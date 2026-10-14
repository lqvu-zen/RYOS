"""The updates module: finding this download's asset and downloading it,
checked against SHA256SUMS.txt, from a local HTTP server on 127.0.0.1 --
never GitHub. Every test points LOCALAPPDATA at a throwaway folder.
"""

from __future__ import annotations

import hashlib
import http.client
import io
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ryos import buildinfo, notifications, settings, updates  # noqa: E402

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_LOOPBACK_FLAKES = (ConnectionResetError, ConnectionAbortedError, TimeoutError)


class _Answer:
    def __init__(self, status, headers, body, cut):
        self.status = status
        self.headers = headers
        self._body = io.BytesIO(body)
        self._cut = cut

    def read(self, amount=-1):
        data = self._body.read(amount)
        if not data and self._cut is not None:
            cut, self._cut = self._cut, None
            raise cut
        return data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _OPEN(request, timeout=None):
    for attempt in range(5):
        try:
            with _OPENER.open(request, timeout=min(timeout or 5, 5)) as resp:
                try:
                    return _Answer(resp.status, resp.headers, resp.read(), None)
                except http.client.IncompleteRead as cut:
                    return _Answer(resp.status, resp.headers, cut.partial, cut)
        except urllib.error.HTTPError as refused:
            refused.close()
            raise
        except (urllib.error.URLError, *_LOOPBACK_FLAKES) as e:
            flaky = isinstance(getattr(e, "reason", e), _LOOPBACK_FLAKES)
            if not flaky or attempt == 4:
                raise
    raise AssertionError("unreachable")


def _payload(name: str) -> bytes:
    return (name.encode() + b"-") * 5000


class _Handler(BaseHTTPRequestHandler):
    wbufsize = 1 << 20

    def log_message(self, *args):
        pass

    def do_GET(self):
        srv = self.server
        srv.requests.append((self.path, self.headers.get("Range")))
        if self.path in srv.json:
            body = json.dumps(srv.json[self.path]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = srv.files.get(self.path)
        if body is None:
            self.send_error(404)
            return
        start = 0
        wanted = self.headers.get("Range")
        if wanted and srv.ranges:
            start = int(wanted.split("=")[1].split("-")[0])
            if start >= len(body):
                self.send_error(416)
                return
            self.send_response(206)
            self.send_header("Content-Range",
                             f"bytes {start}-{len(body) - 1}/{len(body)}")
        else:
            self.send_response(200)
        rest = body[start:]
        self.send_header("Content-Length", str(len(rest)))
        self.end_headers()
        if srv.cut_when.get(self.path, lambda wanted: False)(wanted):
            self.wfile.write(rest[: len(rest) // 2])
            self.close_connection = True
            return
        self.wfile.write(rest)


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.requests: list[tuple[str, str | None]] = []
        self.json: dict = {}
        self.files: dict[str, bytes] = {}
        self.cut_when: dict = {}
        self.ranges = True

    def shutdown_request(self, request):
        try:
            request.shutdown(socket.SHUT_WR)
            request.settimeout(2)
            while request.recv(4096):
                pass
        except OSError:
            pass
        self.close_request(request)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"


class _Base(unittest.TestCase):
    tag = "v9.9.9"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        env = mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.tmp)})
        env.start()
        self.addCleanup(env.stop)
        self.server = _Server()
        threading.Thread(target=self.server.serve_forever, args=(0.05,),
                         daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.publish(self.tag)

    def publish(self, tag, names=None, sums=True, wrong=(), prerelease=False):
        names = list(buildinfo.DOWNLOADS.values()) if names is None else names
        assets = []
        lines = []
        for name in names:
            body = _payload(name)
            self.server.files[f"/dl/{tag}/{name}"] = body
            digest = hashlib.sha256(b"not it" if name in wrong else body).hexdigest()
            lines.append(f"{digest}  {name}\n")
            assets.append({"name": name, "size": len(body),
                           "browser_download_url": f"{self.server.base}/dl/{tag}/{name}"})
        if sums:
            body = "".join(lines).encode()
            self.server.files[f"/dl/{tag}/SHA256SUMS.txt"] = body
            assets.append({"name": "SHA256SUMS.txt", "size": len(body),
                           "browser_download_url":
                               f"{self.server.base}/dl/{tag}/SHA256SUMS.txt"})
        release = {"tag_name": tag, "html_url": f"{self.server.base}/page/{tag}",
                   "prerelease": prerelease, "draft": False, "assets": assets}
        self.server.json["/api/releases/latest"] = release
        return release

    def fetch(self, prereleases=False):
        return updates.fetch_release(prereleases, open_url=_OPEN,
                                     api=f"{self.server.base}/api/releases")

    def download(self, which, release=None, **kw):
        return updates.download(release or self.fetch(), which, open_url=_OPEN, **kw)

    def folder(self, tag=None):
        return self.tmp / "RYOS" / "updates" / (tag or self.tag).lstrip("v")

    def seen(self):
        found: list[tuple[str, str | None]] = []
        for request in self.server.requests:
            if not found or found[-1] != request:
                found.append(request)
        return found

    def asset_requests(self):
        return [p for p, _ in self.seen() if not p.endswith("SHA256SUMS.txt")
                and p.startswith("/dl/")]


class TestUpdatesFolder(_Base):
    def test_under_localappdata(self):
        self.assertEqual(settings.updates_dir("v2.4.0"),
                         self.tmp / "RYOS" / "updates" / "2.4.0")

    def test_off_windows_falls_back_to_the_cache_folder(self):
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": "",
                                          "XDG_CACHE_HOME": str(self.tmp / "c")}):
            self.assertEqual(settings.updates_root(),
                             self.tmp / "c" / "RYOS" / "updates")
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": "", "XDG_CACHE_HOME": ""}):
            self.assertEqual(settings.updates_root(),
                             Path.home() / ".cache" / "RYOS" / "updates")


class TestFindingTheRelease(_Base):
    def test_latest_carries_its_assets(self):
        release = self.fetch()
        self.assertEqual(release.tag, self.tag)
        self.assertIn("SHA256SUMS.txt", release.assets)
        self.assertEqual(self.server.requests[-1][0], "/api/releases/latest")

    def test_each_download_picks_its_own_zip_and_portable_none(self):
        release = self.fetch()
        for which, name in ((buildinfo.WINDOWS, "RYOS-windows.zip"),
                            (buildinfo.WINDOWS_AI, "RYOS-windows-ai.zip"),
                            (buildinfo.AGENT, "RYOS-agent.zip")):
            self.assertEqual(updates.pick_asset(release, which).name, name)
        self.assertIsNone(updates.pick_asset(release, buildinfo.PORTABLE))
        self.assertIsNone(updates.asset_name(buildinfo.PORTABLE))

    def test_the_check_result_keeps_its_tag_and_url_shape(self):
        release = self.fetch()
        status, tag, _ = notifications.update_status(release.check, "1.0.0")
        self.assertEqual((status, tag), (notifications.NEWER, self.tag))

    def test_the_pre_release_channel_reads_every_release(self):
        final = self.publish("v9.9.9")
        candidate = self.publish("v9.9.10-rc2", prerelease=True)
        draft = dict(self.publish("v99.0.0"), draft=True)
        self.server.json["/api/releases"] = [final, draft, candidate]
        self.server.json["/api/releases/latest"] = final
        self.assertEqual(self.fetch(prereleases=True).tag, "v9.9.10-rc2")
        self.assertEqual(self.server.requests[-1][0], "/api/releases")
        self.assertEqual(self.fetch(prereleases=False).tag, "v9.9.9")

    def test_unreachable_or_odd_answers_give_none(self):
        self.server.json["/api/releases/latest"] = {"no": "tag"}
        self.assertIsNone(self.fetch())
        self.server.json["/api/releases"] = []
        self.assertIsNone(self.fetch(prereleases=True))
        self.assertIsNone(updates.fetch_release(
            open_url=_OPEN, api="http://127.0.0.1:9/api/releases"))


class TestDownloading(_Base):
    def test_each_download_gets_its_own_zip_verified(self):
        for which in (buildinfo.WINDOWS, buildinfo.WINDOWS_AI, buildinfo.AGENT):
            name = buildinfo.DOWNLOADS[which]
            self.server.requests.clear()
            outcome = self.download(which)
            self.assertTrue(outcome.ok, outcome.message)
            self.assertEqual(outcome.path, self.folder() / name)
            self.assertEqual(outcome.path.read_bytes(), _payload(name))
            self.assertTrue((self.folder() / "SHA256SUMS.txt").exists())
            self.assertEqual(self.asset_requests(), [f"/dl/{self.tag}/{name}"])
            self.assertFalse((self.folder() / (name + ".part")).exists())

    def test_portable_never_self_updates(self):
        self.server.requests.clear()
        outcome = self.download(buildinfo.PORTABLE)
        self.assertFalse(outcome.ok)
        self.assertIn("does not update itself", outcome.message)
        self.assertEqual(self.server.requests[-1][0], "/api/releases/latest")
        self.assertFalse((self.tmp / "RYOS").exists())

    def test_a_wrong_hash_is_rejected_and_deleted(self):
        self.publish(self.tag, wrong=("RYOS-windows.zip",))
        outcome = self.download(buildinfo.WINDOWS)
        self.assertFalse(outcome.ok)
        self.assertIn("did not match", outcome.message)
        self.assertIn("deleted", outcome.message)
        leftovers = [p.name for p in self.folder().iterdir()]
        self.assertEqual(leftovers, ["SHA256SUMS.txt"])

    def test_a_tampered_finished_file_is_replaced(self):
        self.assertTrue(self.download(buildinfo.WINDOWS).ok)
        (self.folder() / "RYOS-windows.zip").write_bytes(b"tampered")
        outcome = self.download(buildinfo.WINDOWS)
        self.assertTrue(outcome.ok, outcome.message)
        self.assertEqual(outcome.path.read_bytes(), _payload("RYOS-windows.zip"))

    def test_a_cut_off_download_resumes_and_ends_verified(self):
        path = f"/dl/{self.tag}/RYOS-windows.zip"
        self.server.cut_when[path] = lambda wanted: wanted is None
        outcome = self.download(buildinfo.WINDOWS)
        self.assertTrue(outcome.ok, outcome.message)
        ranges = [r for p, r in self.seen() if p == path]
        self.assertEqual(len(ranges), 2)
        self.assertIsNone(ranges[0])
        self.assertTrue(ranges[1].startswith("bytes="))
        self.assertNotEqual(ranges[1], "bytes=0-")

    def test_a_cut_off_download_restarts_when_the_server_cannot_resume(self):
        path = f"/dl/{self.tag}/RYOS-agent.zip"
        self.server.cut_when[path] = lambda wanted: wanted is None
        self.server.ranges = False
        outcome = self.download(buildinfo.AGENT)
        self.assertTrue(outcome.ok, outcome.message)
        self.assertEqual(outcome.path.read_bytes(), _payload("RYOS-agent.zip"))

    def test_a_download_cut_off_every_time_carries_on_next_time(self):
        path = f"/dl/{self.tag}/RYOS-windows-ai.zip"
        three_quarters = len(_payload("RYOS-windows-ai.zip")) * 3 // 4
        self.server.cut_when[path] = (
            lambda wanted: int((wanted or "bytes=0-")[6:-1]) < three_quarters)
        outcome = self.download(buildinfo.WINDOWS_AI, attempts=2)
        self.assertFalse(outcome.ok)
        self.assertIn("cut off", outcome.message)
        part = self.folder() / "RYOS-windows-ai.zip.part"
        self.assertTrue(part.exists())
        outcome = self.download(buildinfo.WINDOWS_AI)
        self.assertTrue(outcome.ok, outcome.message)
        self.assertFalse(part.exists())
        self.assertEqual([r for p, r in self.seen() if p == path][-1],
                         f"bytes={three_quarters}-")

    def test_a_stale_complete_part_is_checked_without_downloading(self):
        name = "RYOS-windows.zip"
        self.folder().mkdir(parents=True)
        (self.folder() / (name + ".part")).write_bytes(_payload(name))
        self.server.requests.clear()
        outcome = self.download(buildinfo.WINDOWS, release=self.fetch())
        self.assertTrue(outcome.ok, outcome.message)
        self.assertEqual(self.asset_requests(), [])

    def test_a_missing_asset_is_refused_with_words(self):
        self.publish(self.tag, names=["RYOS-windows.zip"])
        outcome = self.download(buildinfo.AGENT)
        self.assertFalse(outcome.ok)
        self.assertIn("has no RYOS-agent.zip", outcome.message)
        self.assertEqual(self.asset_requests(), [])

    def test_a_missing_sums_is_refused_with_words(self):
        self.publish(self.tag, sums=False)
        outcome = self.download(buildinfo.WINDOWS)
        self.assertFalse(outcome.ok)
        self.assertIn("has no SHA256SUMS.txt", outcome.message)
        self.assertEqual(self.asset_requests(), [])

    def test_sums_without_this_zip_is_refused_with_words(self):
        release = self.fetch()
        self.server.files[f"/dl/{self.tag}/SHA256SUMS.txt"] = b"0" * 64 + b"  other.zip\n"
        outcome = self.download(buildinfo.WINDOWS, release=release)
        self.assertFalse(outcome.ok)
        self.assertIn("no line for RYOS-windows.zip", outcome.message)
        self.assertFalse((self.folder() / "RYOS-windows.zip").exists())

    def test_an_unreachable_asset_is_refused_with_words(self):
        release = self.fetch()
        del self.server.files[f"/dl/{self.tag}/RYOS-windows.zip"]
        outcome = self.download(buildinfo.WINDOWS, release=release)
        self.assertFalse(outcome.ok)
        self.assertIn("Could not download RYOS-windows.zip", outcome.message)

    def test_a_tag_that_is_not_a_version_is_refused(self):
        release = updates.Release("../../evil", "x", False, self.fetch().assets)
        outcome = self.download(buildinfo.WINDOWS, release=release)
        self.assertFalse(outcome.ok)
        self.assertIn("not a version", outcome.message)
        self.assertFalse((self.tmp / "RYOS").exists())

    def test_sums_lines_parse_like_sha256sum(self):
        digest = "a" * 64
        self.assertEqual(updates.parse_sums(f"{digest}  RYOS-windows.zip\n"
                                            f"{digest.upper()} *RYOS-agent.zip\njunk\n"),
                         {"RYOS-windows.zip": digest, "RYOS-agent.zip": digest})


if __name__ == "__main__":
    unittest.main()
