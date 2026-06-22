"""Consumer Copilot proof-of-work challenge solvers."""

import base64
import hashlib
import math
import struct
from dataclasses import dataclass


@dataclass(frozen=True)
class HashcashChallenge:
    prefix: str
    difficulty: int


def solve_copilot_challenge(parameter: str) -> str:
    value = int(parameter)
    result = round(((value**3) / 100 + value * 25) % 22)
    return str(result)


def solve_hashcash(parameter: str) -> str:
    challenge = _parse_hashcash(parameter)
    nonce = 0
    while True:
        candidate = f"{challenge.prefix}{nonce}"
        digest = hashlib.sha256(candidate.encode("utf-8")).digest()
        if _leading_zero_bits(digest) >= challenge.difficulty:
            return base64.b64encode(candidate.encode("utf-8")).decode("ascii")
        nonce += 1


def _parse_hashcash(parameter: str) -> HashcashChallenge:
    decoded = base64.b64decode(parameter).decode("utf-8")
    parts = decoded.split(":")
    if len(parts) < 2:
        raise ValueError("Invalid hashcash challenge")
    return HashcashChallenge(prefix=f"{decoded}:", difficulty=int(parts[1]))


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
