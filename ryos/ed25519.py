"""Ed25519 (RFC 8032) in pure Python, verify only: the check RYOS runs on a
release's SHA256SUMS.txt.sig. See docs/ARCHITECTURE.md."""

from __future__ import annotations

import hashlib

Point = tuple[int, int, int, int]

_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _recover_x(y: int, odd: int) -> int | None:
    if y >= _P:
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    if x2 == 0:
        return None if odd else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P:
        return None
    if (x & 1) != odd:
        x = _P - x
    return x


def _decode(data: bytes) -> Point | None:
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    odd = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, odd)
    if x is None:
        return None
    return x, y, 1, x * y % _P


def _add(a: Point, b: Point) -> Point:
    pa = (a[1] - a[0]) * (b[1] - b[0]) % _P
    pb = (a[1] + a[0]) * (b[1] + b[0]) % _P
    pc = 2 * a[3] * b[3] * _D % _P
    pd = 2 * a[2] * b[2] % _P
    e, f, g, h = pb - pa, pd - pc, pd + pc, pb + pa
    return e * f % _P, g * h % _P, f * g % _P, e * h % _P


def _mul(scalar: int, point: Point) -> Point:
    total: Point = (0, 1, 1, 0)
    while scalar > 0:
        if scalar & 1:
            total = _add(total, point)
        point = _add(point, point)
        scalar >>= 1
    return total


def _equal(a: Point, b: Point) -> bool:
    return ((a[0] * b[2] - b[0] * a[2]) % _P == 0
            and (a[1] * b[2] - b[1] * a[2]) % _P == 0)


_GY = 4 * pow(5, _P - 2, _P) % _P
_GX = _recover_x(_GY, 0) or 0
_G: Point = (_GX, _GY, 1, _GX * _GY % _P)


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """Whether ``signature`` is ``public_key``'s Ed25519 signature of
    ``message``. False, never an exception, for anything malformed."""
    if not all(isinstance(part, (bytes, bytearray, memoryview))
               for part in (public_key, message, signature)):
        return False
    public_key, message, signature = bytes(public_key), bytes(message), bytes(signature)
    if len(public_key) != 32 or len(signature) != 64:
        return False
    a = _decode(public_key)
    r = _decode(signature[:32])
    if a is None or r is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False
    k = int.from_bytes(hashlib.sha512(signature[:32] + public_key + message).digest(),
                       "little") % _L
    return _equal(_mul(s, _G), _add(r, _mul(k, a)))
