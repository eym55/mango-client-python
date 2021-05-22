import abc
import logging
import typing

from decimal import Decimal
from solana.publickey import PublicKey

from baseCli import BasketToken, Group, Token, TokenValue
from Context import Context
from TradeExecutor import TradeExecutor
from Wallet import Wallet


class TargetBalance(metaclass=abc.ABCMeta):
    def __init__(self, token: Token):
        self.token = token

    @abc.abstractmethod
    def resolve(self, current_price: Decimal, total_value: Decimal) -> TokenValue:
        raise NotImplementedError("TargetBalance.resolve() is not implemented on the base type.")

    def __repr__(self) -> str:
        return f"{self}"


class FixedTargetBalance(TargetBalance):
    def __init__(self, token: Token, value: Decimal):
        super().__init__(token)
        self.value = value

    def resolve(self, current_price: Decimal, total_value: Decimal) -> TokenValue:
        return TokenValue(self.token, self.value)

    def __str__(self) -> str:
        return f"""« FixedTargetBalance [{self.value} {self.token.name}] »"""

class PercentageTargetBalance(TargetBalance):
    def __init__(self, token: Token, target_percentage: Decimal):
        super().__init__(token)
        self.target_fraction = target_percentage / 100

    def resolve(self, current_price: Decimal, total_value: Decimal) -> TokenValue:
        target_value = total_value * self.target_fraction
        target_size = target_value / current_price
        return TokenValue(self.token, target_size)

    def __str__(self) -> str:
        return f"""« PercentageTargetBalance [{self.target_fraction * 100}% {self.token.name}] »"""

class TargetBalanceParser:
    def __init__(self, tokens: typing.List[Token]):
        self.tokens = tokens

    def parse(self, to_parse: str) -> TargetBalance:
        try:
            token_name, value = to_parse.split(":")
        except Exception as exception:
            raise Exception(f"Could not parse target balance '{to_parse}'") from exception

        token = Token.find_by_name(self.tokens, token_name)

        # The value we have may be an int (like 27), a fraction (like 0.1) or a percentage
        # (like 25%). In all cases we want the number as a number, but we also want to know if
        # we have a percent or not
        values = value.split("%")
        numeric_value_string = values[0]
        try:
            numeric_value = Decimal(numeric_value_string)
        except Exception as exception:
            raise Exception(f"Could not parse '{numeric_value_string}' as a decimal number. It should be formatted as a decimal number, e.g. '2.345', with no surrounding spaces.") from exception

        if len(values) > 2:
            raise Exception(f"Could not parse '{value}' as a decimal percentage. It should be formatted as a decimal number followed by a percentage sign, e.g. '30%', with no surrounding spaces.")

        if len(values) == 1:
            return FixedTargetBalance(token, numeric_value)
        else:
            return PercentageTargetBalance(token, numeric_value)

def sort_changes_for_trades(changes: typing.List[TokenValue]) -> typing.List[TokenValue]:
    return sorted(changes, key=lambda change: change.value)

def calculate_required_balance_changes(current_balances: typing.List[TokenValue], desired_balances: typing.List[TokenValue]) -> typing.List[TokenValue]:
    changes: typing.List[TokenValue] = []
    for desired in desired_balances:
        current = TokenValue.find_by_token(current_balances, desired.token)
        change = TokenValue(desired.token, desired.value - current.value)
        changes += [change]

    return changes

class FilterSmallChanges:
    def __init__(self, action_threshold: Decimal, balances: typing.List[TokenValue], prices: typing.List[TokenValue]):
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self.prices: typing.Dict[str, TokenValue] = {}
        total = Decimal(0)
        for balance in balances:
            price = TokenValue.find_by_token(prices, balance.token)
            self.prices[f"{price.token.mint}"] = price
            total += price.value * balance.value
        self.total_balance = total
        self.action_threshold_value = total * action_threshold
        self.logger.info(f"Wallet total balance of {total} gives action threshold value of {self.action_threshold_value}")

    def allow(self, token_value: TokenValue) -> bool:
        price = self.prices[f"{token_value.token.mint}"]
        value = price.value * token_value.value
        absolute_value = value.copy_abs()
        result = absolute_value > self.action_threshold_value

        self.logger.info(f"Value of {token_value.token.name} trade is {absolute_value}, threshold value is {self.action_threshold_value}. Is this worth doing? {result}.")
        return result

class WalletBalancer(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def balance(self, prices: typing.List[TokenValue]):
        raise NotImplementedError("WalletBalancer.balance() is not implemented on the base type.")

class NullWalletBalancer(WalletBalancer):
    def balance(self, prices: typing.List[TokenValue]):
        pass

class LiveWalletBalancer(WalletBalancer):
    def __init__(self, context: Context, wallet: Wallet, trade_executor: TradeExecutor, action_threshold: Decimal, tokens: typing.List[Token], target_balances: typing.List[TargetBalance]):
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self.context: Context = context
        self.wallet: Wallet = wallet
        self.trade_executor: TradeExecutor = trade_executor
        self.action_threshold: Decimal = action_threshold
        self.tokens: typing.List[Token] = tokens
        self.target_balances: typing.List[TargetBalance] = target_balances

    def balance(self, prices: typing.List[TokenValue]):
        padding = "\n    "

        def balances_report(balances) -> str:
            return padding.join(list([f"{bal}" for bal in balances]))

        current_balances = self._fetch_balances()
        total_value = Decimal(0)
        for bal in current_balances:
            price = TokenValue.find_by_token(prices, bal.token)
            value = bal.value * price.value
            total_value += value
        self.logger.info(f"Starting balances: {padding}{balances_report(current_balances)} - total: {total_value}")
        resolved_targets: typing.List[TokenValue] = []
        for target in self.target_balances:
            price = TokenValue.find_by_token(prices, target.token)
            resolved_targets += [target.resolve(price.value, total_value)]

        balance_changes = calculate_required_balance_changes(current_balances, resolved_targets)
        self.logger.info(f"Full balance changes: {padding}{balances_report(balance_changes)}")

        dont_bother = FilterSmallChanges(self.action_threshold, current_balances, prices)
        filtered_changes = list(filter(dont_bother.allow, balance_changes))
        self.logger.info(f"Filtered balance changes: {padding}{balances_report(filtered_changes)}")
        if len(filtered_changes) == 0:
            self.logger.info("No balance changes to make.")
            return

        sorted_changes = sort_changes_for_trades(filtered_changes)
        self._make_changes(sorted_changes)
        updated_balances = self._fetch_balances()
        self.logger.info(f"Finishing balances: {padding}{balances_report(updated_balances)}")

    def _make_changes(self, balance_changes: typing.List[TokenValue]):
        self.logger.info(f"Balance changes to make: {balance_changes}")
        for change in balance_changes:
            if change.value < 0:
                self.trade_executor.sell(change.token.name, change.value.copy_abs())
            else:
                self.trade_executor.buy(change.token.name, change.value.copy_abs())

    def _fetch_balances(self) -> typing.List[TokenValue]:
        balances: typing.List[TokenValue] = []
        for token in self.tokens:
            balance = TokenValue.fetch_total_value(self.context, self.wallet.address, token)
            balances += [balance]

        return balances

if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO)

    from Context import default_context

    group = Group.load(default_context)
    eth = BasketToken.find_by_name(group.basket_tokens, "eth").token
    btc = BasketToken.find_by_name(group.basket_tokens, "btc").token
    usdt = BasketToken.find_by_name(group.basket_tokens, "usdt").token

    parser = TargetBalanceParser([eth, btc])
    eth_target = parser.parse("ETH:20%")
    btc_target = parser.parse("btc:0.05")
    prices = [Decimal("60000"), Decimal("4000"), Decimal("1")]  # Ordered as per Group index ordering
    desired_balances = []
    for target in [eth_target, btc_target]:
        token_index = group.price_index_of_token(target.token)
        price = prices[token_index]
        resolved = target.resolve(price, Decimal(10000))
        desired_balances += [resolved]

    assert(desired_balances[0].token.name == "ETH")
    assert(desired_balances[0].value == Decimal("0.5"))
    assert(desired_balances[1].token.name == "BTC")
    assert(desired_balances[1].value == Decimal("0.05"))

    current_balances = [
        TokenValue(eth, Decimal("0.6")),  # Worth $2,400 at the test prices
        TokenValue(btc, Decimal("0.01")),  # Worth $6,00 at the test prices
        TokenValue(usdt, Decimal("7000")),  # Remainder of $10,000 minus above token values
    ]

    changes = calculate_required_balance_changes(current_balances, desired_balances)
    for change in changes:
        order_type = "BUY" if change.value > 0 else "SELL"
        print(f"{change.token.name} {order_type} {change.value}")

    # To get from our current balances of 0.6 ETH and 0.01 BTC to our desired balances of
    # 0.5 ETH and 0.05 BTC, we need to sell 0.1 ETH and buy 0.04 BTC. But we want to do the sell
    # first, to make sure we have the proper liquidity when it comes to buying.
    sorted_changes = sort_changes_for_trades(changes)
    assert(sorted_changes[0].token.name == "ETH")
    assert(sorted_changes[0].value == Decimal("-0.1"))
    assert(sorted_changes[1].token.name == "BTC")
    assert(sorted_changes[1].value == Decimal("0.04"))

