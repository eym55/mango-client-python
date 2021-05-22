import logging
import rx
import rx.operators as ops
import time
import typing

from AccountLiquidator import AccountLiquidator
from BaseModel import Group, LiquidationEvent, MarginAccount, MarginAccountMetadata, TokenValue
from Context import Context
from Observables import EventSource
from WalletBalancer import NullWalletBalancer, WalletBalancer

class LiquidationProcessor:
    def __init__(self, context: Context, account_liquidator: AccountLiquidator, wallet_balancer: WalletBalancer, worthwhile_threshold: float = 0.01):
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self.context: Context = context
        self.account_liquidator: AccountLiquidator = account_liquidator
        self.wallet_balancer: WalletBalancer = wallet_balancer
        self.worthwhile_threshold: float = worthwhile_threshold
        self.liquidations: EventSource[LiquidationEvent] = EventSource[LiquidationEvent]()
        self.ripe_accounts: typing.Optional[typing.List[MarginAccount]] = None

    def update_margin_accounts(self, ripe_margin_accounts: typing.List[MarginAccount]):
        self.logger.info(f"Received {len(ripe_margin_accounts)} ripe 🥭 margin accounts to process.")
        self.ripe_accounts = ripe_margin_accounts

    def update_prices(self, prices):
        started_at = time.time()

        if self.ripe_accounts is None:
            self.logger.info("Ripe accounts is None - skipping")
            return

        self.logger.info(f"Running on {len(self.ripe_accounts)} ripe accounts.")
        group = Group.load(self.context)
        updated: typing.List[MarginAccountMetadata] = []
        for margin_account in self.ripe_accounts:
            balance_sheet = margin_account.get_balance_sheet_totals(group, prices)
            balances = margin_account.get_intrinsic_balances(group)
            updated += [MarginAccountMetadata(margin_account, balance_sheet, balances)]

        liquidatable = list(filter(lambda mam: mam.balance_sheet.collateral_ratio <= group.maint_coll_ratio, updated))
        self.logger.info(f"Of those {len(updated)}, {len(liquidatable)} are liquidatable.")

        above_water = list(filter(lambda mam: mam.collateral_ratio > 1, liquidatable))
        self.logger.info(f"Of those {len(liquidatable)} liquidatable margin accounts, {len(above_water)} are 'above water' margin accounts with assets greater than their liabilities.")

        worthwhile = list(filter(lambda mam: mam.assets - mam.liabilities > self.worthwhile_threshold, above_water))
        self.logger.info(f"Of those {len(above_water)} above water margin accounts, {len(worthwhile)} are worthwhile margin accounts with more than ${self.worthwhile_threshold} net assets.")

        self._liquidate_all(group, prices, worthwhile)

        time_taken = time.time() - started_at
        self.logger.info(f"Check of all ripe 🥭 accounts complete. Time taken: {time_taken:.2f} seconds.")

    def _liquidate_all(self, group: Group, prices: typing.List[TokenValue], to_liquidate: typing.List[MarginAccountMetadata]):
        to_process = to_liquidate
        while len(to_process) > 0:
            highest_first = sorted(to_process, key=lambda mam: mam.assets - mam.liabilities, reverse=True)
            highest = highest_first[0]
            try:
                self.account_liquidator.liquidate(group, highest.margin_account, prices)
                self.wallet_balancer.balance(prices)

                updated_margin_account = MarginAccount.load(self.context, highest.margin_account.address, group)
                balance_sheet = updated_margin_account.get_balance_sheet_totals(group, prices)
                balances = updated_margin_account.get_intrinsic_balances(group)
                updated_mam = MarginAccountMetadata(updated_margin_account, balance_sheet, balances)
                if updated_mam.assets - updated_mam.liabilities > self.worthwhile_threshold:
                    self.logger.info(f"Margin account {updated_margin_account.address} has been drained and is no longer worthwhile.")
                else:
                    self.logger.info(f"Margin account {updated_margin_account.address} is still worthwhile - putting it back on list.")
                    to_process += [updated_mam]
            except Exception as exception:
                self.logger.error(f"Failed to liquidate account '{highest.margin_account.address}' - {exception}")
            finally:
                # highest should always be in to_process, but we're outside the try-except block
                # so let's be a little paranoid about it.
                if highest in to_process:
                    to_process.remove(highest)

if __name__ == "__main__":
    from AccountLiquidator import NullAccountLiquidator
    from Context import default_context
    from Observables import create_backpressure_skipping_observer, log_subscription_error
    from Wallet import default_wallet

    from rx.scheduler import ThreadPoolScheduler

    if default_wallet is None:
        raise Exception("No wallet")

    pool_scheduler = ThreadPoolScheduler(2)

    def fetch_prices(context):
        group = Group.load(context)

        def _fetch_prices(_):
            return group.fetch_token_prices()

        return _fetch_prices

    def fetch_margin_accounts(context):
        def _fetch_margin_accounts(_):
            group = Group.load(context)
            return MarginAccount.load_all_for_group_with_open_orders(context, context.program_id, group)
        return _fetch_margin_accounts

    liquidation_processor = LiquidationProcessor(default_context, NullAccountLiquidator(), NullWalletBalancer())

    print("Starting margin account fetcher subscription")
    margin_account_interval = 60
    margin_account_subscription = rx.interval(margin_account_interval).pipe(
        ops.subscribe_on(pool_scheduler),
        ops.start_with(-1),
        ops.map(fetch_margin_accounts(default_context)),
    ).subscribe(create_backpressure_skipping_observer(on_next=liquidation_processor.update_margin_accounts, on_error=log_subscription_error))

    print("Starting price fetcher subscription")
    price_interval = 2
    price_subscription = rx.interval(price_interval).pipe(
        ops.subscribe_on(pool_scheduler),
        ops.map(fetch_prices(default_context))
    ).subscribe(create_backpressure_skipping_observer(on_next=liquidation_processor.update_prices, on_error=log_subscription_error))

    print("Subscriptions created - now just running")

    time.sleep(120)
    print("Disposing")
    price_subscription.dispose()
    margin_account_subscription.dispose()
    print("Disposed")