"""Make RYOS's release key, and sign a release's SHA256SUMS.txt with it.

    uv run --with cryptography python tools/sign_release.py new KEYFILE
    uv run --with cryptography python tools/sign_release.py sign KEYFILE [--sums dist/SHA256SUMS.txt] [--version V]

The private key lives outside the repository, protected by a passphrase; this
tool ships in no download. See docs/ARCHITECTURE.md.
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import sys
from pathlib import Path
from typing import Callable, TextIO

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ryos import __version__, signature  # noqa: E402

_SUMS_LINE = re.compile(r"[0-9a-f]{64}  [^\s/\\][^/\\]*")

KEY_LOST = ("Keep the key file and its passphrase safe, and outside the repository. "
            "If either is lost, a new key pair means every RYOS needs one manual "
            "update to a build carrying the new public key.")


class ToolError(Exception):
    pass


def inside_repo(path: str | os.PathLike, root: Path = ROOT) -> bool:
    resolved = Path(path).expanduser().resolve()
    root = root.resolve()
    return resolved == root or root in resolved.parents


def _refuse_in_repo(path: Path) -> None:
    if inside_repo(path):
        raise ToolError(f"{path} is inside the repository ({ROOT}): keep the release "
                        "key somewhere else, so it can never be committed.")


def _public_bytes(private) -> bytes:
    from cryptography.hazmat.primitives import serialization
    return private.public_key().public_bytes(serialization.Encoding.Raw,
                                             serialization.PublicFormat.Raw)


def new_key(keyfile: str | os.PathLike, passphrase: str,
            out: TextIO | None = None) -> bytes:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    out = out or sys.stdout
    path = Path(keyfile).expanduser()
    _refuse_in_repo(path)
    if not passphrase:
        raise ToolError("The passphrase cannot be empty.")
    private = Ed25519PrivateKey.generate()
    pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(passphrase.encode("utf-8")))
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        raise ToolError(f"{path} already exists: a key file is never overwritten.") from None
    except OSError as e:
        raise ToolError(f"Could not write {path}: {e}") from None
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    public = _public_bytes(private)
    print(f"Wrote the encrypted release key to {path}.", file=out)
    print(f"Public key: {public.hex()}", file=out)
    print(KEY_LOST, file=out)
    return public


def _load(keyfile: Path, passphrase: str):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    try:
        data = keyfile.read_bytes()
    except OSError as e:
        raise ToolError(f"Could not read {keyfile}: {e}") from None
    try:
        private = serialization.load_pem_private_key(
            data, password=passphrase.encode("utf-8") if passphrase else None)
    except (ValueError, TypeError):
        raise ToolError(f"Could not open {keyfile}: a wrong passphrase, or not a "
                        "release key.") from None
    if not isinstance(private, Ed25519PrivateKey):
        raise ToolError(f"{keyfile} is not an Ed25519 key.")
    return private


def _check_sums(sums: bytes, path: Path) -> None:
    if b"\r" in sums:
        raise ToolError(f"{path} has CR line endings: build_release.py writes LF only.")
    if not sums.endswith(b"\n"):
        raise ToolError(f"{path} does not end with a line break.")
    try:
        text = sums.decode("utf-8")
    except UnicodeDecodeError:
        raise ToolError(f"{path} is not UTF-8 text.") from None
    for number, line in enumerate(text[:-1].split("\n"), 1):
        if not _SUMS_LINE.fullmatch(line):
            raise ToolError(f"Line {number} of {path} is not '<64 hex>  <name>': {line!r}")


def sign_sums(keyfile: str | os.PathLike, passphrase: str,
              sums_path: str | os.PathLike = "dist/SHA256SUMS.txt",
              version: str | None = None, out: TextIO | None = None) -> Path:
    out = out or sys.stdout
    keyfile = Path(keyfile).expanduser()
    _refuse_in_repo(keyfile)
    wanted = signature.version_of(__version__ if version is None else version)
    if wanted is None:
        raise ToolError(f"{version!r} is not a version (for example 2.4.0 or 2.4.0-rc1).")
    sums_path = Path(sums_path)
    try:
        sums = sums_path.read_bytes()
    except OSError as e:
        raise ToolError(f"Could not read {sums_path}: {e}") from None
    _check_sums(sums, sums_path)
    private = _load(keyfile, passphrase)
    public = _public_bytes(private)
    made = private.sign(signature.signed_message(wanted, sums))
    sig = signature.signature_file(wanted, public, made)
    checked = signature.check(sums, sig, public, version=wanted)
    if not checked.ok:
        raise ToolError(f"The signature did not check: {checked.message}")
    target = sums_path.with_name(signature.SIG_NAME)
    try:
        target.write_bytes(sig)
    except OSError as e:
        raise ToolError(f"Could not write {target}: {e}") from None
    print(f"Signed {sums_path.name} for RYOS {wanted}: wrote {target}.", file=out)
    print(f"Public key: {public.hex()}", file=out)
    return target


def _ask_new_passphrase(ask: Callable[[str], str]) -> str:
    first = ask("Passphrase for the new key: ")
    if not first:
        raise ToolError("The passphrase cannot be empty.")
    if ask("The same passphrase again: ") != first:
        raise ToolError("The two passphrases differ; nothing was written.")
    return first


def main(argv: list[str] | None = None, *,
         ask: Callable[[str], str] = getpass.getpass,
         out: TextIO | None = None, err: TextIO | None = None) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    parser = argparse.ArgumentParser(prog="sign_release",
                                     description="Make or use RYOS's release key.")
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("new", help="Make a new key pair, encrypted with a passphrase.")
    new.add_argument("keyfile", metavar="KEYFILE")
    sg = sub.add_parser("sign", help="Write SHA256SUMS.txt.sig beside SHA256SUMS.txt.")
    sg.add_argument("keyfile", metavar="KEYFILE")
    sg.add_argument("--sums", default=str(ROOT / "dist" / "SHA256SUMS.txt"))
    sg.add_argument("--version", dest="release_version", default=None,
                    help=f"The version it is for (default {__version__}).")
    args = parser.parse_args(argv)
    try:
        if args.command == "new":
            _refuse_in_repo(Path(args.keyfile))
            if Path(args.keyfile).expanduser().exists():
                raise ToolError(f"{args.keyfile} already exists: a key file is never "
                                "overwritten.")
            new_key(args.keyfile, _ask_new_passphrase(ask), out)
        else:
            _refuse_in_repo(Path(args.keyfile))
            sign_sums(args.keyfile, ask("Passphrase: "), args.sums,
                      args.release_version, out)
    except ToolError as e:
        print(f"sign_release: {e}", file=err)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
