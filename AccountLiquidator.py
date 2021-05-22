import abc
import datetime
import logging
import typing

from solana.transaction import Transaction

from BaseModel import Group, LiquidationEvent, MarginAccount, MarginAccountMetadata, TokenValue
from Context import Context
from Instructions import ForceCancelOrdersInstructionBuilder, InstructionBuilder, LiquidateInstructionBuilder
from Observables import EventSource
from Wallet import Wallet

class AccountLiquidator(metaclass=abc.ABCMeta):
    def __init__(self):
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)

    @abc.abstractmethod
    def prepare_instructions(self, group: Group, margin_account: MarginAccount, prices: typing.List[TokenValue]) -> typing.List[InstructionBuilder]:
        raise NotImplementedError("AccountLiquidator.prepare_instructions() is not implemented on the base type.")

    @abc.abstractmethod
    def liquidate(self, group: Group, margin_account: MarginAccount, prices: typing.List[TokenValue]) -> typing.Optional[str]:
        raise NotImplementedError("AccountLiquidator.liquidate() is not implemented on the base type.")

class NullAccountLiquidator(AccountLiquidator):
    def __init__(self):
        super().__init__()

    def prepare_instructions(self, group: Group, margin_account: MarginAccount, prices: typing.List[TokenValue]) -> typing.List[InstructionBuilder]:
        return []

    def liquidate(self, group: Group, margin_account: MarginAccount, prices: typing.List[TokenValue]) -> typing.Optional[str]:
        self.logger.info(f"Skipping liquidation of margin account [{margin_account.address}]")
        return None

class ActualAccountLiquidator(AccountLiquidator):
    def __init__(self, context: Context, wallet: Wallet):
        super().__init__()
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self.context = context
        self.wallet = wallet

    def prepare_instructions(self, group: Group, margin_account: MarginAccount, prices: typing.List[TokenValue]) -> typing.List[InstructionBuilder]:
        liquidate_instructions: typing.List[InstructionBuilder] = []
        liquidate_instruction = LiquidateInstructionBuilder.from_margin_account_and_market(self.context, group, self.wallet, margin_account, prices)
        if liquidate_instruction is not None:
            liquidate_instructions += [liquidate_instruction]

        return liquidate_instructions

    def liquidate(self, group: Group, margin_account: MarginAccount, prices: typing.List[TokenValue]) -> typing.Optional[str]:
        instruction_builders = self.prepare_instructions(group, margin_account, prices)

        if len(instruction_builders) == 0:
            return None

        transaction = Transaction()
        for builder in instruction_builders:
            transaction.add(builder.build())

        for instruction in transaction.instructions:
            self.logger.debug("INSTRUCTION")
            self.logger.debug("    Keys:")
            for key in instruction.keys:
                self.logger.debug("        ", f"{key.pubkey}".ljust(45), f"{key.is_signer}".ljust(6), f"{key.is_writable}".ljust(6))
            self.logger.debug("    Data:", " ".join(f"{x:02x}" for x in instruction.data))
            self.logger.debug("    Program ID:", instruction.program_id)

        transaction_response = self.context.client.send_transaction(transaction, self.wallet.account)
        transaction_id = self.context.unwrap_transaction_id_or_raise_exception(transaction_response)
        return transaction_id

class ForceCancelOrdersAccountLiquidator(ActualAccountLiquidator):
    def __init__(self, context: Context, wallet: Wallet):
        super().__init__(context, wallet)

    def prepare_instructions(self, group: Group, margin_account: MarginAccount, prices: typing.List[TokenValue]) -> typing.List[InstructionBuilder]:
        force_cancel_orders_instructions: typing.List[InstructionBuilder] = []
        for index, market_metadata in enumerate(group.markets):
            open_orders = margin_account.open_orders_accounts[index]
            if open_orders is not None:
                market = market_metadata.fetch_market(self.context)
                orders = market.load_orders_for_owner(margin_account.owner)
                order_count = len(orders)
                if order_count > 0:
                    force_cancel_orders_instructions += ForceCancelOrdersInstructionBuilder.multiple_instructions_from_margin_account_and_market(self.context, group, self.wallet, margin_account, market_metadata, order_count)

        all_instructions = force_cancel_orders_instructions + super().prepare_instructions(group, margin_account, prices)

        return all_instructions

class ReportingAccountLiquidator(AccountLiquidator):
    def __init__(self, inner: AccountLiquidator, context: Context, wallet: Wallet, liquidations_publisher: EventSource[LiquidationEvent]):
        super().__init__()
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self.inner: AccountLiquidator = inner
        self.context: Context = context
        self.wallet: Wallet = wallet
        self.liquidations_publisher: EventSource[LiquidationEvent] = liquidations_publisher

    def prepare_instructions(self, group: Group, margin_account: MarginAccount, prices: typing.List[TokenValue]) -> typing.List[InstructionBuilder]:
        return self.inner.prepare_instructions(group, margin_account, prices)

    def liquidate(self, group: Group, margin_account: MarginAccount, prices: typing.List[TokenValue]) -> typing.Optional[str]:
        balance_sheet = margin_account.get_balance_sheet_totals(group, prices)
        balances = margin_account.get_intrinsic_balances(group)
        mam = MarginAccountMetadata(margin_account, balance_sheet, balances)

        balances_before = group.fetch_balances(self.wallet.address)
        self.logger.info("Wallet balances before:")
        TokenValue.report(self.logger.info, balances_before)

        self.logger.info(f"Margin account balances before:\n{mam.balances}")
        self.logger.info(f"Liquidating margin account: {mam.margin_account}\n{mam.balance_sheet}")
        transaction_id = self.inner.liquidate(group, mam.margin_account, prices)
        if transaction_id is None:
            self.logger.info("No transaction sent.")
        else:
            self.logger.info(f"Transaction ID: {transaction_id} - waiting for confirmation...")

            self.context.wait_for_confirmation(transaction_id)

            group_after = Group.load(self.context)
            margin_account_after_liquidation = MarginAccount.load(self.context, mam.margin_account.address, group_after)
            intrinsic_balances_after = margin_account_after_liquidation.get_intrinsic_balances(group_after)
            self.logger.info(f"Margin account balances after: {intrinsic_balances_after}")

            self.logger.info("Wallet Balances After:")
            balances_after = group_after.fetch_balances(self.wallet.address)
            TokenValue.report(self.logger.info, balances_after)

            liquidation_event = LiquidationEvent(datetime.datetime.now(),
                                                 transaction_id,
                                                 self.wallet.address,
                                                 margin_account_after_liquidation.address,
                                                 balances_before,
                                                 balances_after)

            self.logger.info("Wallet Balances Changes:")
            changes = TokenValue.changes(balances_before, balances_after)
            TokenValue.report(self.logger.info, changes)

            self.liquidations_publisher.publish(liquidation_event)

        return transaction_id

if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO)

    from Context import default_context
    from Wallet import default_wallet

    if default_wallet is None:
        print("No default wallet file available.")
    else:
        group = Group.load(default_context)
        prices = group.fetch_token_prices()
        margin_accounts = MarginAccount.load_all_for_owner(default_context, default_wallet.address, group)
        for margin_account in margin_accounts:
            account_liquidator = ActualAccountLiquidator(default_context, default_wallet)
            print(account_liquidator.prepare_instructions(group, margin_account, prices))

            force_cancel_orders_account_liquidator = ForceCancelOrdersAccountLiquidator(default_context, default_wallet)
            print(force_cancel_orders_account_liquidator.prepare_instructions(group, margin_account, prices))


