import construct
import datetime

from decimal import Decimal
from solana.publickey import PublicKey

from Constants import NUM_MARKETS, NUM_TOKENS

class DecimalAdapter(construct.Adapter):
    def __init__(self, size: int = 8):
        construct.Adapter.__init__(self, construct.BytesInteger(size, swapped=True))

    def _decode(self, obj, context, path) -> Decimal:
        return Decimal(obj)

    def _encode(self, obj, context, path) -> int:
        # Can only encode int values.
        return int(obj)


class FloatAdapter(construct.Adapter):
    def __init__(self, size: int = 16):
        self.size = size
        construct.Adapter.__init__(self, construct.BytesInteger(size, swapped=True))

        # Our size is in bytes but we want to work with bits here.
        bit_size = self.size * 8

        # For our string of bits, our 'fixed point' is right in the middle.
        fixed_point = bit_size / 2

        # So our divisor is 2 to the power of the fixed point
        self.divisor = Decimal(2 ** fixed_point)

    def _decode(self, obj, context, path) -> Decimal:
        return Decimal(obj) / self.divisor

    def _encode(self, obj, context, path) -> bytes:
        return bytes(obj)

class PublicKeyAdapter(construct.Adapter):
    def __init__(self):
        construct.Adapter.__init__(self, construct.Bytes(32))

    def _decode(self, obj, context, path) -> PublicKey:
        return PublicKey(obj)

    def _encode(self, obj, context, path) -> bytes:
        return bytes(obj)


class DatetimeAdapter(construct.Adapter):
    def __init__(self):
        construct.Adapter.__init__(self, construct.BytesInteger(8, swapped=True))

    def _decode(self, obj, context, path) -> datetime.datetime:
        return datetime.datetime.fromtimestamp(obj)

    def _encode(self, obj, context, path) -> bytes:
        return bytes(obj)

SERUM_ACCOUNT_FLAGS = construct.BitsSwapped(
    construct.BitStruct(
        "initialized" / construct.Flag,
        "market" / construct.Flag,
        "open_orders" / construct.Flag,
        "request_queue" / construct.Flag,
        "event_queue" / construct.Flag,
        "bids" / construct.Flag,
        "asks" / construct.Flag,
        "disabled" / construct.Flag,
        construct.Padding(7 * 8)
    )
)

MANGO_ACCOUNT_FLAGS = construct.BitsSwapped(
    construct.BitStruct(
        "initialized" / construct.Flag,
        "group" / construct.Flag,
        "margin_account" / construct.Flag,
        "srm_account" / construct.Flag,
        construct.Padding(4 + (7 * 8))
    )
)

INDEX = construct.Struct(
    "last_update" / DatetimeAdapter(),
    "borrow" / FloatAdapter(),
    "deposit" / FloatAdapter()
)

AGGREGATOR_CONFIG = construct.Struct(
    "description" / construct.PaddedString(32, "utf8"),
    "decimals" / DecimalAdapter(1),
    "restart_delay" / DecimalAdapter(1),
    "max_submissions" / DecimalAdapter(1),
    "min_submissions" / DecimalAdapter(1),
    "reward_amount" / DecimalAdapter(),
    "reward_token_account" / PublicKeyAdapter()
)

ROUND = construct.Struct(
    "id" / DecimalAdapter(),
    "created_at" / DecimalAdapter(),
    "updated_at" / DecimalAdapter()
)

ANSWER = construct.Struct(
    "round_id" / DecimalAdapter(),
    "median" / DecimalAdapter(),
    "created_at" / DatetimeAdapter(),
    "updated_at" / DatetimeAdapter()
)

AGGREGATOR = construct.Struct(
    "config" / AGGREGATOR_CONFIG,
    "initialized" / DecimalAdapter(1),
    "owner" / PublicKeyAdapter(),
    "round" / ROUND,
    "round_submissions" / PublicKeyAdapter(),
    "answer" / ANSWER,
    "answer_submissions" / PublicKeyAdapter()
)

GROUP_PADDING = 8 - (NUM_TOKENS + NUM_MARKETS) % 8

GROUP = construct.Struct(
    "account_flags" / MANGO_ACCOUNT_FLAGS,
    "tokens" / construct.Array(NUM_TOKENS, PublicKeyAdapter()),
    "vaults" / construct.Array(NUM_TOKENS, PublicKeyAdapter()),
    "indexes" / construct.Array(NUM_TOKENS, INDEX),
    "spot_markets" / construct.Array(NUM_MARKETS, PublicKeyAdapter()),
    "oracles" / construct.Array(NUM_MARKETS, PublicKeyAdapter()),
    "signer_nonce" / DecimalAdapter(),
    "signer_key" / PublicKeyAdapter(),
    "dex_program_id" / PublicKeyAdapter(),
    "total_deposits" / construct.Array(NUM_TOKENS, FloatAdapter()),
    "total_borrows" / construct.Array(NUM_TOKENS, FloatAdapter()),
    "maint_coll_ratio" / FloatAdapter(),
    "init_coll_ratio" / FloatAdapter(),
    "srm_vault" / PublicKeyAdapter(),
    "admin" / PublicKeyAdapter(),
    "borrow_limits" / construct.Array(NUM_TOKENS, DecimalAdapter()),
    "mint_decimals" / construct.Array(NUM_TOKENS, DecimalAdapter(1)),
    "oracle_decimals" / construct.Array(NUM_MARKETS, DecimalAdapter(1)),
    "padding" / construct.Array(GROUP_PADDING, construct.Padding(1))
)

MARGIN_ACCOUNT = construct.Struct(
    "account_flags" / MANGO_ACCOUNT_FLAGS,
    "mango_group" / PublicKeyAdapter(),
    "owner" / PublicKeyAdapter(),
    "deposits" / construct.Array(NUM_TOKENS, FloatAdapter()),
    "borrows" / construct.Array(NUM_TOKENS, FloatAdapter()),
    "open_orders" / construct.Array(NUM_MARKETS, PublicKeyAdapter()),
    "padding" / construct.Padding(8)
)

MANGO_INSTRUCTION_VARIANT_FINDER = construct.Struct(
    "variant" / construct.BytesInteger(4, swapped=True)
)

INIT_MANGO_GROUP = construct.Struct(
    "variant" / construct.Const(0x0, construct.BytesInteger(4, swapped=True)),
    "signer_nonce" / DecimalAdapter(),
    "maint_coll_ratio" / FloatAdapter(),
    "init_coll_ratio" / FloatAdapter(),
    #  "borrow_limits" / construct.Array(NUM_TOKENS, DecimalAdapter())  # This is inconsistently available
)

INIT_MARGIN_ACCOUNT = construct.Struct(
    "variant" / construct.Const(0x1, construct.BytesInteger(4, swapped=True)),
)

DEPOSIT = construct.Struct(
    "variant" / construct.Const(0x2, construct.BytesInteger(4, swapped=True)),
    "quantity" / DecimalAdapter()
)

WITHDRAW = construct.Struct(
    "variant" / construct.Const(0x3, construct.BytesInteger(4, swapped=True)),
    "quantity" / DecimalAdapter()
)

BORROW = construct.Struct(
    "variant" / construct.Const(0x4, construct.BytesInteger(4, swapped=True)),
    "token_index" / DecimalAdapter(),
    "quantity" / DecimalAdapter()
)

SETTLE_BORROW = construct.Struct(
    "variant" / construct.Const(0x5, construct.BytesInteger(4, swapped=True)),
    "token_index" / DecimalAdapter(),
    "quantity" / DecimalAdapter()
)

LIQUIDATE = construct.Struct(
    "variant" / construct.Const(0x6, construct.BytesInteger(4, swapped=True)),
    "deposit_quantities" / construct.Array(NUM_TOKENS, DecimalAdapter())
)

DEPOSIT_SRM = construct.Struct(
    "variant" / construct.Const(0x7, construct.BytesInteger(4, swapped=True)),
    "quantity" / DecimalAdapter()
)

WITHDRAW_SRM = construct.Struct(
    "variant" / construct.Const(0x8, construct.BytesInteger(4, swapped=True)),
    "quantity" / DecimalAdapter()
)

PLACE_ORDER = construct.Struct(
    "variant" / construct.Const(0x9, construct.BytesInteger(4, swapped=True)),
    "order" / construct.Padding(1)  # Actual type is: serum_dex::instruction::NewOrderInstructionV3
)

SETTLE_FUNDS = construct.Struct(
    "variant" / construct.Const(0xa, construct.BytesInteger(4, swapped=True)),
)

CANCEL_ORDER = construct.Struct(
    "variant" / construct.Const(0xb, construct.BytesInteger(4, swapped=True)),
    "order" / construct.Padding(1)  # Actual type is: serum_dex::instruction::CancelOrderInstructionV2
)

CANCEL_ORDER_BY_CLIENT_ID = construct.Struct(
    "variant" / construct.Const(0xc, construct.BytesInteger(4, swapped=True)),
    "client_id" / DecimalAdapter()
)

CHANGE_BORROW_LIMIT = construct.Struct(
    "variant" / construct.Const(0xd, construct.BytesInteger(4, swapped=True)),
    "token_index" / DecimalAdapter(),
    "borrow_limit" / DecimalAdapter()
)

PLACE_AND_SETTLE = construct.Struct(
    "variant" / construct.Const(0xe, construct.BytesInteger(4, swapped=True)),
    "order" / construct.Padding(1)  # Actual type is: serum_dex::instruction::NewOrderInstructionV3
)
FORCE_CANCEL_ORDERS = construct.Struct(
    "variant" / construct.Const(0xf, construct.BytesInteger(4, swapped=True)),
    "limit" / DecimalAdapter(1)
)

PARTIAL_LIQUIDATE = construct.Struct(
    "variant" / construct.Const(0x10, construct.BytesInteger(4, swapped=True)),
    "max_deposit" / DecimalAdapter()
)

InstructionParsersByVariant = {
    0: INIT_MANGO_GROUP,
    1: INIT_MARGIN_ACCOUNT,
    2: DEPOSIT,
    3: WITHDRAW,
    4: BORROW,
    5: SETTLE_BORROW,
    6: LIQUIDATE,
    7: DEPOSIT_SRM,
    8: WITHDRAW_SRM,
    9: PLACE_ORDER,
    10: SETTLE_FUNDS,
    11: CANCEL_ORDER,
    12: CANCEL_ORDER_BY_CLIENT_ID,
    13: CHANGE_BORROW_LIMIT,
    14: PLACE_AND_SETTLE,
    15: FORCE_CANCEL_ORDERS,
    16: PARTIAL_LIQUIDATE
}

if __name__ == "__main__":
    import base64
    import logging

    logging.getLogger().setLevel(logging.INFO)

    encoded = "AwAAAAAAAACCaOmpoURMK6XHelGTaFawcuQ/78/15LAemWI8jrt3SRKLy2R9i60eclDjuDS8+p/ZhvTUd9G7uQVOYCsR6+BhmqGCiO6EPYP2PQkf/VRTvw7JjXvIjPFJy06QR1Cq1WfTonHl0OjCkyEf60SD07+MFJu5pVWNFGGEO/8AiAYfduaKdnFTaZEHPcK5Eq72WWHeHg2yIbBF09kyeOhlCJwOoG8O5SgpPV8QOA64ZNV4aKroFfADg6kEy/wWCdp3fv0O4GJgAAAAAPH6Ud6jtjwAAQAAAAAAAADiDkkCi9UOAAEAAAAAAAAADuBiYAAAAACNS5bSy7soAAEAAAAAAAAACMvgO+2jCwABAAAAAAAAAA7gYmAAAAAAZFeDUBNVhwABAAAAAAAAABtRNytozC8AAQAAAAAAAABIBGiCcyaEZdNhrTyeqUY692vOzzPdHaxAxguht3JQGlkzjtd05dX9LENHkl2z1XvUbTNKZlweypNRetmH0lmQ9VYQAHqylxZVK65gEg85g27YuSyvOBZAjJyRmYU9KdCO1D+4ehdPu9dQB1yI1uh75wShdAaFn2o4qrMYwq3SQQEAAAAAAAAAAiH1PPJKAuh6oGiE35aGhUQhFi/bxgKOudpFv8HEHNCFDy1uAqR6+CTQmradxC1wyyjL+iSft+5XudJWwSdi7wvphsxb96x7Obj/AgAAAAAKlV4LL5ow6r9LMhIAAAAADvsOtqcVFmChDPzPnwAAAE33lx1h8hPFD04AAAAAAAA8YRV3Oa309B2wGwAAAAAA+yPBZRlZz7b605n+AQAAAACgmZmZmZkZAQAAAAAAAAAAMDMzMzMzMwEAAAAAAAAA25D1XcAtRzSuuyx3U+X7aE9vM1EJySU9KprgL0LMJ/vat9+SEEUZuga7O5tTUrcMDYWDg+LYaAWhSQiN2fYk7aCGAQAAAAAAgIQeAAAAAAAA8gUqAQAAAAYGBgICAAAA"
    decoded = base64.b64decode(encoded)

    group = GROUP.parse(decoded)
    print("\n\nThis is hard-coded, not live information!")
    print(group)