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