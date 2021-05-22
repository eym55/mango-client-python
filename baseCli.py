import abc
import datetime
import enum
import logging
import time
import typing
import aysncio

import Layout as layouts

from decimal import Decimal
from pyserum.market import Market
from pyserum.open_orders_account import OpenOrdersAccount
from solana.account import Account
from solana.publickey import PublicKey
from solana.rpc.commitment import Single
from solana.rpc.types import MemcmpOpts, TokenAccountOpts, RPCMethod, RPCResponse
from spl.token.client import Token as SplToken
from spl.token.constants import TOKEN_PROGRAM_ID

from Constants import NUM_MARKETS, NUM_TOKENS, SOL_DECIMALS, SYSTEM_PROGRAM_ADDRESS, MAX_RATE,OPTIMAL_RATE,OPTIMAL_UTIL
from Context import Context
from Decoder import decode_binary, encode_binary, encode_key


class Version(enum.Enum):
    UNSPECIFIED = 0
    V1 = 1
    V2 = 2
    V3 = 3
    V4 = 4
    V5 = 5

class InstructionType(enum.IntEnum):
    InitMangoGroup = 0
    InitMarginAccount = 1
    Deposit = 2
    Withdraw = 3
    Borrow = 4
    SettleBorrow = 5
    Liquidate = 6
    DepositSrm = 7
    WithdrawSrm = 8
    PlaceOrder = 9
    SettleFunds = 10
    CancelOrder = 11
    CancelOrderByClientId = 12
    ChangeBorrowLimit = 13
    PlaceAndSettle = 14
    ForceCancelOrders = 15
    PartialLiquidate = 16

    def __str__(self):
        return self.name

class AccountInfo:
    def __init__(self, address: PublicKey, executable: bool, lamports: Decimal, owner: PublicKey, rent_epoch: Decimal, data: bytes):
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self.address: PublicKey = address
        self.executable: bool = executable
        self.lamports: Decimal = lamports
        self.owner: PublicKey = owner
        self.rent_epoch: Decimal = rent_epoch
        self.data: bytes = data

    def encoded_data(self) -> typing.List:
        return encode_binary(self.data)

    def __str__(self) -> str:
        return f"""« AccountInfo [{self.address}]:
            Owner: {self.owner}
            Executable: {self.executable}
            Lamports: {self.lamports}
            Rent Epoch: {self.rent_epoch}
            »"""

    def __repr__(self) -> str:
        return f"{self}"

    @staticmethod
    async def load(context: Context, address: PublicKey) -> typing.Optional["AccountInfo"]:
        response: RPCResponse = context.client.get_account_info(address)
        result = context.unwrap_or_raise_exception(response)
        if result["value"] is None:
            return None
        return AccountInfo._from_response_values(result["value"], address)



    @staticmethod
    async def load_multiple(context: Context, addresses: typing.List[PublicKey]) -> typing.List["AccountInfo"]:
        address_strings = list(map(PublicKey.__str__, addresses))
        response = context.client._provider.make_request(RPCMethod("getMultipleAccounts"), address_strings)
        response_value_list = zip(response["result"]["value"], addresses)
        return list(map(lambda pair: AccountInfo._from_response_values(pair[0], pair[1]), response_value_list))

    @staticmethod
    def _from_response_values(response_values: typing.Dict[str, typing.Any], address: PublicKey) -> "AccountInfo":
        executable = bool(response_values["executable"])
        lamports = Decimal(response_values["lamports"])
        owner = PublicKey(response_values["owner"])
        rent_epoch = Decimal(response_values["rentEpoch"])
        data = decode_binary(response_values["data"])
        return AccountInfo(address, executable, lamports, owner, rent_epoch, data)

    @staticmethod
    def from_response(response: RPCResponse, address: PublicKey) -> "AccountInfo":
        return AccountInfo._from_response_values(response["result"]["value"], address)

class AddressableAccount(metaclass=abc.ABCMeta):
    def __init__(self, account_info: AccountInfo):
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self.account_info = account_info

    @property
    def address(self) -> PublicKey:
        return self.account_info.address

    def __repr__(self) -> str:
        return f"{self}"

class SerumAccountFlags:
    def __init__(self, version: Version, initialized: bool, market: bool, open_orders: bool,
                 request_queue: bool, event_queue: bool, bids: bool, asks: bool, disabled: bool):
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self.version: Version = version
        self.initialized = initialized
        self.market = market
        self.open_orders = open_orders
        self.request_queue = request_queue
        self.event_queue = event_queue
        self.bids = bids
        self.asks = asks
        self.disabled = disabled

    @staticmethod
    def from_layout(layout: layouts.SERUM_ACCOUNT_FLAGS) -> "SerumAccountFlags":
        return SerumAccountFlags(Version.UNSPECIFIED, layout.initialized, layout.market,
                                 layout.open_orders, layout.request_queue, layout.event_queue,
                                 layout.bids, layout.asks, layout.disabled)

    def __str__(self) -> str:
        flags: typing.List[typing.Optional[str]] = []
        flags += ["initialized" if self.initialized else None]
        flags += ["market" if self.market else None]
        flags += ["open_orders" if self.open_orders else None]
        flags += ["request_queue" if self.request_queue else None]
        flags += ["event_queue" if self.event_queue else None]
        flags += ["bids" if self.bids else None]
        flags += ["asks" if self.asks else None]
        flags += ["disabled" if self.disabled else None]
        flag_text = " | ".join(flag for flag in flags if flag is not None) or "None"
        return f"« SerumAccountFlags: {flag_text} »"

    def __repr__(self) -> str:
        return f"{self}"

class MangoAccountFlags:
    def __init__(self, version: Version, initialized: bool, group: bool, margin_account: bool, srm_account: bool):
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self.version: Version = version
        self.initialized = initialized
        self.group = group
        self.margin_account = margin_account
        self.srm_account = srm_account

    @staticmethod
    def from_layout(layout: layouts.MANGO_ACCOUNT_FLAGS) -> "MangoAccountFlags":
        return MangoAccountFlags(Version.UNSPECIFIED, layout.initialized, layout.group, layout.margin_account,
                                 layout.srm_account)

    def __str__(self) -> str:
        flags: typing.List[typing.Optional[str]] = []
        flags += ["initialized" if self.initialized else None]
        flags += ["group" if self.group else None]
        flags += ["margin_account" if self.margin_account else None]
        flags += ["srm_account" if self.srm_account else None]
        flag_text = " | ".join(flag for flag in flags if flag is not None) or "None"
        return f"« MangoAccountFlags: {flag_text} »"

    def __repr__(self) -> str:
        return f"{self}"

class Index:
    def __init__(self, version: Version, last_update: datetime.datetime, borrow: Decimal, deposit: Decimal):
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self.version: Version = version
        self.last_update: datetime.datetime = last_update
        self.borrow: Decimal = borrow
        self.deposit: Decimal = deposit

    @staticmethod
    def from_layout(layout: layouts.INDEX, decimals: Decimal) -> "Index":
        borrow = layout.borrow / Decimal(10 ** decimals)
        deposit = layout.deposit / Decimal(10 ** decimals)
        return Index(Version.UNSPECIFIED, layout.last_update, borrow, deposit)

    def __str__(self) -> str:
        return f"« Index: Borrow: {self.borrow:,.8f}, Deposit: {self.deposit:,.8f} [last update: {self.last_update}] »"

    def __repr__(self) -> str:
        return f"{self}"

class AggregatorConfig:
    def __init__(self, version: Version, description: str, decimals: Decimal, restart_delay: Decimal,
                 max_submissions: Decimal, min_submissions: Decimal, reward_amount: Decimal,
                 reward_token_account: PublicKey):
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self.version: Version = version
        self.description: str = description
        self.decimals: Decimal = decimals
        self.restart_delay: Decimal = restart_delay
        self.max_submissions: Decimal = max_submissions
        self.min_submissions: Decimal = min_submissions
        self.reward_amount: Decimal = reward_amount
        self.reward_token_account: PublicKey = reward_token_account

    @staticmethod
    def from_layout(layout: layouts.AGGREGATOR_CONFIG) -> "AggregatorConfig":
        return AggregatorConfig(Version.UNSPECIFIED, layout.description, layout.decimals,
                                layout.restart_delay, layout.max_submissions, layout.min_submissions,
                                layout.reward_amount, layout.reward_token_account)

    def __str__(self) -> str:
        return f"« AggregatorConfig: '{self.description}', Decimals: {self.decimals} [restart delay: {self.restart_delay}], Max: {self.max_submissions}, Min: {self.min_submissions}, Reward: {self.reward_amount}, Reward Account: {self.reward_token_account} »"

    def __repr__(self) -> str:
        return f"{self}"

class Round:
    def __init__(self, version: Version, id: Decimal, created_at: datetime.datetime, updated_at: datetime.datetime):
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self.version: Version = version
        self.id: Decimal = id
        self.created_at: datetime.datetime = created_at
        self.updated_at: datetime.datetime = updated_at

    @staticmethod
    def from_layout(layout: layouts.ROUND) -> "Round":
        return Round(Version.UNSPECIFIED, layout.id, layout.created_at, layout.updated_at)

    def __str__(self) -> str:
        return f"« Round[{self.id}], Created: {self.updated_at}, Updated: {self.updated_at} »"

    def __repr__(self) -> str:
        return f"{self}"

class Answer:
    def __init__(self, version: Version, round_id: Decimal, median: Decimal, created_at: datetime.datetime, updated_at: datetime.datetime):
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self.version: Version = version
        self.round_id: Decimal = round_id
        self.median: Decimal = median
        self.created_at: datetime.datetime = created_at
        self.updated_at: datetime.datetime = updated_at

    @staticmethod
    def from_layout(layout: layouts.ANSWER) -> "Answer":
        return Answer(Version.UNSPECIFIED, layout.round_id, layout.median, layout.created_at, layout.updated_at)

    def __str__(self) -> str:
        return f"« Answer: Round[{self.round_id}], Median: {self.median:,.8f}, Created: {self.updated_at}, Updated: {self.updated_at} »"

    def __repr__(self) -> str:
        return f"{self}"

class Aggregator(AddressableAccount):
    def __init__(self, account_info: AccountInfo, version: Version, config: AggregatorConfig,
                 initialized: bool, name: str, owner: PublicKey, round_: Round,
                 round_submissions: PublicKey, answer: Answer, answer_submissions: PublicKey):
        super().__init__(account_info)
        self.version: Version = version
        self.config: AggregatorConfig = config
        self.initialized: bool = initialized
        self.name: str = name
        self.owner: PublicKey = owner
        self.round: Round = round_
        self.round_submissions: PublicKey = round_submissions
        self.answer: Answer = answer
        self.answer_submissions: PublicKey = answer_submissions

    @property
    def price(self) -> Decimal:
        return self.answer.median / (10 ** self.config.decimals)

    @staticmethod
    def from_layout(layout: layouts.AGGREGATOR, account_info: AccountInfo, name: str) -> "Aggregator":
        config = AggregatorConfig.from_layout(layout.config)
        initialized = bool(layout.initialized)
        round_ = Round.from_layout(layout.round)
        answer = Answer.from_layout(layout.answer)

        return Aggregator(account_info, Version.UNSPECIFIED, config, initialized, name, layout.owner,
                          round_, layout.round_submissions, answer, layout.answer_submissions)

    @staticmethod
    def parse(context: Context, account_info: AccountInfo) -> "Aggregator":
        data = account_info.data
        if len(data) != layouts.AGGREGATOR.sizeof():
            raise Exception(f"Data length ({len(data)}) does not match expected size ({layouts.AGGREGATOR.sizeof()})")

        name = context.lookup_oracle_name(account_info.address)
        layout = layouts.AGGREGATOR.parse(data)
        return Aggregator.from_layout(layout, account_info, name)

    @staticmethod
    def load(context: Context, account_address: PublicKey):
        account_info = AccountInfo.load(context, account_address)
        if account_info is None:
            raise Exception(f"Aggregator account not found at address '{account_address}'")
        return Aggregator.parse(context, account_info)

    def __str__(self) -> str:
        return f"""
« Aggregator '{self.name}' [{self.version}]:
    Config: {self.config}
    Initialized: {self.initialized}
    Owner: {self.owner}
    Round: {self.round}
    Round Submissions: {self.round_submissions}
    Answer: {self.answer}
    Answer Submissions: {self.answer_submissions}
»
"""

class Token:
    def __init__(self, name: str, mint: PublicKey, decimals: Decimal):
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self.name: str = name.upper()
        self.mint: PublicKey = mint
        self.decimals: Decimal = decimals

    def round(self, value: Decimal) -> Decimal:
        rounded = round(value, int(self.decimals))
        return Decimal(rounded)

    def name_matches(self, name: str) -> bool:
        return self.name.upper() == name.upper()

    @staticmethod
    def find_by_name(values: typing.List["Token"], name: str) -> "Token":
        found = [value for value in values if value.name_matches(name)]
        if len(found) == 0:
            raise Exception(f"Token '{name}' not found in token values: {values}")

        if len(found) > 1:
            raise Exception(f"Token '{name}' matched multiple tokens in values: {values}")

        return found[0]

    @staticmethod
    def find_by_mint(values: typing.List["Token"], mint: PublicKey) -> "Token":
        found = [value for value in values if value.mint == mint]
        if len(found) == 0:
            raise Exception(f"Token '{mint}' not found in token values: {values}")

        if len(found) > 1:
            raise Exception(f"Token '{mint}' matched multiple tokens in values: {values}")

        return found[0]

    # TokenMetadatas are equal if they have the same mint address.
    def __eq__(self, other):
        if hasattr(other, 'mint'):
            return self.mint == other.mint
        return False

    def __str__(self) -> str:
        return f"« Token '{self.name}' [{self.mint} ({self.decimals} decimals)] »"

    def __repr__(self) -> str:
        return f"{self}"

SolToken = Token("SOL", SYSTEM_PROGRAM_ADDRESS, SOL_DECIMALS)

class TokenLookup:
    @staticmethod
    def find_by_name(context: Context, name: str) -> Token:
        if SolToken.name_matches(name):
            return SolToken
        mint = context.lookup_token_address(name)
        if mint is None:
            raise Exception(f"Could not find token with name '{name}'.")
        return Token(name, mint, Decimal(6))

    @staticmethod
    def find_by_mint(context: Context, mint: PublicKey) -> Token:
        if SolToken.mint == mint:
            return SolToken
        name = context.lookup_token_name(mint)
        if name is None:
            raise Exception(f"Could not find token with mint '{mint}'.")
        return Token(name, mint, Decimal(6))

class BasketToken:
    def __init__(self, token: Token, vault: PublicKey, index: Index):
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self.token: Token = token
        self.vault: PublicKey = vault
        self.index: Index = index

    @staticmethod
    def find_by_name(values: typing.List["BasketToken"], name: str) -> "BasketToken":
        found = [value for value in values if value.token.name_matches(name)]
        if len(found) == 0:
            raise Exception(f"Token '{name}' not found in token values: {values}")

        if len(found) > 1:
            raise Exception(f"Token '{name}' matched multiple tokens in values: {values}")

        return found[0]

    @staticmethod
    def find_by_mint(values: typing.List["BasketToken"], mint: PublicKey) -> "BasketToken":
        found = [value for value in values if value.token.mint == mint]
        if len(found) == 0:
            raise Exception(f"Token '{mint}' not found in token values: {values}")

        if len(found) > 1:
            raise Exception(f"Token '{mint}' matched multiple tokens in values: {values}")

        return found[0]

    @staticmethod
    def find_by_token(values: typing.List["BasketToken"], token: Token) -> "BasketToken":
        return BasketToken.find_by_mint(values, token.mint)

    # BasketTokens are equal if they have the same underlying token.
    def __eq__(self, other):
        if hasattr(other, 'token'):
            return self.token == other.token
        return False

    def __str__(self) -> str:
        return f"""« BasketToken [{self.token}]:
    Vault: {self.vault}
    Index: {self.index}
»"""

    def __repr__(self) -> str:
        return f"{self}"

class TokenValue:
    def __init__(self, token: Token, value: Decimal):
        self.token = token
        self.value = value

    @staticmethod
    def fetch_total_value_or_none(context: Context, account_public_key: PublicKey, token: Token) -> typing.Optional["TokenValue"]:
        opts = TokenAccountOpts(mint=token.mint)

        token_accounts_response = context.client.get_token_accounts_by_owner(account_public_key, opts, commitment=context.commitment)
        token_accounts = token_accounts_response["result"]["value"]
        if len(token_accounts) == 0:
            return None

        total_value = Decimal(0)
        for token_account in token_accounts:
            result = context.client.get_token_account_balance(token_account["pubkey"], commitment=context.commitment)
            value = Decimal(result["result"]["value"]["amount"])
            decimal_places = result["result"]["value"]["decimals"]
            divisor = Decimal(10 ** decimal_places)
            total_value += value / divisor

        return TokenValue(token, total_value)

    @staticmethod
    def fetch_total_value(context: Context, account_public_key: PublicKey, token: Token) -> "TokenValue":
        value = TokenValue.fetch_total_value_or_none(context, account_public_key, token)
        if value is None:
            return TokenValue(token, Decimal(0))
        return value

    @staticmethod
    def report(reporter: typing.Callable[[str], None], values: typing.List["TokenValue"]) -> None:
        for value in values:
            reporter(f"{value.value:>18,.8f} {value.token.name}")

    @staticmethod
    def find_by_name(values: typing.List["TokenValue"], name: str) -> "TokenValue":
        found = [value for value in values if value.token.name_matches(name)]
        if len(found) == 0:
            raise Exception(f"Token '{name}' not found in token values: {values}")

        if len(found) > 1:
            raise Exception(f"Token '{name}' matched multiple tokens in values: {values}")

        return found[0]

    @staticmethod
    def find_by_mint(values: typing.List["TokenValue"], mint: PublicKey) -> "TokenValue":
        found = [value for value in values if value.token.mint == mint]
        if len(found) == 0:
            raise Exception(f"Token '{mint}' not found in token values: {values}")

        if len(found) > 1:
            raise Exception(f"Token '{mint}' matched multiple tokens in values: {values}")

        return found[0]

    @staticmethod
    def find_by_token(values: typing.List["TokenValue"], token: Token) -> "TokenValue":
        return TokenValue.find_by_mint(values, token.mint)

    @staticmethod
    def changes(before: typing.List["TokenValue"], after: typing.List["TokenValue"]) -> typing.List["TokenValue"]:
        changes: typing.List[TokenValue] = []
        for before_balance in before:
            after_balance = TokenValue.find_by_token(after, before_balance.token)
            result = TokenValue(before_balance.token, after_balance.value - before_balance.value)
            changes += [result]

        return changes

    def __str__(self) -> str:
        return f"« TokenValue: {self.value:>18,.8f} {self.token.name} »"

    def __repr__(self) -> str:
        return f"{self}"

class OwnedTokenValue:
    def __init__(self, owner: PublicKey, token_value: TokenValue):
        self.owner = owner
        self.token_value = token_value

    @staticmethod
    def find_by_owner(values: typing.List["OwnedTokenValue"], owner: PublicKey) -> "OwnedTokenValue":
        found = [value for value in values if value.owner == owner]
        if len(found) == 0:
            raise Exception(f"Owner '{owner}' not found in: {values}")

        if len(found) > 1:
            raise Exception(f"Owner '{owner}' matched multiple tokens in: {values}")

        return found[0]

    @staticmethod
    def changes(before: typing.List["OwnedTokenValue"], after: typing.List["OwnedTokenValue"]) -> typing.List["OwnedTokenValue"]:
        changes: typing.List[OwnedTokenValue] = []
        for before_value in before:
            after_value = OwnedTokenValue.find_by_owner(after, before_value.owner)
            token_value = TokenValue(before_value.token_value.token, after_value.token_value.value - before_value.token_value.value)
            result = OwnedTokenValue(before_value.owner, token_value)
            changes += [result]

        return changes

    def __str__(self) -> str:
        return f"[{self.owner}]: {self.token_value}"

    def __repr__(self) -> str:
        return f"{self}"

class MarketMetadata:
    def __init__(self, name: str, address: PublicKey, base: BasketToken, quote: BasketToken,
                 spot: PublicKey, oracle: PublicKey, decimals: Decimal):
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self.name: str = name
        self.address: PublicKey = address
        self.base: BasketToken = base
        self.quote: BasketToken = quote
        self.spot: PublicKey = spot
        self.oracle: PublicKey = oracle
        self.decimals: Decimal = decimals
        self._market = None

    def fetch_market(self, context: Context) -> Market:
        if self._market is None:
            self._market = Market.load(context.client, self.spot)

        return self._market

    def __str__(self) -> str:
        return f"""« Market '{self.name}' [{self.spot}]:
    Base: {self.base}
    Quote: {self.quote}
    Oracle: {self.oracle} ({self.decimals} decimals)
»"""

    def __repr__(self) -> str:
        return f"{self}"

class Group(AddressableAccount):
    def __init__(self, account_info: AccountInfo, version: Version, context: Context,
                 account_flags: MangoAccountFlags, basket_tokens: typing.List[BasketToken],
                 markets: typing.List[MarketMetadata],
                 signer_nonce: Decimal, signer_key: PublicKey, dex_program_id: PublicKey,
                 total_deposits: typing.List[Decimal], total_borrows: typing.List[Decimal],
                 maint_coll_ratio: Decimal, init_coll_ratio: Decimal, srm_vault: PublicKey,
                 admin: PublicKey, borrow_limits: typing.List[Decimal]):
        super().__init__(account_info)
        self.version: Version = version
        self.context: Context = context
        self.account_flags: MangoAccountFlags = account_flags
        self.basket_tokens: typing.List[BasketToken] = basket_tokens
        self.markets: typing.List[MarketMetadata] = markets
        self.signer_nonce: Decimal = signer_nonce
        self.signer_key: PublicKey = signer_key
        self.dex_program_id: PublicKey = dex_program_id
        self.total_deposits: typing.List[Decimal] = total_deposits
        self.total_borrows: typing.List[Decimal] = total_borrows
        self.maint_coll_ratio: Decimal = maint_coll_ratio
        self.init_coll_ratio: Decimal = init_coll_ratio
        self.srm_vault: PublicKey = srm_vault
        self.admin: PublicKey = admin
        self.borrow_limits: typing.List[Decimal] = borrow_limits

    @property
    def shared_quote_token(self) -> BasketToken:
        return self.basket_tokens[-1]

    @staticmethod
    def from_layout(layout: layouts.GROUP, context: Context, account_info: AccountInfo) -> "Group":
        account_flags = MangoAccountFlags.from_layout(layout.account_flags)
        indexes = list(map(lambda pair: Index.from_layout(pair[0], pair[1]), zip(layout.indexes, layout.mint_decimals)))

        basket_tokens: typing.List[BasketToken] = []
        for index in range(NUM_TOKENS):
            token_address = layout.tokens[index]
            token_name = context.lookup_token_name(token_address)
            if token_name is None:
                raise Exception(f"Could not find token with mint '{token_address}' in Group.")
            token = Token(token_name, token_address, layout.mint_decimals[index])
            basket_token = BasketToken(token, layout.vaults[index], indexes[index])
            basket_tokens += [basket_token]

        markets: typing.List[MarketMetadata] = []
        for index in range(NUM_MARKETS):
            market_address = layout.spot_markets[index]
            market_name = context.lookup_market_name(market_address)
            base_name, quote_name = market_name.split("/")
            base_token = BasketToken.find_by_name(basket_tokens, base_name)
            quote_token = BasketToken.find_by_name(basket_tokens, quote_name)
            market = MarketMetadata(market_name, market_address, base_token, quote_token,
                                    layout.spot_markets[index],
                                    layout.oracles[index],
                                    layout.oracle_decimals[index])
            markets += [market]

        maint_coll_ratio = layout.maint_coll_ratio.quantize(Decimal('.01'))
        init_coll_ratio = layout.init_coll_ratio.quantize(Decimal('.01'))
        return Group(account_info, Version.UNSPECIFIED, context, account_flags, basket_tokens, markets,
                     layout.signer_nonce, layout.signer_key, layout.dex_program_id, layout.total_deposits,
                     layout.total_borrows, maint_coll_ratio, init_coll_ratio, layout.srm_vault,
                     layout.admin, layout.borrow_limits)

    @staticmethod
    def parse(context: Context, account_info: AccountInfo) -> "Group":
        data = account_info.data
        if len(data) != layouts.GROUP.sizeof():
            raise Exception(f"Data length ({len(data)}) does not match expected size ({layouts.GROUP.sizeof()})")

        layout = layouts.GROUP.parse(data)
        return Group.from_layout(layout, context, account_info)

    @staticmethod
    def load(context: Context):
        account_info = AccountInfo.load(context, context.group_id)
        if account_info is None:
            raise Exception(f"Group account not found at address '{context.group_id}'")
        return Group.parse(context, account_info)
    
    #TODO Test this method, implement get_ui_total_borrow,get_ui_total_deposit
    def get_deposit_rate(self,token_index: int):
        borrow_rate = self.get_borrow_rate(token_index)
        total_borrows = self.get_ui_total_borrow(token_index)
        total_deposits = self.get_ui_total_deposit(token_index)
        
        if total_deposits == 0 and total_borrows == 0: return 0
        elif total_deposits == 0: return MAX_RATE
        utilization = total_borrows / total_deposits
        return utilization * borrow_rate
    
    #TODO Test this method, implement get_ui_total_borrow, get_ui_total_deposit
    def get_borrow_rate(self,token_index: int):
        total_borrows = self.get_ui_total_borrow(token_index)
        total_deposits = self.get_ui_total_deposit(token_index)
        
        if total_deposits == 0 and total_borrows == 0: return 0
        if total_deposits <= total_borrows : return MAX_RATE
        utilization = total_borrows / total_deposits
        if utilization > OPTIMAL_UTIL:
            extra_util = utilization - OPTIMAL_UTIL
            slope = (MAX_RATE - OPTIMAL_RATE) / (1 - OPTIMAL_UTIL)
            return OPTIMAL_RATE + slope * extra_util
        else:
            slope = OPTIMAL_RATE / OPTIMAL_UTIL
            return slope * utilization

    def get_token_index(self, token: Token) -> int:
        for index, existing in enumerate(self.basket_tokens):
            if existing.token == token:
                return index
        return -1

    def get_prices(self) -> typing.List[TokenValue]:
        started_at = time.time()

        # Note: we can just load the oracle data in a simpler way, with:
        #   oracles = map(lambda market: Aggregator.load(self.context, market.oracle), self.markets)
        # but that makes a network request for every oracle. We can reduce that to just one request
        # if we use AccountInfo.load_multiple() and parse the data ourselves.
        #
        # This seems to halve the time this function takes.
        oracle_addresses = list([market.oracle for market in self.markets])
        oracle_account_infos = AccountInfo.load_multiple(self.context, oracle_addresses)
        oracles = map(lambda oracle_account_info: Aggregator.parse(self.context, oracle_account_info),
                      oracle_account_infos)
        prices = list(map(lambda oracle: oracle.price, oracles)) + [Decimal(1)]
        token_prices = []
        for index, price in enumerate(prices):
            token_prices += [TokenValue(self.basket_tokens[index].token, price)]

        time_taken = time.time() - started_at
        self.logger.info(f"Faster fetching prices complete. Time taken: {time_taken:.2f} seconds.")
        return token_prices

    def fetch_balances(self, root_address: PublicKey) -> typing.List[TokenValue]:
        balances: typing.List[TokenValue] = []
        sol_balance = self.context.fetch_sol_balance(root_address)
        balances += [TokenValue(SolToken, sol_balance)]

        for basket_token in self.basket_tokens:
            balance = TokenValue.fetch_total_value(self.context, root_address, basket_token.token)
            balances += [balance]
        return balances

    def __str__(self) -> str:
        total_deposits = "\n        ".join(map(str, self.total_deposits))
        total_borrows = "\n        ".join(map(str, self.total_borrows))
        borrow_limits = "\n        ".join(map(str, self.borrow_limits))
        return f"""


« Group [{self.version}] {self.address}:
    Flags: {self.account_flags}
    Tokens:
{self.basket_tokens}
    Markets:
{self.markets}
    DEX Program ID: « {self.dex_program_id} »
    SRM Vault: « {self.srm_vault} »
    Admin: « {self.admin} »
    Signer Nonce: {self.signer_nonce}
    Signer Key: « {self.signer_key} »
    Initial Collateral Ratio: {self.init_coll_ratio}
    Maintenance Collateral Ratio: {self.maint_coll_ratio}
    Total Deposits:
        {total_deposits}
    Total Borrows:
        {total_borrows}
    Borrow Limits:
        {borrow_limits}
»
"""

class TokenAccount(AddressableAccount):
    def __init__(self, account_info: AccountInfo, version: Version, mint: PublicKey, owner: PublicKey, amount: Decimal):
        super().__init__(account_info)
        self.version: Version = version
        self.mint: PublicKey = mint
        self.owner: PublicKey = owner
        self.amount: Decimal = amount

    @staticmethod
    def create(context: Context, account: Account, token: Token):
        spl_token = SplToken(context.client, token.mint, TOKEN_PROGRAM_ID, account)
        owner = account.public_key()
        new_account_address = spl_token.create_account(owner)
        return TokenAccount.load(context, new_account_address)

    @staticmethod
    def fetch_all_for_owner_and_token(context: Context, owner_public_key: PublicKey, token: Token) -> typing.List["TokenAccount"]:
        opts = TokenAccountOpts(mint=token.mint)

        token_accounts_response = context.client.get_token_accounts_by_owner(owner_public_key, opts, commitment=context.commitment)

        all_accounts: typing.List[TokenAccount] = []
        for token_account_response in token_accounts_response["result"]["value"]:
            account_info = AccountInfo._from_response_values(token_account_response["account"], PublicKey(token_account_response["pubkey"]))
            token_account = TokenAccount.parse(account_info)
            all_accounts += [token_account]

        return all_accounts

    @staticmethod
    def fetch_largest_for_owner_and_token(context: Context, owner_public_key: PublicKey, token: Token) -> typing.Optional["TokenAccount"]:
        all_accounts = TokenAccount.fetch_all_for_owner_and_token(context, owner_public_key, token)

        largest_account: typing.Optional[TokenAccount] = None
        for token_account in all_accounts:
            if largest_account is None or token_account.amount > largest_account.amount:
                largest_account = token_account

        return largest_account

    @staticmethod
    def fetch_or_create_largest_for_owner_and_token(context: Context, account: Account, token: Token) -> "TokenAccount":
        all_accounts = TokenAccount.fetch_all_for_owner_and_token(context, account.public_key(), token)

        largest_account: typing.Optional[TokenAccount] = None
        for token_account in all_accounts:
            if largest_account is None or token_account.amount > largest_account.amount:
                largest_account = token_account

        if largest_account is None:
            return TokenAccount.create(context, account, token)

        return largest_account

    @staticmethod
    def from_layout(layout: layouts.TOKEN_ACCOUNT, account_info: AccountInfo) -> "TokenAccount":
        return TokenAccount(account_info, Version.UNSPECIFIED, layout.mint, layout.owner, layout.amount)

    @staticmethod
    def parse(account_info: AccountInfo) -> "TokenAccount":
        data = account_info.data
        if len(data) != layouts.TOKEN_ACCOUNT.sizeof():
            raise Exception(f"Data length ({len(data)}) does not match expected size ({layouts.TOKEN_ACCOUNT.sizeof()})")

        layout = layouts.TOKEN_ACCOUNT.parse(data)
        return TokenAccount.from_layout(layout, account_info)

    @staticmethod
    def load(context: Context, address: PublicKey) -> typing.Optional["TokenAccount"]:
        account_info = AccountInfo.load(context, address)
        if account_info is None or (len(account_info.data) != layouts.TOKEN_ACCOUNT.sizeof()):
            return None
        return TokenAccount.parse(account_info)

    def __str__(self) -> str:
        return f"« Token: Mint: {self.mint}, Owner: {self.owner}, Amount: {self.amount} »"

class OpenOrders(AddressableAccount):
    def __init__(self, account_info: AccountInfo, version: Version, program_id: PublicKey,
                 account_flags: SerumAccountFlags, market: PublicKey, owner: PublicKey,
                 base_token_free: Decimal, base_token_total: Decimal, quote_token_free: Decimal,
                 quote_token_total: Decimal, free_slot_bits: Decimal, is_bid_bits: Decimal,
                 orders: typing.List[Decimal], client_ids: typing.List[Decimal],
                 referrer_rebate_accrued: Decimal):
        super().__init__(account_info)
        self.version: Version = version
        self.program_id: PublicKey = program_id
        self.account_flags: SerumAccountFlags = account_flags
        self.market: PublicKey = market
        self.owner: PublicKey = owner
        self.base_token_free: Decimal = base_token_free
        self.base_token_total: Decimal = base_token_total
        self.quote_token_free: Decimal = quote_token_free
        self.quote_token_total: Decimal = quote_token_total
        self.free_slot_bits: Decimal = free_slot_bits
        self.is_bid_bits: Decimal = is_bid_bits
        self.orders: typing.List[Decimal] = orders
        self.client_ids: typing.List[Decimal] = client_ids
        self.referrer_rebate_accrued: Decimal = referrer_rebate_accrued

    # Sometimes pyserum wants to take its own OpenOrdersAccount as a parameter (e.g. in settle_funds())
    def to_pyserum(self) -> OpenOrdersAccount:
        return OpenOrdersAccount.from_bytes(self.address, self.account_info.data)

    @staticmethod
    def from_layout(layout: layouts.OPEN_ORDERS, account_info: AccountInfo,
                    base_decimals: Decimal, quote_decimals: Decimal) -> "OpenOrders":
        account_flags = SerumAccountFlags.from_layout(layout.account_flags)
        program_id = account_info.owner

        base_divisor = 10 ** base_decimals
        quote_divisor = 10 ** quote_decimals
        base_token_free: Decimal = layout.base_token_free / base_divisor
        base_token_total: Decimal = layout.base_token_total / base_divisor
        quote_token_free: Decimal = layout.quote_token_free / quote_divisor
        quote_token_total: Decimal = layout.quote_token_total / quote_divisor
        nonzero_orders: typing.List[Decimal] = list([order for order in layout.orders if order != 0])
        nonzero_client_ids: typing.List[Decimal] = list([client_id for client_id in layout.client_ids if client_id != 0])

        return OpenOrders(account_info, Version.UNSPECIFIED, program_id, account_flags, layout.market,
                          layout.owner, base_token_free, base_token_total, quote_token_free, quote_token_total,
                          layout.free_slot_bits, layout.is_bid_bits, nonzero_orders, nonzero_client_ids,
                          layout.referrer_rebate_accrued)

    @staticmethod
    def parse(account_info: AccountInfo, base_decimals: Decimal, quote_decimals: Decimal) -> "OpenOrders":
        data = account_info.data
        if len(data) != layouts.OPEN_ORDERS.sizeof():
            raise Exception(f"Data length ({len(data)}) does not match expected size ({layouts.OPEN_ORDERS.sizeof()})")

        layout = layouts.OPEN_ORDERS.parse(data)
        return OpenOrders.from_layout(layout, account_info, base_decimals, quote_decimals)

    @staticmethod
    def load_raw_open_orders_account_infos(context: Context, group: Group) -> typing.Dict[str, AccountInfo]:
        filters = [
            MemcmpOpts(
                offset=layouts.SERUM_ACCOUNT_FLAGS.sizeof() + 37,
                bytes=encode_key(group.signer_key)
            )
        ]

        response = context.client.get_program_accounts(group.dex_program_id, data_size=layouts.OPEN_ORDERS.sizeof(), memcmp_opts=filters, commitment=Single, encoding="base64")
        account_infos = list(map(lambda pair: AccountInfo._from_response_values(pair[0], pair[1]), [(result["account"], PublicKey(result["pubkey"])) for result in response["result"]]))
        account_infos_by_address = {key: value for key, value in [(str(account_info.address), account_info) for account_info in account_infos]}
        return account_infos_by_address

    @staticmethod
    def load(context: Context, address: PublicKey, base_decimals: Decimal, quote_decimals: Decimal) -> "OpenOrders":
        open_orders_account = AccountInfo.load(context, address)
        if open_orders_account is None:
            raise Exception(f"OpenOrders account not found at address '{address}'")
        return OpenOrders.parse(open_orders_account, base_decimals, quote_decimals)

    @staticmethod
    def load_for_market_and_owner(context: Context, market: PublicKey, owner: PublicKey, program_id: PublicKey, base_decimals: Decimal, quote_decimals: Decimal):
        filters = [
            MemcmpOpts(
                offset=layouts.SERUM_ACCOUNT_FLAGS.sizeof() + 5,
                bytes=encode_key(market)
            ),
            MemcmpOpts(
                offset=layouts.SERUM_ACCOUNT_FLAGS.sizeof() + 37,
                bytes=encode_key(owner)
            )
        ]

        response = context.client.get_program_accounts(context.dex_program_id, data_size=layouts.OPEN_ORDERS.sizeof(), memcmp_opts=filters, commitment=Single, encoding="base64")
        accounts = list(map(lambda pair: AccountInfo._from_response_values(pair[0], pair[1]), [(result["account"], PublicKey(result["pubkey"])) for result in response["result"]]))
        return list(map(lambda acc: OpenOrders.parse(acc, base_decimals, quote_decimals), accounts))

    def __str__(self) -> str:
        orders = ", ".join(map(str, self.orders)) or "None"
        client_ids = ", ".join(map(str, self.client_ids)) or "None"

        return f"""« OpenOrders:
    Flags: {self.account_flags}
    Program ID: {self.program_id}
    Address: {self.address}
    Market: {self.market}
    Owner: {self.owner}
    Base Token: {self.base_token_free:,.8f} of {self.base_token_total:,.8f}
    Quote Token: {self.quote_token_free:,.8f} of {self.quote_token_total:,.8f}
    Referrer Rebate Accrued: {self.referrer_rebate_accrued}
    Orders:
        {orders}
    Client IDs:
        {client_ids}
»"""

class BalanceSheet:
    def __init__(self, token: Token, liabilities: Decimal, settled_assets: Decimal, unsettled_assets: Decimal):
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self.token: Token = token
        self.liabilities: Decimal = liabilities
        self.settled_assets: Decimal = settled_assets
        self.unsettled_assets: Decimal = unsettled_assets

    @property
    def assets(self) -> Decimal:
        return self.settled_assets + self.unsettled_assets

    @property
    def value(self) -> Decimal:
        return self.assets - self.liabilities

    @property
    def collateral_ratio(self) -> Decimal:
        if self.liabilities == Decimal(0):
            return Decimal(0)
        return self.assets / self.liabilities

    def __str__(self) -> str:
        name = "«Unspecified»"
        if self.token is not None:
            name = self.token.name

        return f"""« BalanceSheet [{name}]:
    Assets :           {self.assets:>18,.8f}
    Settled Assets :   {self.settled_assets:>18,.8f}
    Unsettled Assets : {self.unsettled_assets:>18,.8f}
    Liabilities :      {self.liabilities:>18,.8f}
    Value :            {self.value:>18,.8f}
    Collateral Ratio : {self.collateral_ratio:>18,.2%}
»
"""

    def __repr__(self) -> str:
        return f"{self}"

class MarginAccount(AddressableAccount):
    def __init__(self, account_info: AccountInfo, version: Version, account_flags: MangoAccountFlags,
                 mango_group: PublicKey, owner: PublicKey, deposits: typing.List[Decimal],
                 borrows: typing.List[Decimal], open_orders: typing.List[PublicKey]):
        super().__init__(account_info)
        self.version: Version = version
        self.account_flags: MangoAccountFlags = account_flags
        self.mango_group: PublicKey = mango_group
        self.owner: PublicKey = owner
        self.deposits: typing.List[Decimal] = deposits
        self.borrows: typing.List[Decimal] = borrows
        self.open_orders: typing.List[PublicKey] = open_orders
        self.open_orders_accounts: typing.List[typing.Optional[OpenOrders]] = [None] * NUM_MARKETS

    @staticmethod
    def from_layout(layout: layouts.MARGIN_ACCOUNT, account_info: AccountInfo) -> "MarginAccount":
        account_flags: MangoAccountFlags = MangoAccountFlags.from_layout(layout.account_flags)
        deposits: typing.List[Decimal] = []
        for index, deposit in enumerate(layout.deposits):
            deposits += [deposit]

        borrows: typing.List[Decimal] = []
        for index, borrow in enumerate(layout.borrows):
            borrows += [borrow]

        return MarginAccount(account_info, Version.UNSPECIFIED, account_flags, layout.mango_group,
                             layout.owner, deposits, borrows, list(layout.open_orders))

    @staticmethod
    def parse(account_info: AccountInfo) -> "MarginAccount":
        data = account_info.data
        if len(data) != layouts.MARGIN_ACCOUNT.sizeof():
            raise Exception(f"Data length ({len(data)}) does not match expected size ({layouts.MARGIN_ACCOUNT.sizeof()})")

        layout = layouts.MARGIN_ACCOUNT.parse(data)
        return MarginAccount.from_layout(layout, account_info)

    @staticmethod
    def load(context: Context, margin_account_address: PublicKey, group: typing.Optional[Group] = None) -> "MarginAccount":
        account_info = AccountInfo.load(context, margin_account_address)
        if account_info is None:
            raise Exception(f"MarginAccount account not found at address '{margin_account_address}'")
        margin_account = MarginAccount.parse(account_info)
        if group is None:
            group = Group.load(context)
        margin_account.load_open_orders_accounts(context, group)
        return margin_account

    @staticmethod
    def load_all_for_group(context: Context, program_id: PublicKey, group: Group) -> typing.List["MarginAccount"]:
        filters = [
            MemcmpOpts(
                offset=layouts.MANGO_ACCOUNT_FLAGS.sizeof(),  # mango_group is just after the MangoAccountFlags, which is the first entry
                bytes=encode_key(group.address)
            )
        ]
        response = context.client.get_program_accounts(program_id, data_size=layouts.MARGIN_ACCOUNT.sizeof(), memcmp_opts=filters, commitment=Single, encoding="base64")
        margin_accounts = []
        for margin_account_data in response["result"]:
            address = PublicKey(margin_account_data["pubkey"])
            account = AccountInfo._from_response_values(margin_account_data["account"], address)
            margin_account = MarginAccount.parse(account)
            margin_accounts += [margin_account]
        return margin_accounts

    @staticmethod
    def load_all_for_group_with_open_orders(context: Context, program_id: PublicKey, group: Group) -> typing.List["MarginAccount"]:
        margin_accounts = MarginAccount.load_all_for_group(context, context.program_id, group)
        open_orders = OpenOrders.load_raw_open_orders_account_infos(context, group)
        for margin_account in margin_accounts:
            margin_account.install_open_orders_accounts(group, open_orders)

        return margin_accounts

    @staticmethod
    def load_all_for_owner(context: Context, owner: PublicKey, group: typing.Optional[Group] = None) -> typing.List["MarginAccount"]:
        if group is None:
            group = Group.load(context)

        mango_group_offset = layouts.MANGO_ACCOUNT_FLAGS.sizeof()  # mango_group is just after the MangoAccountFlags, which is the first entry.
        owner_offset = mango_group_offset + 32  # owner is just after mango_group in the layout, and it's a PublicKey which is 32 bytes.
        filters = [
            MemcmpOpts(
                offset=mango_group_offset,
                bytes=encode_key(group.address)
            ),
            MemcmpOpts(
                offset=owner_offset,
                bytes=encode_key(owner)
            )
        ]

        response = context.client.get_program_accounts(context.program_id, data_size=layouts.MARGIN_ACCOUNT.sizeof(), memcmp_opts=filters, commitment=Single, encoding="base64")
        margin_accounts = []
        for margin_account_data in response["result"]:
            address = PublicKey(margin_account_data["pubkey"])
            account = AccountInfo._from_response_values(margin_account_data["account"], address)
            margin_account = MarginAccount.parse(account)
            margin_account.load_open_orders_accounts(context, group)
            margin_accounts += [margin_account]
        return margin_accounts

    @classmethod
    def load_all_ripe(cls, context: Context) -> typing.List["MarginAccount"]:
        logger: logging.Logger = logging.getLogger(cls.__name__)

        started_at = time.time()

        group = Group.load(context)
        margin_accounts = MarginAccount.load_all_for_group_with_open_orders(context, context.program_id, group)
        logger.info(f"Fetched {len(margin_accounts)} margin accounts to process.")

        prices = group.get_prices()
        nonzero: typing.List[MarginAccountMetadata] = []
        for margin_account in margin_accounts:
            balance_sheet = margin_account.get_balance_sheet_totals(group, prices)
            if balance_sheet.collateral_ratio > 0:
                balances = margin_account.get_intrinsic_balances(group)
                nonzero += [MarginAccountMetadata(margin_account, balance_sheet, balances)]
        logger.info(f"Of those {len(margin_accounts)}, {len(nonzero)} have a nonzero collateral ratio.")

        ripe_metadata = filter(lambda mam: mam.balance_sheet.collateral_ratio <= group.init_coll_ratio, nonzero)
        ripe_accounts = list(map(lambda mam: mam.margin_account, ripe_metadata))
        logger.info(f"Of those {len(nonzero)}, {len(ripe_accounts)} are ripe 🥭.")

        time_taken = time.time() - started_at
        logger.info(f"Loading ripe 🥭 accounts complete. Time taken: {time_taken:.2f} seconds.")
        return ripe_accounts

    def load_open_orders_accounts(self, context: Context, group: Group) -> None:
        for index, oo in enumerate(self.open_orders):
            key = oo
            if key != SYSTEM_PROGRAM_ADDRESS:
                self.open_orders_accounts[index] = OpenOrders.load(context, key, group.basket_tokens[index].token.decimals, group.shared_quote_token.token.decimals)

    def install_open_orders_accounts(self, group: Group, all_open_orders_by_address: typing.Dict[str, AccountInfo]) -> None:
        for index, oo in enumerate(self.open_orders):
            key = str(oo)
            if key in all_open_orders_by_address:
                open_orders_account_info = all_open_orders_by_address[key]
                open_orders = OpenOrders.parse(open_orders_account_info,
                                               group.basket_tokens[index].token.decimals,
                                               group.shared_quote_token.token.decimals)
                self.open_orders_accounts[index] = open_orders

    def get_intrinsic_balance_sheets(self, group: Group) -> typing.List[BalanceSheet]:
        settled_assets: typing.List[Decimal] = [Decimal(0)] * NUM_TOKENS
        liabilities: typing.List[Decimal] = [Decimal(0)] * NUM_TOKENS
        for index in range(NUM_TOKENS):
            settled_assets[index] = group.basket_tokens[index].index.deposit * self.deposits[index]
            liabilities[index] = group.basket_tokens[index].index.borrow * self.borrows[index]

        unsettled_assets: typing.List[Decimal] = [Decimal(0)] * NUM_TOKENS
        for index in range(NUM_MARKETS):
            open_orders_account = self.open_orders_accounts[index]
            if open_orders_account is not None:
                unsettled_assets[index] += open_orders_account.base_token_total
                unsettled_assets[NUM_TOKENS - 1] += open_orders_account.quote_token_total

        balance_sheets: typing.List[BalanceSheet] = []
        for index in range(NUM_TOKENS):
            balance_sheets += [BalanceSheet(group.basket_tokens[index].token, liabilities[index],
                                            settled_assets[index], unsettled_assets[index])]

        return balance_sheets

    def get_priced_balance_sheets(self, group: Group, prices: typing.List[TokenValue]) -> typing.List[BalanceSheet]:
        priced: typing.List[BalanceSheet] = []
        balance_sheets = self.get_intrinsic_balance_sheets(group)
        for balance_sheet in balance_sheets:
            price = TokenValue.find_by_token(prices, balance_sheet.token)
            liabilities = balance_sheet.liabilities * price.value
            settled_assets = balance_sheet.settled_assets * price.value
            unsettled_assets = balance_sheet.unsettled_assets * price.value
            priced += [BalanceSheet(
                price.token,
                price.token.round(liabilities),
                price.token.round(settled_assets),
                price.token.round(unsettled_assets)
            )]

        return priced

    def get_balance_sheet_totals(self, group: Group, prices: typing.List[TokenValue]) -> BalanceSheet:
        liabilities = Decimal(0)
        settled_assets = Decimal(0)
        unsettled_assets = Decimal(0)

        balance_sheets = self.get_priced_balance_sheets(group, prices)
        for balance_sheet in balance_sheets:
            if balance_sheet is not None:
                liabilities += balance_sheet.liabilities
                settled_assets += balance_sheet.settled_assets
                unsettled_assets += balance_sheet.unsettled_assets

        # A BalanceSheet must have a token - it's a pain to make it a typing.Optional[Token].
        # So in this one case, we produce a 'fake' token whose symbol is a summary of all token
        # symbols that went into it.
        #
        # If this becomes more painful than typing.Optional[Token], we can go with making
        # Token optional.
        summary_name = "-".join([bal.token.name for bal in balance_sheets])
        summary_token = Token(summary_name, SYSTEM_PROGRAM_ADDRESS, Decimal(0))
        return BalanceSheet(summary_token, liabilities, settled_assets, unsettled_assets)

    def get_intrinsic_balances(self, group: Group) -> typing.List[TokenValue]:
        balance_sheets = self.get_intrinsic_balance_sheets(group)
        balances: typing.List[TokenValue] = []
        for index, balance_sheet in enumerate(balance_sheets):
            if balance_sheet.token is None:
                raise Exception(f"Intrinsic balance sheet with index [{index}] has no token.")
            balances += [TokenValue(balance_sheet.token, balance_sheet.value)]

        return balances

    def __str__(self) -> str:
        deposits = ", ".join([f"{item:,.8f}" for item in self.deposits])
        borrows = ", ".join([f"{item:,.8f}" for item in self.borrows])
        if all(oo is None for oo in self.open_orders_accounts):
            open_orders = f"{self.open_orders}"
        else:
            open_orders_unindented = f"{self.open_orders_accounts}"
            open_orders = open_orders_unindented.replace("\n", "\n    ")
        return f"""« MarginAccount: {self.address}
    Flags: {self.account_flags}
    Owner: {self.owner}
    Mango Group: {self.mango_group}
    Deposits: [{deposits}]
    Borrows: [{borrows}]
    Mango Open Orders: {open_orders}
»"""

class MarginAccountMetadata:
    def __init__(self, margin_account: MarginAccount, balance_sheet: BalanceSheet, balances: typing.List[TokenValue]):
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self.margin_account = margin_account
        self.balance_sheet = balance_sheet
        self.balances = balances

    @property
    def assets(self):
        return self.balance_sheet.assets

    @property
    def liabilities(self):
        return self.balance_sheet.liabilities

    @property
    def collateral_ratio(self):
        return self.balance_sheet.collateral_ratio

class LiquidationEvent:
    def __init__(self, timestamp: datetime.datetime, signature: str, wallet_address: PublicKey, margin_account_address: PublicKey, balances_before: typing.List[TokenValue], balances_after: typing.List[TokenValue]):
        self.timestamp = timestamp
        self.signature = signature
        self.wallet_address = wallet_address
        self.margin_account_address = margin_account_address
        self.balances_before = balances_before
        self.balances_after = balances_after

    def __str__(self) -> str:
        changes = TokenValue.changes(self.balances_before, self.balances_after)
        changes_text = "\n        ".join([f"{change.value:>15,.8f} {change.token.name}" for change in changes])
        return f"""« 🥭 Liqudation Event 💧 at {self.timestamp}
            📇 Signature: {self.signature}
            👛 Wallet: {self.wallet_address}
            💳 Margin Account: {self.margin_account_address}
            💸 Changes:
                {changes_text}
            »"""

    def __repr__(self) -> str:
        return f"{self}"

def _notebook_tests():
    log_level = logging.getLogger().level
    try:
        logging.getLogger().setLevel(logging.CRITICAL)

        from Constants import SYSTEM_PROGRAM_ADDRESS
        from Context import default_context

        balances_before = [
            TokenValue(TokenLookup.find_by_name(default_context, "ETH"), Decimal(1)),
            TokenValue(TokenLookup.find_by_name(default_context, "BTC"), Decimal("0.1")),
            TokenValue(TokenLookup.find_by_name(default_context, "USDT"), Decimal(1000))
        ]
        balances_after = [
            TokenValue(TokenLookup.find_by_name(default_context, "ETH"), Decimal(1)),
            TokenValue(TokenLookup.find_by_name(default_context, "BTC"), Decimal("0.05")),
            TokenValue(TokenLookup.find_by_name(default_context, "USDT"), Decimal(2000))
        ]
        timestamp = datetime.datetime(2021, 5, 17, 12, 20, 56)
        event = LiquidationEvent(timestamp, "signature", SYSTEM_PROGRAM_ADDRESS, SYSTEM_PROGRAM_ADDRESS,
                                 balances_before, balances_after)
        assert(str(event) == """« 🥭 Liqudation Event 💧 at 2021-05-17 12:20:56
    📇 Signature: signature
    👛 Wallet: 11111111111111111111111111111111
    💳 Margin Account: 11111111111111111111111111111111
    💸 Changes:
             0.00000000 ETH
            -0.05000000 BTC
         1,000.00000000 USDT
»""")
    finally:
        logging.getLogger().setLevel(log_level)

_notebook_tests()

del _notebook_tests

if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO)

    import base64
    from Constants import SYSTEM_PROGRAM_ADDRESS
    from Context import default_context

    # Just use any public key here
    fake_public_key = SYSTEM_PROGRAM_ADDRESS
    encoded = "AwAAAAAAAACCaOmpoURMK6XHelGTaFawcuQ/78/15LAemWI8jrt3SRKLy2R9i60eclDjuDS8+p/ZhvTUd9G7uQVOYCsR6+BhmqGCiO6EPYP2PQkf/VRTvw7JjXvIjPFJy06QR1Cq1WfTonHl0OjCkyEf60SD07+MFJu5pVWNFGGEO/8AiAYfduaKdnFTaZEHPcK5Eq72WWHeHg2yIbBF09kyeOhlCJwOoG8O5SgpPV8QOA64ZNV4aKroFfADg6kEy/wWCdp3fv0O4GJgAAAAAPH6Ud6jtjwAAQAAAAAAAADiDkkCi9UOAAEAAAAAAAAADuBiYAAAAACNS5bSy7soAAEAAAAAAAAACMvgO+2jCwABAAAAAAAAAA7gYmAAAAAAZFeDUBNVhwABAAAAAAAAABtRNytozC8AAQAAAAAAAABIBGiCcyaEZdNhrTyeqUY692vOzzPdHaxAxguht3JQGlkzjtd05dX9LENHkl2z1XvUbTNKZlweypNRetmH0lmQ9VYQAHqylxZVK65gEg85g27YuSyvOBZAjJyRmYU9KdCO1D+4ehdPu9dQB1yI1uh75wShdAaFn2o4qrMYwq3SQQEAAAAAAAAAAiH1PPJKAuh6oGiE35aGhUQhFi/bxgKOudpFv8HEHNCFDy1uAqR6+CTQmradxC1wyyjL+iSft+5XudJWwSdi7wvphsxb96x7Obj/AgAAAAAKlV4LL5ow6r9LMhIAAAAADvsOtqcVFmChDPzPnwAAAE33lx1h8hPFD04AAAAAAAA8YRV3Oa309B2wGwAAAAAA+yPBZRlZz7b605n+AQAAAACgmZmZmZkZAQAAAAAAAAAAMDMzMzMzMwEAAAAAAAAA25D1XcAtRzSuuyx3U+X7aE9vM1EJySU9KprgL0LMJ/vat9+SEEUZuga7O5tTUrcMDYWDg+LYaAWhSQiN2fYk7aCGAQAAAAAAgIQeAAAAAAAA8gUqAQAAAAYGBgICAAAA"
    decoded = base64.b64decode(encoded)
    group_account_info = AccountInfo(fake_public_key, False, Decimal(0), fake_public_key, Decimal(0), decoded)

    group = Group.parse(default_context, group_account_info)
    print("\n\nThis is hard-coded, not live information!")
    print(group)

    print(TokenLookup.find_by_name(default_context, "ETH"))
    print(TokenLookup.find_by_name(default_context, "BTC"))

    # USDT
    print(TokenLookup.find_by_mint(default_context, PublicKey("Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB")))

    single_account_info = AccountInfo.load(default_context, default_context.dex_program_id)
    print("DEX account info", single_account_info)

    multiple_account_info = AccountInfo.load_multiple(default_context, [default_context.program_id, default_context.dex_program_id])
    print("Mango program and DEX account info", multiple_account_info)

    balances_before = [
        TokenValue(TokenLookup.find_by_name(default_context, "ETH"), Decimal(1)),
        TokenValue(TokenLookup.find_by_name(default_context, "BTC"), Decimal("0.1")),
        TokenValue(TokenLookup.find_by_name(default_context, "USDT"), Decimal(1000))
    ]
    balances_after = [
        TokenValue(TokenLookup.find_by_name(default_context, "ETH"), Decimal(1)),
        TokenValue(TokenLookup.find_by_name(default_context, "BTC"), Decimal("0.05")),
        TokenValue(TokenLookup.find_by_name(default_context, "USDT"), Decimal(2000))
    ]
    timestamp = datetime.datetime(2021, 5, 17, 12, 20, 56)
    event = LiquidationEvent(timestamp, "signature", SYSTEM_PROGRAM_ADDRESS, SYSTEM_PROGRAM_ADDRESS,
                             balances_before, balances_after)
    print(event)