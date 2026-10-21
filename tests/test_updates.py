"""The updates module: finding this download's asset and downloading it,
checked against SHA256SUMS.txt, from a local HTTP server on 127.0.0.1 --
never GitHub. Every test points LOCALAPPDATA at a throwaway folder.
"""

from __future__ import annotations

import contextlib
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
import zipfile
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from ed25519_signer import (OTHER_PUBLIC, OTHER_SEED, TEST_PUBLIC,  # noqa: E402
                            TEST_SEED, sig_file, sign)
from ryos import buildinfo, ed25519, notifications, settings, signature, updates  # noqa: E402

try:
    import cryptography  # noqa: F401
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False

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


def _STREAM(request, timeout=None):
    for attempt in range(5):
        try:
            return _OPENER.open(request, timeout=min(timeout or 5, 5))
        except urllib.error.HTTPError:
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

    def publish(self, tag, names=None, sums=True, wrong=(), prerelease=False,
                signed=True, signed_version=None, seed=TEST_SEED):
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
        self.signing = (tag, signed_version, seed)
        if sums:
            body = "".join(lines).encode()
            self.server.files[f"/dl/{tag}/SHA256SUMS.txt"] = body
            assets.append({"name": "SHA256SUMS.txt", "size": len(body),
                           "browser_download_url":
                               f"{self.server.base}/dl/{tag}/SHA256SUMS.txt"})
            if signed:
                sig = self.sign_sums(body)
                assets.append({"name": signature.SIG_NAME, "size": len(sig),
                               "browser_download_url":
                                   f"{self.server.base}/dl/{tag}/{signature.SIG_NAME}"})
        release = {"tag_name": tag, "html_url": f"{self.server.base}/page/{tag}",
                   "prerelease": prerelease, "draft": False, "assets": assets}
        self.server.json["/api/releases/latest"] = release
        return release

    def sign_sums(self, body):
        tag, signed_version, seed = self.signing
        sig = sig_file(seed, signed_version or tag.lstrip("v"), body)
        self.server.files[f"/dl/{tag}/{signature.SIG_NAME}"] = sig
        return sig

    def serve_sums(self, body):
        tag = self.signing[0]
        self.server.files[f"/dl/{tag}/SHA256SUMS.txt"] = body
        self.sign_sums(body)

    def fetch(self, prereleases=False):
        return updates.fetch_release(prereleases, open_url=_OPEN,
                                     api=f"{self.server.base}/api/releases")

    def download(self, which, release=None, **kw):
        kw.setdefault("key", TEST_PUBLIC)
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
        return [p for p, _ in self.seen()
                if not p.endswith(("SHA256SUMS.txt", signature.SIG_NAME))
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


class TestTestSource(_Base):
    """Only release_check's test build (TEST_UPDATES) reads releases from
    RYOS_TEST_RELEASES_API, and only from 127.0.0.1 (UP-30)."""

    marked = SimpleNamespace(VARIANT="agent", RELEASE_KEY=TEST_PUBLIC.hex(),
                             TEST_UPDATES=True)
    unmarked = SimpleNamespace(VARIANT="agent", RELEASE_KEY=TEST_PUBLIC.hex())

    def build(self, fake, env):
        return mock.patch.dict(sys.modules, {"ryos._build_info": fake}), \
            mock.patch.dict(os.environ, {buildinfo.TEST_RELEASES_ENV: env})

    def recorded(self, fake, env):
        seen = []

        def open_url(request, timeout=None):
            seen.append(request.full_url)
            raise urllib.error.URLError("not here")
        modules, environ = self.build(fake, env)
        with modules, environ:
            self.assertIsNone(updates.fetch_release(open_url=open_url))
        return seen

    def test_fetch_uses_the_test_source_only_in_a_marked_build(self):
        env = f"{self.server.base}/api/releases"
        self.assertEqual(self.recorded(self.unmarked, env),
                         [updates.RELEASES_API + "/latest"])
        self.assertEqual(self.recorded(self.marked, env), [env + "/latest"])
        self.assertEqual(self.recorded(self.marked, "https://example.com/releases"),
                         [updates.RELEASES_API + "/latest"])
        modules, environ = self.build(self.marked, env)
        with modules, environ, mock.patch.object(urllib.request, "urlopen", _OPEN):
            release = updates.fetch_release()
        self.assertEqual(release.tag, self.tag)
        self.assertEqual(self.server.requests[-1][0], "/api/releases/latest")

    def test_the_version_check_reads_the_same_source(self):
        from ryos import cli
        env = f"{self.server.base}/api/releases"
        cases = ((self.unmarked, False, updates.RELEASES_API + "/latest"),
                 (self.marked, False, env + "/latest"),
                 (self.marked, True, env))
        for fake, on, want in cases:
            seen = []

            def urlopen(request, timeout=None):
                seen.append(request.full_url)
                raise urllib.error.URLError("not here")
            modules, environ = self.build(fake, env)
            with self.subTest(fake=fake, on=on), modules, environ, \
                    mock.patch.object(urllib.request, "urlopen", urlopen), \
                    contextlib.redirect_stdout(io.StringIO()):
                cli.main(["version", "--check"],
                         settings={"offer_release_candidates": on})
            self.assertEqual(seen, [want])


class TestReleaseCandidates(_Base):
    ALL = (buildinfo.WINDOWS, buildinfo.WINDOWS_AI, buildinfo.AGENT)

    def channel(self, *tags):
        releases = [self.publish(tag, prerelease="-rc" in tag) for tag in tags]
        finals = [r for r, tag in zip(releases, tags) if "-rc" not in tag]
        self.server.json["/api/releases"] = releases
        self.server.json["/api/releases/latest"] = finals[0]
        self.server.requests.clear()

    def asked_all(self):
        return any(p == "/api/releases" for p, _ in self.server.requests)

    def test_rc_to_the_next_rc(self):
        self.channel("v9.9.10-rc2", "v9.9.10-rc1", "v9.9.9")
        release = self.fetch(prereleases=True)
        self.assertEqual(release.tag, "v9.9.10-rc2")
        self.assertEqual(notifications.update_status(release.check, "9.9.10-rc1")[0],
                         notifications.NEWER)
        for which in self.ALL:
            with self.subTest(which=which):
                self.assertTrue(updates.wants_download(
                    release, "9.9.10-rc1", allowed=True, which=which))
                outcome = self.download(which, release, current="9.9.10-rc1")
                self.assertTrue(outcome.ok, outcome.message)
                self.assertEqual(updates.downloaded(
                    "v9.9.10-rc2", which, key=TEST_PUBLIC), outcome.path)
        self.server.requests.clear()
        off = self.fetch(prereleases=False)
        self.assertEqual(off.tag, "v9.9.9")
        self.assertEqual(notifications.update_status(off.check, "9.9.10-rc1")[0],
                         notifications.CURRENT)
        self.assertFalse(self.asked_all())

    def test_rc_to_its_final(self):
        self.channel("v9.9.10", "v9.9.10-rc2", "v9.9.9")
        for on in (True, False):
            with self.subTest(on=on):
                release = self.fetch(prereleases=on)
                self.assertEqual(release.tag, "v9.9.10")
                self.assertEqual(
                    notifications.update_status(release.check, "9.9.10-rc2")[0],
                    notifications.NEWER)
                self.assertTrue(updates.wants_download(
                    release, "9.9.10-rc2", allowed=True, which=buildinfo.WINDOWS))

    def test_a_final_to_the_next_rc1(self):
        self.channel("v9.9.11-rc1", "v9.9.10")
        release = self.fetch(prereleases=True)
        self.assertEqual(release.tag, "v9.9.11-rc1")
        self.assertTrue(updates.wants_download(
            release, "9.9.10", allowed=True, which=buildinfo.WINDOWS))
        outcome = self.download(buildinfo.WINDOWS, release, current="9.9.10")
        self.assertTrue(outcome.ok, outcome.message)
        self.server.requests.clear()
        off = self.fetch(prereleases=False)
        self.assertEqual(off.tag, "v9.9.10")
        self.assertEqual(notifications.update_status(off.check, "9.9.10")[0],
                         notifications.CURRENT)
        self.assertFalse(self.asked_all())

    def test_a_release_is_never_replaced_by_an_older_pre_release(self):
        self.channel("v9.9.10-rc3", "v9.9.9")
        self.server.json["/api/releases"] = [
            self.publish("v9.9.10-rc3", prerelease=True), self.publish("v9.9.9")]
        release = self.fetch(prereleases=True)
        self.assertEqual(release.tag, "v9.9.10-rc3")
        self.assertEqual(notifications.update_status(release.check, "9.9.10")[0],
                         notifications.CURRENT)
        self.assertFalse(updates.wants_download(
            release, "9.9.10", allowed=True, which=buildinfo.WINDOWS))
        outcome = self.download(buildinfo.WINDOWS, release, current="9.9.10")
        self.assertFalse(outcome.ok)

    def test_the_command_line_follows_the_option(self):
        from ryos import cli, selfupdate, swap
        packed = io.BytesIO()
        with zipfile.ZipFile(packed, "w") as z:
            z.writestr("RYOS.exe", b"new")
            z.writestr("ryos-cli.exe", b"new cli")
        zip_bytes = packed.getvalue()
        here = sys.modules[__name__]
        with mock.patch.object(here, "_payload", lambda name: (
                zip_bytes if name == "RYOS-windows.zip" else name.encode() * 10)):
            self.channel("v9.9.10-rc2", "v9.9.10-rc1", "v9.9.9")
        fake = SimpleNamespace(VARIANT="windows", RELEASE_KEY=TEST_PUBLIC.hex(),
                               TEST_UPDATES=True)
        env = {buildinfo.TEST_RELEASES_ENV: f"{self.server.base}/api/releases"}
        install = self.tmp / "apps" / "RYOS"
        install.mkdir(parents=True)
        (install / "RYOS.exe").write_bytes(b"old")
        spawned: list = []
        updater = selfupdate.Updater(
            install=install, which="windows", running_from=lambda _f: [],
            write_problem=lambda _i: None,
            staged=lambda tag: updates.downloaded(tag),
            spawn=lambda argv, cwd: spawned.append(list(argv)),
            effects=swap.Effects(wait_for_exit=lambda p, t: True,
                                 spawn=lambda a, c: None, sleep=lambda s: None),
            pid=4242)

        def check(settings):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cli.main(["version", "--check"], settings=settings)
            return out.getvalue()
        with mock.patch.dict(sys.modules, {"ryos._build_info": fake}), \
                mock.patch.dict(os.environ, env), \
                mock.patch.object(urllib.request, "urlopen", _OPEN), \
                mock.patch.object(cli, "__version__", "9.9.10-rc1"), \
                mock.patch.object(updates, "__version__", "9.9.10-rc1"):
            self.assertIn("9.9.10-rc2",
                          check({"offer_release_candidates": True}))
            self.assertIn("Up to date", check({}))
            out, err = io.StringIO(), io.StringIO()
            code = cli.main(["update", "--yes"], settings={"offer_release_candidates": True},
                            out=out, err=err, updater=updater)
        self.assertEqual(code, cli.EXIT_OK, err.getvalue())
        self.assertEqual(len(spawned), 1)
        self.assertIn("v9.9.10-rc2", spawned[0])
        self.assertIsNotNone(updates.downloaded("v9.9.10-rc2", buildinfo.WINDOWS,
                                                key=TEST_PUBLIC))


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
        leftovers = sorted(p.name for p in self.folder().iterdir())
        self.assertEqual(leftovers, ["SHA256SUMS.txt", "SHA256SUMS.txt.sig"])

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
        self.serve_sums(b"0" * 64 + b"  other.zip\n")
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

    def test_a_cut_off_download_resumes_with_the_real_streaming_opener(self):
        path = f"/dl/{self.tag}/RYOS-windows.zip"
        self.server.cut_when[path] = lambda wanted: wanted is None
        outcome = updates.download(self.fetch(), buildinfo.WINDOWS, open_url=_STREAM,
                                   key=TEST_PUBLIC)
        self.assertTrue(outcome.ok, outcome.message)
        self.assertEqual(outcome.path.read_bytes(), _payload("RYOS-windows.zip"))
        ranges = [r for p, r in self.seen() if p == path]
        self.assertIsNone(ranges[0])
        self.assertTrue(ranges[-1].startswith("bytes="))
        self.assertNotEqual(ranges[-1], "bytes=0-")

    def test_a_hash_check_that_cannot_read_is_refused_with_words(self):
        release = self.fetch()
        with mock.patch.object(updates, "_sha256",
                               side_effect=PermissionError("locked")):
            outcome = self.download(buildinfo.WINDOWS, release=release)
        self.assertFalse(outcome.ok)
        self.assertIn("Could not check RYOS-windows.zip", outcome.message)
        self.assertIn("locked", outcome.message)

    def test_a_rename_that_fails_keeps_the_checked_part_for_next_time(self):
        name = "RYOS-windows.zip"
        release = self.fetch()
        with mock.patch.object(updates.os, "replace",
                               side_effect=PermissionError("in use")):
            outcome = self.download(buildinfo.WINDOWS, release=release)
        self.assertFalse(outcome.ok)
        self.assertIn(f"Could not put {name}", outcome.message)
        self.assertIn("tried again next time", outcome.message)
        self.assertTrue((self.folder() / (name + ".part")).exists())
        self.server.requests.clear()
        outcome = self.download(buildinfo.WINDOWS, release=release)
        self.assertTrue(outcome.ok, outcome.message)
        self.assertEqual(self.asset_requests(), [])
        self.assertEqual(outcome.path.read_bytes(), _payload(name))

    def test_sums_lines_parse_like_sha256sum(self):
        digest = "a" * 64
        self.assertEqual(updates.parse_sums(f"{digest}  RYOS-windows.zip\n"
                                            f"{digest.upper()} *RYOS-agent.zip\njunk\n"),
                         {"RYOS-windows.zip": digest, "RYOS-agent.zip": digest})

    def refused(self, *words, **kw):
        self.server.requests.clear()
        outcome = self.download(buildinfo.WINDOWS, **kw)
        self.assertFalse(outcome.ok)
        for said in words:
            self.assertIn(said, outcome.message)
        self.assertEqual(self.asset_requests(), [])
        self.assertFalse((self.folder() / "RYOS-windows.zip").exists())
        self.assertFalse((self.folder() / "RYOS-windows.zip.part").exists())
        return outcome

    def test_a_missing_signature_downloads_nothing(self):
        self.publish(self.tag, signed=False)
        self.refused("has no SHA256SUMS.txt.sig", "not downloaded")
        self.assertFalse(self.folder().exists())

    def test_a_tampered_sums_downloads_nothing(self):
        release = self.fetch()
        path = f"/dl/{self.tag}/SHA256SUMS.txt"
        self.server.files[path] = self.server.files[path].replace(b"a", b"b", 1)
        self.refused("was not downloaded", "has been changed", release=release)
        self.assertFalse(self.folder().exists())

    def test_a_wrong_key_downloads_nothing(self):
        self.refused("different key", key=OTHER_PUBLIC)
        self.publish(self.tag, seed=OTHER_SEED)
        self.refused("different key")
        self.assertFalse(self.folder().exists())

    def test_a_signature_for_an_older_version_downloads_nothing(self):
        self.publish("v9.9.9", signed_version="1.0.0")
        self.refused("for RYOS 1.0.0, not v9.9.9")
        self.assertFalse(self.folder().exists())

    def test_an_older_release_than_this_one_downloads_nothing(self):
        self.publish("v1.0.0")
        self.refused("RYOS 1.0.0, older than this RYOS (2.0.0)", current="2.0.0")
        self.assertFalse(self.folder("v1.0.0").exists())

    def test_without_a_release_key_nothing_is_downloaded(self):
        self.server.requests.clear()
        with mock.patch.dict(sys.modules, {"ryos._build_info": None}):
            outcome = updates.download(self.fetch(), buildinfo.WINDOWS, open_url=_OPEN)
        self.assertFalse(outcome.ok)
        self.assertIn("carries no release key", outcome.message)
        self.assertEqual([p for p, _ in self.seen() if p.startswith("/dl/")], [])
        self.assertFalse((self.tmp / "RYOS").exists())
        build = SimpleNamespace(VARIANT="windows")
        with mock.patch.dict(sys.modules, {"ryos._build_info": build}):
            outcome = updates.download(self.fetch(), open_url=_OPEN)
        self.assertIn("carries no release key", outcome.message)
        build.RELEASE_KEY = TEST_PUBLIC.hex()
        with mock.patch.dict(sys.modules, {"ryos._build_info": build}):
            outcome = updates.download(self.fetch(), open_url=_OPEN)
        self.assertTrue(outcome.ok, outcome.message)

    def test_unverified_sums_are_never_staged(self):
        for kw in ({"signed": False}, {"seed": OTHER_SEED}, {"signed_version": "9.9.8"}):
            self.publish(self.tag, **kw)
            self.refused()
            self.assertFalse(self.folder().exists(), kw)
        self.publish(self.tag)
        self.assertTrue(self.download(buildinfo.WINDOWS).ok)
        staged = self.folder() / "SHA256SUMS.txt"
        good = staged.read_bytes()
        release = self.fetch()
        path = f"/dl/{self.tag}/SHA256SUMS.txt"
        self.server.files[path] = good + b"0" * 64 + b"  extra.zip\n"
        outcome = self.download(buildinfo.WINDOWS, release=release)
        self.assertFalse(outcome.ok)
        self.assertEqual(staged.read_bytes(), good)


class TestWhenToDownload(unittest.TestCase):
    release = updates.Release("v9.9.9", "https://example.invalid/r", False, {})

    def wants(self, result, current="1.0.0", allowed=True, which=buildinfo.WINDOWS):
        return updates.wants_download(result, current, allowed=allowed, which=which)

    def test_a_newer_release_of_a_windows_download_is_wanted(self):
        for which in (buildinfo.WINDOWS, buildinfo.WINDOWS_AI, buildinfo.AGENT):
            self.assertTrue(self.wants(self.release, which=which))

    def test_with_the_setting_off_nothing_is_wanted(self):
        self.assertFalse(self.wants(self.release, allowed=False))

    def test_from_source_nothing_is_wanted(self):
        self.assertFalse(self.wants(self.release, which=buildinfo.PORTABLE))

    def test_the_same_or_an_older_release_is_not_wanted(self):
        self.assertFalse(self.wants(self.release, current="9.9.9"))
        self.assertFalse(self.wants(self.release, current="10.0.0"))

    def test_a_bare_check_or_nothing_is_not_wanted(self):
        self.assertFalse(self.wants(self.release.check))
        self.assertFalse(self.wants(None))

    def test_check_of_gives_the_tag_and_url(self):
        self.assertEqual(updates.check_of(self.release),
                         ("v9.9.9", "https://example.invalid/r"))
        self.assertEqual(updates.check_of(("v1", "u")), ("v1", "u"))
        self.assertIsNone(updates.check_of(None))


class TestDownloaded(_Base):
    def staged(self, tag=None, which=buildinfo.WINDOWS, key=TEST_PUBLIC):
        return updates.downloaded(tag or self.tag, which, key=key)

    def test_found_after_a_download(self):
        outcome = self.download(buildinfo.WINDOWS)
        self.assertTrue(outcome.ok, outcome.message)
        self.assertEqual(self.staged(), outcome.path)

    def test_nothing_before_a_download(self):
        self.assertIsNone(self.staged())

    def test_a_tampered_zip_is_not_counted(self):
        self.assertTrue(self.download(buildinfo.WINDOWS).ok)
        (self.folder() / "RYOS-windows.zip").write_bytes(b"tampered")
        self.assertIsNone(self.staged())

    def test_a_tag_that_is_not_a_version_is_none(self):
        self.assertIsNone(self.staged("../../evil"))

    def test_from_source_is_none(self):
        self.assertTrue(self.download(buildinfo.WINDOWS).ok)
        self.assertIsNone(self.staged(which=buildinfo.PORTABLE))

    def test_reads_no_network(self):
        self.assertTrue(self.download(buildinfo.WINDOWS).ok)
        self.server.requests.clear()
        with mock.patch.object(updates, "_open",
                               side_effect=AssertionError("network")):
            self.assertIsNotNone(self.staged())
        self.assertEqual(self.server.requests, [])

    def test_a_tampered_staged_signature_is_not_counted(self):
        self.assertTrue(self.download(buildinfo.WINDOWS).ok)
        sig_path = self.folder() / signature.SIG_NAME
        good = sig_path.read_bytes()
        sig_path.write_bytes(sig_file(OTHER_SEED, "9.9.9",
                                      (self.folder() / "SHA256SUMS.txt").read_bytes()))
        self.assertIsNone(self.staged())
        sig_path.write_bytes(good.replace(b"version 9.9.9", b"version 9.9.8"))
        self.assertIsNone(self.staged())
        sig_path.unlink()
        self.assertIsNone(self.staged())
        sig_path.write_bytes(good)
        sums = self.folder() / "SHA256SUMS.txt"
        sums.write_bytes(sums.read_bytes() + b"0" * 64 + b"  extra.zip\n")
        self.assertIsNone(self.staged())

    def test_a_build_without_a_key_counts_nothing(self):
        self.assertTrue(self.download(buildinfo.WINDOWS).ok)
        with mock.patch.dict(sys.modules, {"ryos._build_info": None}):
            self.assertIsNone(updates.downloaded(self.tag, buildinfo.WINDOWS))
        self.assertIsNotNone(self.staged())


class TestEd25519(unittest.TestCase):
    VECTORS = (
        ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
         "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
         "",
         "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555"
         "fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
        ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
         "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
         "72",
         "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
         "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
        ("c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
         "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
         "af82",
         "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac"
         "18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"),
        ("833fe62409237b9d62ec77587520911e9a759cec1d19755b7da901b96dca3d42",
         "ec172b93ad5e563bf4932c70e1245034c35467ef2efd4d64ebf819683467e2bf",
         "ddaf35a193617abacc417349ae20413112e6fa4e89a97ea20a9eeee64b55d39a"
         "2192992a274fc1a836ba3c23a3feebbd454d4423643ce80e2a9ac94fa54ca49f",
         "dc2a4459e7369633a52b1bf277839a00201009a3efbf3ecb69bea2186c26b589"
         "09351fc9ac90b3ecfdfbc7c66431e0303dca179c138ac17ad9bef1177331a704"),
    )

    def vectors(self):
        return [tuple(bytes.fromhex(x) for x in v) for v in self.VECTORS]

    def test_rfc8032_vectors_verify(self):
        self.assertEqual(self.vectors()[3][2], hashlib.sha512(b"abc").digest())
        for _seed, public, message, sig in self.vectors():
            self.assertTrue(ed25519.verify(public, message, sig), public.hex())

    def test_the_test_signer_reproduces_the_rfc8032_signatures(self):
        for seed, public, message, sig in self.vectors():
            self.assertEqual(sign(seed, message), (public, sig))
        self.assertEqual(sign(TEST_SEED, b"")[0], TEST_PUBLIC)
        self.assertEqual(sign(OTHER_SEED, b"")[0], OTHER_PUBLIC)

    def test_a_changed_message_signature_or_key_is_refused(self):
        _seed, public, message, sig = self.vectors()[2]
        self.assertFalse(ed25519.verify(public, message + b"x", sig))
        self.assertFalse(ed25519.verify(public, b"\x00\x82", sig))
        for i in (0, 31, 32, 63):
            bad = bytearray(sig)
            bad[i] ^= 1
            self.assertFalse(ed25519.verify(public, message, bytes(bad)), i)
        self.assertFalse(ed25519.verify(OTHER_PUBLIC, message, sig))

    def test_s_at_or_above_the_group_order_is_refused(self):
        _seed, public, message, sig = self.vectors()[1]
        s = int.from_bytes(sig[32:], "little")
        for big in (s + ed25519._L, ed25519._L, 2 ** 256 - 1):
            if big < 2 ** 256:
                self.assertFalse(ed25519.verify(
                    public, message, sig[:32] + big.to_bytes(32, "little")), big)

    def test_wrong_lengths_and_points_off_the_curve_are_refused(self):
        _seed, public, message, sig = self.vectors()[0]
        self.assertFalse(ed25519.verify(public[:31], message, sig))
        self.assertFalse(ed25519.verify(public + b"\0", message, sig))
        self.assertFalse(ed25519.verify(public, message, sig[:63]))
        self.assertFalse(ed25519.verify(public, message, sig + b"\0"))
        self.assertFalse(ed25519.verify("not bytes", message, sig))  # type: ignore[arg-type]
        self.assertFalse(ed25519.verify(public, None, sig))  # type: ignore[arg-type]
        non_canonical = (ed25519._P + 1).to_bytes(32, "little")
        self.assertFalse(ed25519.verify(non_canonical, message, sig))
        self.assertFalse(ed25519.verify(public, message, non_canonical + sig[32:]))
        off_curve = next(y for y in range(2, 100)
                         if ed25519._recover_x(y, 0) is None).to_bytes(32, "little")
        self.assertFalse(ed25519.verify(off_curve, message, sig))
        self.assertFalse(ed25519.verify(public, message, off_curve + sig[32:]))
        odd_zero = (1 | (1 << 255)).to_bytes(32, "little")
        self.assertFalse(ed25519.verify(odd_zero, message, sig))

    @unittest.skipUnless(HAS_CRYPTOGRAPHY, "needs the cryptography library")
    def test_matches_the_cryptography_library(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        for n in range(20):
            private = Ed25519PrivateKey.generate()
            public = private.public_key().public_bytes(serialization.Encoding.Raw,
                                                       serialization.PublicFormat.Raw)
            message = os.urandom(n * 7)
            sig = private.sign(message)
            self.assertTrue(ed25519.verify(public, message, sig))
            self.assertFalse(ed25519.verify(public, message + b"!", sig))

    def test_the_core_holds_no_signing_code_and_never_imports_cryptography(self):
        self.assertEqual([n for n in vars(ed25519) if "sign" in n.lower()], [])
        for path in (ROOT / "ryos").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                stripped = line.strip()
                self.assertFalse(stripped.startswith(("import cryptography",
                                                      "from cryptography")),
                                 f"{path}: {line}")


class TestReleaseSignature(unittest.TestCase):
    SUMS = b"a" * 64 + b"  RYOS-windows.zip\n" + b"b" * 64 + b"  RYOS-agent.zip\n"

    def check(self, sig, sums=None, key=TEST_PUBLIC, **kw):
        return signature.check(self.SUMS if sums is None else sums, sig, key, **kw)

    def test_the_signed_message_bytes(self):
        self.assertEqual(signature.signed_message("2.4.0", b"x  y\r\n"),
                         b"RYOS SHA256SUMS.txt signature 1\nversion 2.4.0\nx  y\r\n")
        self.assertEqual(signature.version_of("v2.4.0-rc1"), "2.4.0-rc1")
        self.assertEqual(signature.version_of("2.4.0"), "2.4.0")
        for bad in ("vv2.4.0", "2.4.0 ", "2.4.١", "", "v", "../1", None):
            self.assertIsNone(signature.version_of(bad), bad)
        for bad in ("v2.4.0", "2.4.0\n", "x"):
            with self.assertRaises(ValueError):
                signature.signed_message(bad, b"")

    def test_the_signature_file_round_trips(self):
        sig = bytes(range(64))
        data = signature.signature_file("2.4.0", TEST_PUBLIC, sig)
        self.assertEqual(data, (f"RYOS signature 1\nversion 2.4.0\nkey {TEST_PUBLIC.hex()}\n"
                                f"signature {sig.hex()}\n").encode())
        self.assertEqual(signature.parse(data),
                         signature.Signature("2.4.0", TEST_PUBLIC, sig))
        self.assertEqual(signature.parse(data.replace(b"\n", b"\r\n")),
                         signature.Signature("2.4.0", TEST_PUBLIC, sig))

    def test_a_good_signature_is_accepted_and_names_its_version(self):
        checked = self.check(sig_file(TEST_SEED, "2.4.0", self.SUMS), version="v2.4.0",
                             current="2.3.1")
        self.assertTrue(checked.ok, checked.message)
        self.assertEqual(checked.version, "2.4.0")

    def test_a_missing_signature_is_refused(self):
        checked = self.check(None)
        self.assertFalse(checked.ok)
        self.assertIn("there is no SHA256SUMS.txt.sig", checked.message)

    def test_a_tampered_sums_is_refused(self):
        sig = sig_file(TEST_SEED, "2.4.0", self.SUMS)
        for sums in (self.SUMS.replace(b"a", b"c", 1), self.SUMS + b"\n",
                     self.SUMS.replace(b"\n", b"\r\n")):
            checked = self.check(sig, sums=sums)
            self.assertFalse(checked.ok)
            self.assertIn("has been changed", checked.message)

    def test_a_wrong_key_is_refused(self):
        checked = self.check(sig_file(OTHER_SEED, "2.4.0", self.SUMS))
        self.assertFalse(checked.ok)
        self.assertIn("different key", checked.message)
        good = sig_file(OTHER_SEED, "2.4.0", self.SUMS)
        lied = good.replace(OTHER_PUBLIC.hex().encode(), TEST_PUBLIC.hex().encode())
        checked = self.check(lied)
        self.assertFalse(checked.ok)
        self.assertIn("has been changed", checked.message)

    def test_a_malformed_signature_file_is_refused(self):
        good = sig_file(TEST_SEED, "2.4.0", self.SUMS)
        lines = good.split(b"\n")
        for bad in (b"", b"junk", good.replace(b"RYOS signature 1", b"RYOS signature 2"),
                    b"\n".join([lines[0], lines[2], lines[1], lines[3]]) + b"\n",
                    good + b"extra\n", good.replace(b"key ", b"key  "),
                    good[:-1] + b"ab\n",
                    good[:-3] + b"\n", good.upper(),
                    good.replace(b"2.4.0", "2.4.é".encode()),
                    good + b" " * 5000):
            checked = self.check(bad)
            self.assertFalse(checked.ok, bad)
            self.assertIn("not a signature file", checked.message)

    def test_a_signature_for_another_version_is_refused(self):
        checked = self.check(sig_file(TEST_SEED, "1.0.0", self.SUMS), version="v9.9.9")
        self.assertFalse(checked.ok)
        self.assertIn("for RYOS 1.0.0, not v9.9.9", checked.message)

    def test_a_signed_older_version_is_refused(self):
        for older in ("2.3.1", "2.4.0-rc1"):
            checked = self.check(sig_file(TEST_SEED, older, self.SUMS), current="2.4.0")
            self.assertFalse(checked.ok, older)
            self.assertIn(f"RYOS {older}, older than this RYOS (2.4.0)", checked.message)

    def test_a_signed_same_or_newer_version_is_accepted(self):
        for version in ("2.4.0", "2.4.1", "3.0.0-rc1"):
            checked = self.check(sig_file(TEST_SEED, version, self.SUMS), current="2.4.0")
            self.assertTrue(checked.ok, version)


class TestVerifyZip(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.zip = self.tmp / "RYOS-windows.zip"
        self.zip.write_bytes(b"the new RYOS")
        self.sums = (hashlib.sha256(b"the new RYOS").hexdigest().encode()
                     + b"  RYOS-windows.zip\n")
        self.write(self.sums)

    def write(self, sums, version="9.9.9"):
        (self.tmp / "SHA256SUMS.txt").write_bytes(sums)
        (self.tmp / signature.SIG_NAME).write_bytes(sig_file(TEST_SEED, version, sums))

    def verify(self):
        return updates.verify_zip(self.zip, key=TEST_PUBLIC, current="2.0.0")

    def test_a_good_zip_is_verified(self):
        outcome = self.verify()
        self.assertTrue(outcome.ok, outcome.message)
        self.assertEqual(outcome.message,
                         "RYOS-windows.zip is RYOS 9.9.9: signed with this RYOS's "
                         "release key and matching SHA256SUMS.txt.")

    def test_a_tampered_zip_is_refused(self):
        self.zip.write_bytes(b"the new RYOS, changed")
        outcome = self.verify()
        self.assertFalse(outcome.ok)
        self.assertIn("does not match its line in SHA256SUMS.txt", outcome.message)

    def test_a_zip_with_no_line_is_refused(self):
        self.write(b"0" * 64 + b"  other.zip\n")
        outcome = self.verify()
        self.assertFalse(outcome.ok)
        self.assertIn("has no line for RYOS-windows.zip", outcome.message)

    def test_a_missing_sums_is_refused(self):
        (self.tmp / "SHA256SUMS.txt").unlink()
        outcome = self.verify()
        self.assertFalse(outcome.ok)
        self.assertIn("There is no SHA256SUMS.txt beside RYOS-windows.zip", outcome.message)


@unittest.skipUnless(HAS_CRYPTOGRAPHY, "needs the cryptography library")
class TestSigningTool(unittest.TestCase):
    PASS = "correct horse battery staple"

    def setUp(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import sign_release
        self.tool = sign_release
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.keyfile = self.tmp / "release.pem"
        self.sums = self.tmp / "SHA256SUMS.txt"
        self.sums.write_bytes(b"a" * 64 + b"  RYOS-windows.zip\n"
                              + b"b" * 64 + b"  RYOS-agent.zip\n")

    def new(self):
        out = io.StringIO()
        public = self.tool.new_key(self.keyfile, self.PASS, out)
        return public, out.getvalue()

    def test_new_writes_an_encrypted_key_outside_the_repo_and_prints_the_public_key(self):
        public, said = self.new()
        self.assertEqual(len(public), 32)
        self.assertIn(public.hex(), said)
        self.assertIn("manual update", said)
        pem = self.keyfile.read_bytes()
        self.assertIn(b"BEGIN ENCRYPTED PRIVATE KEY", pem)
        self.assertNotIn(pem.decode(), said)
        from cryptography.hazmat.primitives import serialization
        with self.assertRaises((TypeError, ValueError)):
            serialization.load_pem_private_key(pem, password=None)
        serialization.load_pem_private_key(pem, password=self.PASS.encode())
        answers = iter([self.PASS, self.PASS])
        other = self.tmp / "second.pem"
        out = io.StringIO()
        self.assertEqual(self.tool.main(["new", str(other)], ask=lambda _q: next(answers),
                                        out=out, err=io.StringIO()), 0)
        self.assertTrue(other.exists())

    def test_new_refuses_an_existing_file_or_a_path_in_the_repo(self):
        self.keyfile.write_bytes(b"keep me")
        with self.assertRaises(self.tool.ToolError):
            self.new()
        self.assertEqual(self.keyfile.read_bytes(), b"keep me")
        inside = ROOT / "dist" / "nope-release.pem"
        with self.assertRaises(self.tool.ToolError) as said:
            self.tool.new_key(inside, self.PASS, io.StringIO())
        self.assertIn("inside the repository", str(said.exception))
        self.assertFalse(inside.exists())
        with self.assertRaises(self.tool.ToolError):
            self.tool.new_key(self.tmp / "empty.pem", "", io.StringIO())
        answers = iter([self.PASS, "different"])
        err = io.StringIO()
        self.assertEqual(self.tool.main(["new", str(self.tmp / "x.pem")],
                                        ask=lambda _q: next(answers),
                                        out=io.StringIO(), err=err), 1)
        self.assertIn("differ", err.getvalue())
        self.assertFalse((self.tmp / "x.pem").exists())

    def test_sign_writes_a_signature_ryos_accepts(self):
        public, _ = self.new()
        out = io.StringIO()
        target = self.tool.sign_sums(self.keyfile, self.PASS, self.sums, "2.4.0", out)
        self.assertEqual(target, self.tmp / signature.SIG_NAME)
        self.assertIn(public.hex(), out.getvalue())
        self.assertIn("RYOS 2.4.0", out.getvalue())
        checked = signature.check(self.sums.read_bytes(), target.read_bytes(), public,
                                  version="v2.4.0", current="2.4.0")
        self.assertTrue(checked.ok, checked.message)
        err = io.StringIO()
        self.assertEqual(self.tool.main(["sign", str(self.keyfile), "--sums",
                                         str(self.sums), "--version", "v2.4.1"],
                                        ask=lambda _q: self.PASS, out=io.StringIO(),
                                        err=err), 0, err.getvalue())
        self.assertEqual(signature.parse(target.read_bytes()).version, "2.4.1")

    def test_sign_refuses_a_key_in_the_repo_a_wrong_passphrase_or_a_crlf_sums(self):
        self.new()
        with self.assertRaises(self.tool.ToolError) as said:
            self.tool.sign_sums(ROOT / "pyproject.toml", self.PASS, self.sums, "2.4.0",
                                io.StringIO())
        self.assertIn("inside the repository", str(said.exception))
        with self.assertRaises(self.tool.ToolError) as said:
            self.tool.sign_sums(self.keyfile, "wrong", self.sums, "2.4.0", io.StringIO())
        self.assertIn("wrong passphrase", str(said.exception))
        for bad, words in ((self.sums.read_bytes().replace(b"\n", b"\r\n"), "CR"),
                           (self.sums.read_bytes()[:-1], "line break"),
                           (b"zz  RYOS-windows.zip\n", "Line 1")):
            self.sums.write_bytes(bad)
            with self.assertRaises(self.tool.ToolError) as said:
                self.tool.sign_sums(self.keyfile, self.PASS, self.sums, "2.4.0",
                                    io.StringIO())
            self.assertIn(words, str(said.exception))
        with self.assertRaises(self.tool.ToolError) as said:
            self.tool.sign_sums(self.keyfile, self.PASS, self.sums, "two", io.StringIO())
        self.assertIn("not a version", str(said.exception))
        self.assertFalse((self.tmp / signature.SIG_NAME).exists())

    def test_sign_leaves_sums_byte_for_byte_unchanged(self):
        self.new()
        before = self.sums.read_bytes()
        stat = self.sums.stat()
        self.tool.sign_sums(self.keyfile, self.PASS, self.sums, "2.4.0", io.StringIO())
        self.assertEqual(self.sums.read_bytes(), before)
        self.assertEqual(self.sums.stat().st_mtime_ns, stat.st_mtime_ns)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()),
                         ["SHA256SUMS.txt", "SHA256SUMS.txt.sig", "release.pem"])


if __name__ == "__main__":
    unittest.main()
