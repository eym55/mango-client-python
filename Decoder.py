import base64
import base58
import logging
import typing

from solana.publickey import PublicKey


def decode_binary(encoded: typing.List) -> bytes:
    if isinstance(encoded, str):
        return base58.b58decode(encoded)
    elif encoded[1] == "base64":
        return base64.b64decode(encoded[0])
    else:
        return base58.b58decode(encoded[0])

def encode_binary(decoded: bytes) -> typing.List:
    return [base64.b64encode(decoded), "base64"]

def encode_key(key: PublicKey) -> str:
    return str(key)

if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO)

    data = decode_binary(['AwAAAAAAAACCaOmpoURMK6XHelGTaFawcuQ/78/15LAemWI8jrt3SRKLy2R9i60eclDjuDS8+p/ZhvTUd9G7uQVOYCsR6+BhmqGCiO6EPYP2PQkf/VRTvw7JjXvIjPFJy06QR1Cq1WfTonHl0OjCkyEf60SD07+MFJu5pVWNFGGEO/8AiAYfduaKdnFTaZEHPcK5Eq72WWHeHg2yIbBF09kyeOhlCJwOoG8O5SgpPV8QOA64ZNV4aKroFfADg6kEy/wWCdp3fv2B8WJgAAAAANVfH3HGtjwAAQAAAAAAAADr8cwFi9UOAAEAAAAAAAAAgfFiYAAAAABo3Dbz0L0oAAEAAAAAAAAAr8K+TvCjCwABAAAAAAAAAIHxYmAAAAAA49t5tVNZhwABAAAAAAAAAAmPtcB1zC8AAQAAAAAAAABIBGiCcyaEZdNhrTyeqUY692vOzzPdHaxAxguht3JQGlkzjtd05dX9LENHkl2z1XvUbTNKZlweypNRetmH0lmQ9VYQAHqylxZVK65gEg85g27YuSyvOBZAjJyRmYU9KdCO1D+4ehdPu9dQB1yI1uh75wShdAaFn2o4qrMYwq3SQQEAAAAAAAAAAiH1PPJKAuh6oGiE35aGhUQhFi/bxgKOudpFv8HEHNCFDy1uAqR6+CTQmradxC1wyyjL+iSft+5XudJWwSdi72NJGmyK96x7Obj/AgAAAAB8RjOEdJow6r9LMhIAAAAAGkNK4CXHh5M2st7PnwAAAE33lx1h8hPFD04AAAAAAAA8YRV3Oa309B2wGwAAAAAAOIlOLmkr6+r605n+AQAAAACgmZmZmZkZAQAAAAAAAAAAMDMzMzMzMwEAAAAAAAAA25D1XcAtRzSuuyx3U+X7aE9vM1EJySU9KprgL0LMJ/vat9+SEEUZuga7O5tTUrcMDYWDg+LYaAWhSQiN2fYk7aCGAQAAAAAAgIQeAAAAAAAA8gUqAQAAAAYGBgICAAAA', 'base64'])
    print(f"Data length (should be 744): {len(data)}")