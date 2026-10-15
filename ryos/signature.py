"""SHA256SUMS.txt.sig: the release signature's format, and the check of a
SHA256SUMS.txt against it with the build's release key. See
docs/ARCHITECTURE.md."""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import ed25519

SIG_NAME = "SHA256SUMS.txt.sig"
SUMS_NAME = "SHA256SUMS.txt"
HEADER = "RYOS signature 1"
MESSAGE_HEADER = b"RYOS SHA256SUMS.txt signature 1\n"
MAX_SIZE = 4096

_VERSION = re.compile(r"\d+(\.\d+)*(-[A-Za-z0-9]+)?", re.ASCII)
_HEX64 = re.compile(r"[0-9a-f]{64}")
_HEX128 = re.compile(r"[0-9a-f]{128}")
_FIELDS = ("version", "key", "signature")


def version_of(tag: object) -> str | None:
    """The version a release tag names ('v2.4.0' -> '2.4.0'), or None."""
    if not isinstance(tag, str):
        return None
    version = tag[1:] if tag.startswith("v") else tag
    return version if _VERSION.fullmatch(version) else None


def _is_version(version: object) -> bool:
    return isinstance(version, str) and _VERSION.fullmatch(version) is not None


def signed_message(version: str, sums: bytes) -> bytes:
    """The bytes a release signature covers: a header, the version, then
    SHA256SUMS.txt exactly as published."""
    if not _is_version(version):
        raise ValueError(f"not a version: {version!r}")
    return MESSAGE_HEADER + b"version " + version.encode("ascii") + b"\n" + bytes(sums)


@dataclass(frozen=True)
class Signature:
    version: str
    key: bytes
    signature: bytes


def parse(data: bytes) -> Signature | None:
    """The four lines of a SHA256SUMS.txt.sig, or None when it is not one."""
    if not isinstance(data, (bytes, bytearray)) or len(data) > MAX_SIZE:
        return None
    try:
        text = bytes(data).decode("ascii")
    except UnicodeDecodeError:
        return None
    lines = [line.rstrip() for line in text.split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    if len(lines) != 4 or lines[0] != HEADER:
        return None
    values = []
    for line, name in zip(lines[1:], _FIELDS):
        label, space, value = line.partition(" ")
        if label != name or not space:
            return None
        values.append(value)
    version, key, sig = values
    if not (_is_version(version) and _HEX64.fullmatch(key) and _HEX128.fullmatch(sig)):
        return None
    return Signature(version, bytes.fromhex(key), bytes.fromhex(sig))


def signature_file(version: str, key: bytes, signature: bytes) -> bytes:
    """The text of SHA256SUMS.txt.sig."""
    if not _is_version(version) or len(key) != 32 or len(signature) != 64:
        raise ValueError("a signature file needs a version, a 32-byte key "
                         "and a 64-byte signature")
    return (f"{HEADER}\nversion {version}\nkey {bytes(key).hex()}\n"
            f"signature {bytes(signature).hex()}\n").encode("ascii")


@dataclass(frozen=True)
class Checked:
    ok: bool
    message: str
    version: str | None = None


def check(sums: bytes, sig: bytes | None, key: bytes, *, version: str | None = None,
          current: str | None = None) -> Checked:
    """Whether ``sig`` is the release key's signature of ``sums``; with
    ``version``, for that release; with ``current``, not older than it."""
    if sig is None:
        return Checked(False, f"there is no {SIG_NAME}, so {SUMS_NAME} cannot be "
                              "shown to come from RYOS's maintainer.")
    parsed = parse(sig)
    if parsed is None:
        return Checked(False, f"{SIG_NAME} is not a signature file RYOS can read.")
    if parsed.key != bytes(key):
        return Checked(False, f"{SIG_NAME} was signed with a different key from "
                              "this RYOS's release key.")
    if not ed25519.verify(bytes(key), signed_message(parsed.version, sums),
                          parsed.signature):
        return Checked(False, f"{SUMS_NAME} or {SIG_NAME} has been changed since "
                              "it was signed.")
    if version is not None and version_of(version) != parsed.version:
        return Checked(False, f"the signature is for RYOS {parsed.version}, not "
                              f"{version}.")
    if current is not None:
        from .notifications import _parse_version
        if _parse_version(parsed.version) < _parse_version(current):
            return Checked(False, f"it is RYOS {parsed.version}, older than this "
                                  f"RYOS ({current}).")
    return Checked(True, f"signed for RYOS {parsed.version} with this RYOS's "
                         "release key.", parsed.version)
