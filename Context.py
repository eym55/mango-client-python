import logging
import os
import random
import time
import typing

from decimal import Decimal
from solana.publickey import PublicKey
from solana.rpc.api import Client
from solana.rpc.types import MemcmpOpts, RPCError, RPCResponse
from solana.rpc.commitment import Commitment, Single

from Constants import MangoConstants, SOL_DECIMAL_DIVISOR

class Context:
    def __init__(self, cluster: str, cluster_url: str, program_id: PublicKey, dex_program_id: PublicKey,
                 group_name: str, group_id: PublicKey):
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self.cluster: str = cluster
        self.cluster_url: str = cluster_url
        self.client: Client = Client(cluster_url)
        self.program_id: PublicKey = program_id
        self.dex_program_id: PublicKey = dex_program_id
        self.group_name: str = group_name
        self.group_id: PublicKey = group_id
        self.commitment: Commitment = Single
        self.encoding: str = "base64"

    def fetch_sol_balance(self, account_public_key: PublicKey) -> Decimal:
        result = self.client.get_balance(account_public_key, commitment=self.commitment)
        value = Decimal(result["result"]["value"])
        return value / SOL_DECIMAL_DIVISOR

    def fetch_program_accounts_for_owner(self, program_id: PublicKey, owner: PublicKey):
        memcmp_opts = [
            MemcmpOpts(offset=40, bytes=str(owner)),
        ]

        return self.client.get_program_accounts(program_id, memcmp_opts=memcmp_opts, commitment=self.commitment, encoding=self.encoding)

    def unwrap_or_raise_exception(self, response: RPCResponse) -> typing.Any:
        if "error" in response:
            if response["error"] is str:
                message: str = typing.cast(str, response["error"])
                code: int = -1
            else:
                error: RPCError = typing.cast(RPCError, response["error"])
                message = error["message"]
                code = error["code"]
            raise Exception(f"Error response from server: '{message}', code: {code}")

        return response["result"]

    def unwrap_transaction_id_or_raise_exception(self, response: RPCResponse) -> str:
        return typing.cast(str, self.unwrap_or_raise_exception(response))

    def random_client_id(self) -> int:
        # 9223372036854775807 is sys.maxsize for 64-bit systems, with a bit_length of 63.
        # We explicitly want to use a max of 64-bits though, so we use the number instead of
        # sys.maxsize, which could be lower on 32-bit systems or higher on 128-bit systems.
        return random.randrange(9223372036854775807)

    @staticmethod
    def _lookup_name_by_address(address: PublicKey, collection: typing.Dict[str, str]) -> typing.Optional[str]:
        address_string = str(address)
        for stored_name, stored_address in collection.items():
            if stored_address == address_string:
                return stored_name
        return None

    @staticmethod
    def _lookup_address_by_name(name: str, collection: typing.Dict[str, str]) -> typing.Optional[PublicKey]:
        for stored_name, stored_address in collection.items():
            if stored_name == name:
                return PublicKey(stored_address)
        return None

    def lookup_group_name(self, group_address: PublicKey) -> str:
        for name, values in MangoConstants[self.cluster]["mango_groups"].items():
            if values["mango_group_pk"] == str(group_address):
                return name
        return "« Unknown Group »"

    def lookup_market_name(self, market_address: PublicKey) -> str:
        return Context._lookup_name_by_address(market_address, MangoConstants[self.cluster]["spot_markets"]) or "« Unknown Market »"

    def lookup_oracle_name(self, token_address: PublicKey) -> str:
        return Context._lookup_name_by_address(token_address, MangoConstants[self.cluster]["oracles"]) or "« Unknown Oracle »"

    def lookup_token_name(self, token_address: PublicKey) -> typing.Optional[str]:
        return Context._lookup_name_by_address(token_address, MangoConstants[self.cluster]["symbols"])

    def lookup_token_address(self, token_name: str) -> typing.Optional[PublicKey]:
        return Context._lookup_address_by_name(token_name, MangoConstants[self.cluster]["symbols"])

    def wait_for_confirmation(self, transaction_id: str, max_wait_in_seconds: int = 60) -> None:
        self.logger.info(f"Waiting up to {max_wait_in_seconds} seconds for {transaction_id}.")
        for wait in range(0, max_wait_in_seconds):
            time.sleep(1)
            confirmed = default_context.client.get_confirmed_transaction(transaction_id)
            if confirmed["result"] is not None:
                self.logger.info(f"Confirmed after {wait} seconds.")
                return
        self.logger.info(f"Timed out after {wait} seconds waiting on transaction {transaction_id}.")

    def __str__(self) -> str:
        return f"""« Context:
    Cluster: {self.cluster}
    Cluster URL: {self.cluster_url}
    Program ID: {self.program_id}
    DEX Program ID: {self.dex_program_id}
    Group Name: {self.group_name}
    Group ID: {self.group_id}
»"""

    def __repr__(self) -> str:
        return f"{self}"

default_cluster = os.environ.get("CLUSTER") or "mainnet-beta"
default_cluster_url = os.environ.get("CLUSTER_URL") or MangoConstants["cluster_urls"][default_cluster]

default_program_id = PublicKey(MangoConstants[default_cluster]["mango_program_id"])
default_dex_program_id = PublicKey(MangoConstants[default_cluster]["dex_program_id"])

default_group_name = os.environ.get("GROUP_NAME") or "BTC_ETH_USDT"
default_group_id = PublicKey(MangoConstants[default_cluster]["mango_groups"][default_group_name]["mango_group_pk"])

default_context = Context(default_cluster, default_cluster_url, default_program_id,
                          default_dex_program_id, default_group_name, default_group_id)

solana_cluster_url = "https://api.mainnet-beta.solana.com"

solana_context = Context(default_cluster, solana_cluster_url, default_program_id,
                         default_dex_program_id, default_group_name, default_group_id)

serum_cluster_url = "https://solana-api.projectserum.com"

serum_context = Context(default_cluster, serum_cluster_url, default_program_id,
                        default_dex_program_id, default_group_name, default_group_id)

if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO)

    print(default_context)

    print("Lookup ETH token name result:", default_context.lookup_token_name(PublicKey("2FPyTwcZLUg1MDrwsyoP4D6s1tM7hAkHYRjkNb5w6Pxk")))
    print("Lookup ETH token address result:", default_context.lookup_token_address("ETH"))
    print("Lookup BTC/USDC market name result:", default_context.lookup_market_name(PublicKey("CVfYa8RGXnuDBeGmniCcdkBwoLqVxh92xB1JqgRQx3F")))

    # Fill out your account address between the quotes below
    MY_ACCOUNT_ADDRESS = ""
    # Don't edit anything beyond here.

    if MY_ACCOUNT_ADDRESS != "":
        account_key = PublicKey(MY_ACCOUNT_ADDRESS)
        print("SOL balance:", default_context.fetch_sol_balance(account_key))