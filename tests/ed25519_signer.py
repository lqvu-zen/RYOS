"""Test only: Ed25519 signing over ryos.ed25519's internals, so tests can sign
SHA256SUMS.txt with the RFC 8032 test keys. Never shipped."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ryos import ed25519, signature  # noqa: E402

TEST_SEED = bytes.fromhex(
    "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
TEST_PUBLIC = bytes.fromhex(
    "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
OTHER_SEED = bytes.fromhex(
    "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb")
OTHER_PUBLIC = bytes.fromhex(
    "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c")


def _encode(point) -> bytes:
    p = ed25519._P
    zinv = pow(point[2], p - 2, p)
    x = point[0] * zinv % p
    y = point[1] * zinv % p
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _int(data: bytes) -> int:
    return int.from_bytes(data, "little")


def sign(seed: bytes, message: bytes) -> tuple[bytes, bytes]:
    digest = hashlib.sha512(seed).digest()
    a = _int(digest[:32])
    a &= (1 << 254) - 8
    a |= 1 << 254
    public = _encode(ed25519._mul(a, ed25519._G))
    r = _int(hashlib.sha512(digest[32:] + message).digest()) % ed25519._L
    big_r = _encode(ed25519._mul(r, ed25519._G))
    k = _int(hashlib.sha512(big_r + public + message).digest()) % ed25519._L
    s = (r + k * a) % ed25519._L
    return public, big_r + s.to_bytes(32, "little")


def sig_file(seed: bytes, version: str, sums: bytes) -> bytes:
    public, sig = sign(seed, signature.signed_message(version, sums))
    return signature.signature_file(version, public, sig)
