"""Consumer Copilot proof-of-work challenge solvers."""

import base64
import binascii
import hashlib
import math
import struct
from dataclasses import dataclass


@dataclass(frozen=True)
class HashcashChallenge:
    seed: str
    difficulty: int


def solve_copilot_challenge(parameter: str) -> str:
    value = int(parameter)
    result = round(((value**3) / 100 + value * 25) % 22)
    return str(result)


def solve_hashcash(parameter: str) -> str:
    challenge = _parse_hashcash(parameter)
    nonce = 0
    while True:
        candidate = f"{challenge.seed}{nonce}"
        digest = hashlib.sha256(candidate.encode("utf-8")).digest()
        if _leading_zero_bits(digest) >= challenge.difficulty:
            return str(nonce)
        nonce += 1


def _parse_hashcash(parameter: str) -> HashcashChallenge:
    decoded = parameter if ":" in parameter else _decode_hashcash_parameter(parameter)
    seed, separator, difficulty = decoded.rpartition(":")
    if not separator or not seed:
        raise ValueError("Invalid hashcash challenge")
    return HashcashChallenge(seed=seed, difficulty=int(difficulty))


def _decode_hashcash_parameter(parameter: str) -> str:
    padded = parameter + "=" * (-len(parameter) % 4)
    for decoder in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            return decoder(padded).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            continue
    return parameter


def _leading_zero_bits(data: bytes) -> int:
    count = 0
    for byte in data:
        if byte == 0:
            count += 8
            continue
        count += 8 - math.floor(math.log2(byte)) - 1
        break
    return count


def pack_uint32(value: int) -> bytes:
    return struct.pack(">I", value)
