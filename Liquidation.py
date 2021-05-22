import logging

from solana.publickey import PublicKey

from baseCli import Group, MarginAccount, TokenValue
from AccountLiquidator import ForceCancelOrdersAccountLiquidator

MARGIN_ACCOUNT_TO_LIQUIDATE = ""

if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO)

    if MARGIN_ACCOUNT_TO_LIQUIDATE == "":
        raise Exception("No margin account to liquidate - try setting the variable MARGIN_ACCOUNT_TO_LIQUIDATE to a margin account public key.")

    from Context import default_context
    from Wallet import default_wallet

    if default_wallet is None:
        print("No default wallet file available.")
    else:
        print("Wallet Balances Before:")
        group = Group.load(default_context)
        balances_before = group.fetch_balances(default_wallet.address)
        TokenValue.report(print, balances_before)

        prices = group.fetch_token_prices()
        margin_account = MarginAccount.load(default_context, PublicKey(MARGIN_ACCOUNT_TO_LIQUIDATE), group)
        intrinsic_balance_sheets_before = margin_account.get_intrinsic_balance_sheets(group)
        print("Margin Account Before:", intrinsic_balance_sheets_before)
        liquidator = ForceCancelOrdersAccountLiquidator(default_context, default_wallet)
        transaction_id = liquidator.liquidate(group, margin_account, prices)
        if transaction_id is None:
            print("No transaction sent.")
        else:
            print("Transaction ID:", transaction_id)
            print("Waiting for confirmation...")

            default_context.wait_for_confirmation(transaction_id)

            group_after = Group.load(default_context)
            margin_account_after_liquidation = MarginAccount.load(default_context, PublicKey(MARGIN_ACCOUNT_TO_LIQUIDATE), group_after)
            intrinsic_balance_sheets_after = margin_account_after_liquidation.get_intrinsic_balance_sheets(group_after)
            print("Margin Account After:", intrinsic_balance_sheets_after)
            print("Wallet Balances After:")
            balances_after = group_after.fetch_balances(default_wallet.address)
            TokenValue.report(print, balances_after)

            print("Wallet Balances Changes:")
            changes = TokenValue.changes(balances_before, balances_after)
            TokenValue.report(print, changes)