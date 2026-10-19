"""Find this download's update on GitHub and download it, checked against
SHA256SUMS.txt and its signature (``signature``), into the updates folder
(``settings.updates_dir``); and check a zip downloaded by hand
(``verify_zip``).

Toolkit-free; the network is passed in as ``open_url`` (``urllib.request.urlopen``
unless a caller gives another), so tests serve releases from 127.0.0.1.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import __version__, buildinfo, settings, signature
from .logger import get_logger
from .notifications import NEWER, _parse_version, update_status
from .signature import SIG_NAME

_log = get_logger("updates")

RELEASES_API = "https://api.github.com/repos/lqvu-zen/RYOS/releases"
SUMS_NAME = "SHA256SUMS.txt"
USER_AGENT = "RYOS-update-check"

_TAG = re.compile(r"v?\d+(\.\d+)*(-[A-Za-z0-9]+)?")
_SUMS_LINE = re.compile(r"([0-9a-fA-F]{64}) [ *](.+)")

OpenUrl = Callable[..., Any]


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    size: int = 0


@dataclass(frozen=True)
class Release:
    tag: str
    url: str
    prerelease: bool = False
    assets: dict[str, Asset] = field(default_factory=dict)

    @property
    def check(self) -> tuple[str, str]:
        return self.tag, self.url


@dataclass(frozen=True)
class Outcome:
    ok: bool
    message: str
    path: Path | None = None


class _CutOff(Exception):
    pass


def asset_name(which: str | None = None) -> str | None:
    which = which or buildinfo.variant()
    if which == buildinfo.PORTABLE:
        return None
    return buildinfo.DOWNLOADS.get(which)


def pick_asset(release: Release, which: str | None = None) -> Asset | None:
    name = asset_name(which)
    return release.assets.get(name) if name else None


def _open(open_url: OpenUrl | None, url: str, timeout: float, headers=None):
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    return (open_url or urllib.request.urlopen)(request, timeout=timeout)


def _release_from(data: dict) -> Release:
    assets = {}
    for item in data.get("assets") or []:
        name = item["name"]
        assets[name] = Asset(name, item["browser_download_url"],
                             int(item.get("size") or 0))
    return Release(data["tag_name"], data["html_url"],
                   bool(data.get("prerelease")), assets)


def fetch_release(prereleases: bool = False, *, open_url: OpenUrl | None = None,
                  api: str | None = None) -> Release | None:
    api = api or buildinfo.test_releases_api() or RELEASES_API
    url = api if prereleases else api + "/latest"
    try:
        with _open(open_url, url, 8) as resp:
            data = json.loads(resp.read())
        if prereleases:
            listed = [r for r in data if isinstance(r, dict) and not r.get("draft")]
            if not listed:
                return None
            data = max(listed, key=lambda r: _parse_version(str(r.get("tag_name", ""))))
        return _release_from(data)
    except (OSError, http.client.HTTPException, ValueError, KeyError,
            TypeError, AttributeError) as e:
        _log.debug("Update fetch failed: %s", e)
        return None


def parse_sums(text: str) -> dict[str, str]:
    found = {}
    for line in text.splitlines():
        match = _SUMS_LINE.fullmatch(line.strip())
        if match:
            found[match.group(2).strip()] = match.group(1).lower()
    return found


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def _fetch_into(open_url: OpenUrl | None, asset: Asset, part: Path) -> None:
    have = _size(part)
    if asset.size and have > asset.size:
        part.unlink()
        have = 0
    if asset.size and have == asset.size:
        return
    headers = {"Range": f"bytes={have}-"} if have else {}
    try:
        resp = _open(open_url, asset.url, 30, headers)
    except urllib.error.HTTPError as e:
        if e.code == 416:
            part.unlink(missing_ok=True)
            raise _CutOff("the server refused to carry on; starting again") from e
        raise
    with resp:
        status = getattr(resp, "status", 200)
        content_range = resp.headers.get("Content-Range", "") or ""
        resumes = have and status == 206 and content_range.startswith(f"bytes {have}-")
        try:
            with open(part, "ab" if resumes else "wb") as f:
                for block in iter(lambda: resp.read(1 << 16), b""):
                    f.write(block)
        except (OSError, http.client.HTTPException) as e:
            raise _CutOff(str(e)) from e
    if asset.size and _size(part) < asset.size:
        raise _CutOff("the connection closed early")


FROM_SOURCE = ("RYOS from source does not update itself: get the new version "
               "with git pull or a fresh RYOS-portable.zip.")

NO_KEY = ("This RYOS carries no release key, so it cannot check an update's "
          "signature and downloads nothing: get the new version from the release page.")


def _fetch_small(open_url: OpenUrl | None, asset: Asset, limit: int | None = None) -> bytes:
    with _open(open_url, asset.url, 30) as resp:
        return resp.read() if limit is None else resp.read(limit)


def _read_small(path: Path, limit: int) -> bytes:
    with open(path, "rb") as f:
        return f.read(limit)


def download(release: Release, which: str | None = None, *,
             open_url: OpenUrl | None = None, attempts: int = 3,
             key: bytes | None = None, current: str | None = None) -> Outcome:
    which = which or buildinfo.variant()
    name = asset_name(which)
    if name is None:
        return Outcome(False, FROM_SOURCE)
    if not isinstance(release.tag, str) or not _TAG.fullmatch(release.tag):
        return Outcome(False, f"The release tag {release.tag!r} is not a version "
                       "RYOS can use, so nothing was downloaded.")
    key = key or buildinfo.release_key()
    if key is None:
        return Outcome(False, NO_KEY)
    asset = release.assets.get(name)
    if asset is None:
        return Outcome(False, f"RYOS {release.tag} has no {name}, so there is "
                       "nothing to download for this kind of RYOS.")
    sums_asset = release.assets.get(SUMS_NAME)
    if sums_asset is None:
        return Outcome(False, f"RYOS {release.tag} has no {SUMS_NAME}, so its "
                       f"{name} cannot be checked and was not downloaded.")
    sig_asset = release.assets.get(SIG_NAME)
    if sig_asset is None:
        return Outcome(False, f"RYOS {release.tag} has no {SIG_NAME}, so its "
                       f"{name} cannot be checked and was not downloaded.")
    try:
        sums_bytes = _fetch_small(open_url, sums_asset)
    except (OSError, http.client.HTTPException) as e:
        return Outcome(False, f"Could not download {SUMS_NAME} for RYOS "
                       f"{release.tag}: {e}")
    try:
        sig_bytes = _fetch_small(open_url, sig_asset, signature.MAX_SIZE + 1)
    except (OSError, http.client.HTTPException) as e:
        return Outcome(False, f"Could not download {SIG_NAME} for RYOS "
                       f"{release.tag}: {e}")
    checked = signature.check(sums_bytes, sig_bytes, key, version=release.tag,
                              current=current or __version__)
    if not checked.ok:
        return Outcome(False, f"RYOS {release.tag} was not downloaded: {checked.message}")
    folder = settings.updates_dir(release.tag)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / SUMS_NAME).write_bytes(sums_bytes)
        (folder / SIG_NAME).write_bytes(sig_bytes)
    except OSError as e:
        return Outcome(False, f"Could not save {SUMS_NAME} for RYOS "
                       f"{release.tag}: {e}")
    expected = parse_sums(sums_bytes.decode("utf-8", "replace")).get(name)
    if expected is None:
        return Outcome(False, f"{SUMS_NAME} for RYOS {release.tag} has no line "
                       f"for {name}, so it cannot be checked and was not downloaded.")
    target = folder / name
    part = folder / (name + ".part")
    try:
        if target.exists():
            if _sha256(target) == expected:
                return Outcome(True, f"{name} for RYOS {release.tag} is already "
                               "downloaded and checked.", target)
            target.unlink()
    except OSError as e:
        return _unreadable(name, release.tag, e)
    for _ in range(max(1, attempts)):
        try:
            _fetch_into(open_url, asset, part)
            break
        except _CutOff as e:
            _log.info("Download of %s cut off: %s", name, e)
        except (OSError, http.client.HTTPException) as e:
            return Outcome(False, f"Could not download {name} for RYOS "
                           f"{release.tag}: {e}")
    else:
        return Outcome(False, f"The download of {name} kept being cut off; it "
                       "carries on from where it stopped next time.")
    try:
        matches = _sha256(part) == expected
    except OSError as e:
        return _unreadable(name, release.tag, e)
    if not matches:
        part.unlink(missing_ok=True)
        return Outcome(False, f"{name} for RYOS {release.tag} did not match its "
                       f"line in {SUMS_NAME}, so it was deleted.")
    try:
        os.replace(part, target)
    except OSError as e:
        return Outcome(False, f"Could not put {name} for RYOS {release.tag} in "
                       f"place: {e}; it is tried again next time.")
    return Outcome(True, f"Downloaded {name} for RYOS {release.tag} and checked "
                   f"it against its signed {SUMS_NAME}.", target)


def _unreadable(name: str, tag: str, error: OSError) -> Outcome:
    return Outcome(False, f"Could not check {name} for RYOS {tag}: {error}")


def check_of(result) -> tuple[str, str] | None:
    if isinstance(result, Release):
        return result.check
    return result


def wants_download(result, current: str, *, allowed: bool,
                   which: str | None = None) -> bool:
    if not allowed or not isinstance(result, Release):
        return False
    if asset_name(which) is None:
        return False
    return update_status(result.check, current)[0] == NEWER


def downloaded(tag: str, which: str | None = None, *,
               key: bytes | None = None) -> Path | None:
    name = asset_name(which)
    if name is None or not isinstance(tag, str) or not _TAG.fullmatch(tag):
        return None
    key = key or buildinfo.release_key()
    if key is None:
        return None
    folder = settings.updates_dir(tag)
    target = folder / name
    try:
        if not target.is_file():
            return None
        sums = (folder / SUMS_NAME).read_bytes()
        sig = _read_small(folder / SIG_NAME, signature.MAX_SIZE + 1)
        if not signature.check(sums, sig, key, version=tag).ok:
            return None
        expected = parse_sums(sums.decode("utf-8", "replace")).get(name)
        if expected is None or _sha256(target) != expected:
            return None
    except OSError:
        return None
    return target


def verify_zip(path: str | os.PathLike, *, key: bytes | None = None,
               current: str | None = None) -> Outcome:
    """Check a zip downloaded by hand, with the SHA256SUMS.txt and its
    signature from the same release beside it."""
    path = Path(path)
    if not path.is_file():
        return Outcome(False, f"There is no file at {path}.")
    key = key or buildinfo.release_key()
    if key is None:
        return Outcome(False, "This RYOS carries no release key (it runs from source "
                       "or was built without one), so it cannot check a download's "
                       "signature.")
    sums_path = path.with_name(SUMS_NAME)
    sig_path = path.with_name(SIG_NAME)
    if not sums_path.is_file():
        return Outcome(False, f"There is no {SUMS_NAME} beside {path.name}: download "
                       f"it from the same release into {path.parent}.")
    try:
        sums = sums_path.read_bytes()
        sig = _read_small(sig_path, signature.MAX_SIZE + 1) if sig_path.is_file() else None
    except OSError as e:
        return Outcome(False, f"Could not read {SUMS_NAME} or {SIG_NAME}: {e}")
    checked = signature.check(sums, sig, key, current=current or __version__)
    if not checked.ok:
        return Outcome(False, f"{path.name} was not verified: {checked.message}")
    expected = parse_sums(sums.decode("utf-8", "replace")).get(path.name)
    if expected is None:
        return Outcome(False, f"{SUMS_NAME} has no line for {path.name}, so it "
                       "cannot be checked.")
    try:
        matches = _sha256(path) == expected
    except OSError as e:
        return Outcome(False, f"Could not read {path.name}: {e}")
    if not matches:
        return Outcome(False, f"{path.name} does not match its line in {SUMS_NAME}: "
                       "it has been changed, or it is not this release's file.")
    return Outcome(True, f"{path.name} is RYOS {checked.version}: signed with this "
                   f"RYOS's release key and matching {SUMS_NAME}.", path)
