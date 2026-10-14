"""Find this download's update on GitHub and download it, checked against
SHA256SUMS.txt, into the updates folder (``settings.updates_dir``).

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

from . import buildinfo, settings
from .logger import get_logger
from .notifications import _parse_version

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
                  api: str = RELEASES_API) -> Release | None:
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


def download(release: Release, which: str | None = None, *,
             open_url: OpenUrl | None = None, attempts: int = 3) -> Outcome:
    which = which or buildinfo.variant()
    name = asset_name(which)
    if name is None:
        return Outcome(False, "RYOS from source does not update itself: get the "
                       "new version with git pull or a fresh RYOS-portable.zip.")
    if not isinstance(release.tag, str) or not _TAG.fullmatch(release.tag):
        return Outcome(False, f"The release tag {release.tag!r} is not a version "
                       "RYOS can use, so nothing was downloaded.")
    asset = release.assets.get(name)
    if asset is None:
        return Outcome(False, f"RYOS {release.tag} has no {name}, so there is "
                       "nothing to download for this kind of RYOS.")
    sums_asset = release.assets.get(SUMS_NAME)
    if sums_asset is None:
        return Outcome(False, f"RYOS {release.tag} has no {SUMS_NAME}, so its "
                       f"{name} cannot be checked and was not downloaded.")
    folder = settings.updates_dir(release.tag)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with _open(open_url, sums_asset.url, 30) as resp:
            sums_bytes = resp.read()
        (folder / SUMS_NAME).write_bytes(sums_bytes)
    except (OSError, http.client.HTTPException) as e:
        return Outcome(False, f"Could not download {SUMS_NAME} for RYOS "
                       f"{release.tag}: {e}")
    expected = parse_sums(sums_bytes.decode("utf-8", "replace")).get(name)
    if expected is None:
        return Outcome(False, f"{SUMS_NAME} for RYOS {release.tag} has no line "
                       f"for {name}, so it cannot be checked and was not downloaded.")
    target = folder / name
    if target.exists():
        if _sha256(target) == expected:
            return Outcome(True, f"{name} for RYOS {release.tag} is already "
                           "downloaded and checked.", target)
        target.unlink()
    part = folder / (name + ".part")
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
    if _sha256(part) != expected:
        part.unlink(missing_ok=True)
        return Outcome(False, f"{name} for RYOS {release.tag} did not match its "
                       f"line in {SUMS_NAME}, so it was deleted.")
    os.replace(part, target)
    return Outcome(True, f"Downloaded {name} for RYOS {release.tag} and checked "
                   f"it against {SUMS_NAME}.", target)
