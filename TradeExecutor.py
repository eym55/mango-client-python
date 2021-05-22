import abc
import logging
import rx
import rx.operators as ops
import typing

from decimal import Decimal
from pyserum.enums import OrderType, Side
from pyserum.market import Market
from solana.account import Account
from solana.publickey import PublicKey

from baseCli import BasketToken, Group, MarketMetadata, OpenOrders, Token, TokenAccount
from Context import Context
from Retrier import retry_context
from Wallet import Wallet

class TradeExecutor(metaclass=abc.ABCMeta):
    def __init__(self):
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)

    @abc.abstractmethod
    def buy(self, symbol: str, quantity: Decimal):
        raise NotImplementedError("TradeExecutor.buy() is not implemented on the base type.")

    @abc.abstractmethod
    def sell(self, symbol: str, quantity: Decimal):
        raise NotImplementedError("TradeExecutor.sell() is not implemented on the base type.")

    @abc.abstractmethod
    def settle(self, market_metadata: MarketMetadata, market: Market) -> typing.List[str]:
        raise NotImplementedError("TradeExecutor.settle() is not implemented on the base type.")

    @abc.abstractmethod
    def wait_for_settlement_completion(self, settlement_transaction_ids: typing.List[str]):
        raise NotImplementedError("TradeExecutor.wait_for_settlement_completion() is not implemented on the base type.")

class NullTradeExecutor(TradeExecutor):
    def __init__(self, reporter: typing.Callable[[str], None] = None):
        super().__init__()
        self.reporter = reporter or (lambda _: None)

    def buy(self, symbol: str, quantity: Decimal):
        self.logger.info(f"Skipping BUY trade of {quantity:,.8f} of '{symbol}'.")
        self.reporter(f"Skipping BUY trade of {quantity:,.8f} of '{symbol}'.")

    def sell(self, symbol: str, quantity: Decimal):
        self.logger.info(f"Skipping SELL trade of {quantity:,.8f} of '{symbol}'.")
        self.reporter(f"Skipping SELL trade of {quantity:,.8f} of '{symbol}'.")

    def settle(self, market_metadata: MarketMetadata, market: Market) -> typing.List[str]:
        self.logger.info(f"Skipping settling of '{market_metadata.base.token.name}' and '{market_metadata.quote.token.name}' in market {market_metadata.address}.")
        self.reporter(f"Skipping settling of '{market_metadata.base.token.name}' and '{market_metadata.quote.token.name}' in market {market_metadata.address}.")
        return []

    def wait_for_settlement_completion(self, settlement_transaction_ids: typing.List[str]):
        self.logger.info("Skipping waiting for settlement.")
        self.reporter("Skipping waiting for settlement.")

class SerumImmediateTradeExecutor(TradeExecutor):
    def __init__(self, context: Context, wallet: Wallet, group: Group, price_adjustment_factor: Decimal = Decimal(0), reporter: typing.Callable[[str], None] = None):
        super().__init__()
        self.context: Context = context
        self.wallet: Wallet = wallet
        self.group: Group = group
        self.price_adjustment_factor: Decimal = price_adjustment_factor

        def report(text):
            self.logger.info(text)
            reporter(text)

        def just_log(text):
            self.logger.info(text)

        if reporter is not None:
            self.reporter = report
        else:
            self.reporter = just_log

    def buy(self, symbol: str, quantity: Decimal):
        market_metadata, base_token, quote_token = self._tokens_and_market(symbol)
        market = market_metadata.fetch_market(self.context)
        self.reporter(f"BUY order market: {market_metadata.address} {market}")

        asks = market.load_asks()
        top_ask = next(asks.orders())
        top_price = Decimal(top_ask.info.price)
        increase_factor = Decimal(1) + self.price_adjustment_factor
        price = top_price * increase_factor
        self.reporter(f"Price {price} - adjusted by {self.price_adjustment_factor} from {top_price}")

        source_token_account = TokenAccount.fetch_largest_for_owner_and_token(self.context, self.wallet.address, quote_token)
        self.reporter(f"Source token account: {source_token_account}")
        if source_token_account is None:
            raise Exception(f"Could not find source token account for '{quote_token}'")

        self._execute(
            market_metadata,
            market,
            Side.BUY,
            source_token_account,
            base_token,
            quote_token,
            price,
            quantity
        )

    def sell(self, symbol: str, quantity: Decimal):
        market_metadata, base_token, quote_token = self._tokens_and_market(symbol)
        market = market_metadata.fetch_market(self.context)
        self.reporter(f"SELL order market: {market_metadata.address} {market}")

        bids = market.load_bids()
        bid_orders = list(bids.orders())
        top_bid = bid_orders[len(bid_orders) - 1]
        top_price = Decimal(top_bid.info.price)
        decrease_factor = Decimal(1) - self.price_adjustment_factor
        price = top_price * decrease_factor
        self.reporter(f"Price {price} - adjusted by {self.price_adjustment_factor} from {top_price}")

        source_token_account = TokenAccount.fetch_largest_for_owner_and_token(self.context, self.wallet.address, base_token)
        self.reporter(f"Source token account: {source_token_account}")
        if source_token_account is None:
            raise Exception(f"Could not find source token account for '{base_token}'")

        self._execute(
            market_metadata,
            market,
            Side.SELL,
            source_token_account,
            base_token,
            quote_token,
            price,
            quantity
        )

    def _execute(self, market_metadata: MarketMetadata, market: Market, side: Side, source_token_account: TokenAccount, base_token: Token, quote_token: Token, price: Decimal, quantity: Decimal):
        client_id, place_order_transaction_id = self._place_order(market_metadata, market, base_token, quote_token, source_token_account.address, self.wallet.account, OrderType.IOC, side, price, quantity)
        self._wait_for_order_fill(market, client_id)
        settlement_transaction_ids = self.settle(market_metadata, market)
        self.wait_for_settlement_completion(settlement_transaction_ids)
        self.reporter("Order execution complete")

    def _place_order(self, market_metadata: MarketMetadata, market: Market, base_token: Token, quote_token: Token, paying_token_address: PublicKey, account: Account, order_type: OrderType, side: Side, price: Decimal, quantity: Decimal) -> typing.Tuple[int, str]:
        to_pay = price * quantity
        self.logger.info(f"{side.name}ing {quantity} of {base_token.name} at {price} for {to_pay} on {base_token.name}/{quote_token.name} from {paying_token_address}.")

        client_id = self.context.random_client_id()
        self.reporter(f"""Placing order
    paying_token_address: {paying_token_address}
    account: {account.public_key()}
    order_type: {order_type.name}
    side: {side.name}
    price: {float(price)}
    quantity: {float(quantity)}
    client_id: {client_id}""")
        with retry_context(market.place_order, 5) as retrier:
            response = retrier.run(paying_token_address, account, order_type, side, float(price), float(quantity), client_id)

        transaction_id = self.context.unwrap_transaction_id_or_raise_exception(response)
        self.reporter(f"Order transaction ID: {transaction_id}")

        return client_id, transaction_id

    def _wait_for_order_fill(self, market: Market, client_id: int, max_wait_in_seconds: int = 60):
        self.logger.info(f"Waiting up to {max_wait_in_seconds} seconds for {client_id}.")
        return rx.interval(1.0).pipe(
            ops.flat_map(lambda _: market.load_event_queue()),
            ops.skip_while(lambda item: item.client_order_id != client_id),
            ops.skip_while(lambda item: not item.event_flags.fill),
            ops.first(),
            ops.map(lambda _: True),
            ops.timeout(max_wait_in_seconds, rx.return_value(False))
        ).run()

    def settle(self, market_metadata: MarketMetadata, market: Market) -> typing.List[str]:
        base_token_account = TokenAccount.fetch_or_create_largest_for_owner_and_token(self.context, self.wallet.account, market_metadata.base.token)
        quote_token_account = TokenAccount.fetch_or_create_largest_for_owner_and_token(self.context, self.wallet.account, market_metadata.quote.token)

        open_orders = OpenOrders.load_for_market_and_owner(self.context, market_metadata.address, self.wallet.account.public_key(), self.context.dex_program_id, market_metadata.base.token.decimals, market_metadata.quote.token.decimals)

        transaction_ids = []
        for open_order_account in open_orders:
            if (open_order_account.base_token_free > 0) or (open_order_account.quote_token_free > 0):
                self.reporter(f"Need to settle open orders: {open_order_account}\nBase account: {base_token_account.address}\nQuote account: {quote_token_account.address}")
                response = market.settle_funds(self.wallet.account, open_order_account.to_pyserum(), base_token_account.address, quote_token_account.address)
                transaction_id = self.context.unwrap_transaction_id_or_raise_exception(response)
                self.reporter(f"Settlement transaction ID: {transaction_id}")
                transaction_ids += [transaction_id]

        return transaction_ids

    def wait_for_settlement_completion(self, settlement_transaction_ids: typing.List[str]):
        if len(settlement_transaction_ids) > 0:
            self.reporter(f"Waiting on settlement transaction IDs: {settlement_transaction_ids}")
            for settlement_transaction_id in settlement_transaction_ids:
                self.reporter(f"Waiting on specific settlement transaction ID: {settlement_transaction_id}")
                self.context.wait_for_confirmation(settlement_transaction_id)
            self.reporter("All settlement transaction IDs confirmed.")

    def _tokens_and_market(self, symbol: str) -> typing.Tuple[MarketMetadata, Token, Token]:
        base_token = BasketToken.find_by_name(self.group.basket_tokens, symbol).token
        quote_token = self.group.shared_quote_token.token
        self.logger.info(f"Base token: {base_token}")
        self.logger.info(f"Quote token: {quote_token}")

        market_metadata = None
        for group_market in self.group.markets:
            if group_market.base.token == base_token and group_market.quote.token == quote_token:
                market_metadata = group_market
                break

        if market_metadata is None:
            raise Exception(f"Market for '{base_token.name}/{quote_token.name}' not in group '{self.group.address}'.")

        market = market_metadata.fetch_market(self.context)
        self.logger.info(f"Market: {market_metadata.address} {market}")

        return (market_metadata, base_token, quote_token)

    def __str__(self) -> str:
        return f"""« SerumImmediateTradeExecutor [{self.price_adjustment_factor}] »"""

    def __repr__(self) -> str:
        return f"{self}"

if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO)

    from Context import default_context
    from Wallet import default_wallet

    if default_wallet is None:
        print("No default wallet file available.")
    else:
        print(default_context)
        group = Group.load(default_context)

        symbol = "ETH"
        trade_executor = SerumImmediateTradeExecutor(default_context, default_wallet, group, Decimal(0.05))

        # WARNING! Uncommenting the following lines will actually try to trade on Serum using the
        # default wallet!
#         trade_executor.sell("ETH", 0.1)
#         trade_executor.buy("ETH", 0.1)