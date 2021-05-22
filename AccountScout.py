import logging
import typing

from solana.publickey import PublicKey

from baseCli import AccountInfo, Group, MarginAccount, OpenOrders, TokenAccount
from Constants import SYSTEM_PROGRAM_ADDRESS
from Context import Context
from Wallet import Wallet


class ScoutReport:
    def __init__(self, address: PublicKey):
        self.address = address
        self.errors: typing.List[str] = []
        self.warnings: typing.List[str] = []
        self.details: typing.List[str] = []

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    def add_error(self, error) -> None:
        self.errors += [error]

    def add_warning(self, warning) -> None:
        self.warnings += [warning]

    def add_detail(self, detail) -> None:
        self.details += [detail]

    def __str__(self) -> str:
        def _pad(text_list: typing.List[str]) -> str:
            if len(text_list) == 0:
                return "None"
            padding = "\n        "
            return padding.join(map(lambda text: text.replace("\n", padding), text_list))

        error_text = _pad(self.errors)
        warning_text = _pad(self.warnings)
        detail_text = _pad(self.details)
        if len(self.errors) > 0 or len(self.warnings) > 0:
            summary = f"Found {len(self.errors)} error(s) and {len(self.warnings)} warning(s)."
        else:
            summary = "No problems found"

        return f"""« ScoutReport [{self.address}]:
    Summary:
        {summary}

    Errors:
        {error_text}

    Warnings:
        {warning_text}

    Details:
        {detail_text}
»"""

    def __repr__(self) -> str:
        return f"{self}"

ACCOUNT_TO_VERIFY = ""

if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO)

    if ACCOUNT_TO_VERIFY == "":
        raise Exception("No account to look up - try setting the variable ACCOUNT_TO_LOOK_UP to an account public key.")

    from Context import default_context

    print("Context:", default_context)

    root_account_key = PublicKey(ACCOUNT_TO_VERIFY)
    group = Group.load(default_context)

    scout = AccountScout()
    report = scout.verify_account_prepared_for_group(default_context, group, root_account_key)

    print(report)