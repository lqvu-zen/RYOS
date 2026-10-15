---
name: release-ryos
description: 'Cut a new GitHub release of the RYOS desktop app through a release candidate — set the version, build every download, run the release check, publish vX.Y.Z-rcN as a pre-release, have it tested, then promote the same commit to vX.Y.Z. Use this whenever the user wants to ship RYOS: "cut a release", "release v1.6.5", "make a release candidate", "cut an rc", "publish rc2", "promote the rc", "publish a new version", "ship it", "build the exe and put it on GitHub", "make a new build", or "tag a release". Also use it when the user has finished a batch of features/fixes and says it''s time to get them out to users. This skill carries the version scheme (X.Y.Z-rcN and X.Y.Z), the build, the release_check gate, the tester and manual-checklist steps, the promotion gate and the gh release steps, so the process is repeatable and safe. It runs on Windows with uv and an authenticated gh CLI. Do NOT use it to write features (use add-ryos-feature), fix bugs (use fix-ryos-bug), or just launch the app locally (use run-ryos).'
---

# Releasing RYOS

RYOS ships as a GitHub release with four downloadable assets, built and checked by `build_release.py`: **`RYOS-windows.zip`** (`RYOS.exe` and the console `ryos-cli.exe`, **no** MCP server — variant `windows`), **`RYOS-windows-ai.zip`** (the same with the MCP server for AI agents — `windows-ai`), **`RYOS-agent.zip`** (`ryos-cli.exe` alone with MCP, no window and no Qt — RYOS Agent, `agent`) and **`RYOS-portable.zip`** (the source, run with uv via `run.bat`), plus `SHA256SUMS.txt`. Each build's update notice names its own zip (`ryos/buildinfo.py`), so these names and variant IDs must not change once released. The release is tagged in the repo `lqvu-zen/RYOS`, and the app's built-in update check (`ryos/notifications.py`) compares the running `__version__` against the latest GitHub release — so the tag, the assets, and `__version__` must all line up.

Every release goes out in two parts. **A. A release candidate**: the downloads are built, pass `tests/release_check.py`, are published as a GitHub **pre-release** `vX.Y.Z-rcN`, are tested by the `ryos-tester` agent, and are used by Vũ on his real data until he has ticked his checklist (no minimum time). **B. Promotion**: the same commit, with only the version line changed, is rebuilt, checked again, release-reviewed and published as `vX.Y.Z`. 2.3.0 was built and published in an hour, and #29 and #30 were found days later in normal use; the candidate phase is where those are meant to surface.

Releasing is **not a design problem** — it's a deterministic runbook, so there is no design subagent here, and you run the steps inline. The safety comes from **hard gates**: CI green on the commit you build, the build succeeding, `release_check.py` printing `RELEASE CHECK PASSED`, the tester reporting `TESTER: PASS`, every box of Vũ's checklist ticked, and the release review printing `READY TO PUBLISH`. Stop and report at any gate that fails rather than publishing. (Drafting release notes from the commit log is the one step you may hand to a cheap Haiku/Sonnet subagent if you like.)

## Environment this needs

This runs on the maintainer's **Windows** machine, because the exes are built and checked there:

- `uv` installed (drives the build in an isolated env, and runs the portable download in the release check).
- `gh` CLI installed and authenticated to GitHub (`gh auth status`) — it creates the releases and uploads assets.
- A working tree you're willing to commit and push from, on the release branch (`main`).

If you're somewhere without a display or without Windows (e.g. a Linux sandbox), you **cannot** build or check the exes — say so plainly and stop; do not fake a release.

## Version scheme

`__version__` (in `ryos/__init__.py`) changes **only here** — never per feature or fix, and never with a `-dev` suffix.

- **Release candidate** `X.Y.Z-rcN`: `__version__ = "X.Y.Z-rcN"`; `setup_cxfreeze.py` `version="X.Y.Z"` (the Windows version resource takes numbers only). Tag `vX.Y.Z-rcN`, published as a **pre-release**.
- **Final** `X.Y.Z`: `__version__ = "X.Y.Z"`, `setup_cxfreeze.py` unchanged from the candidate. Tag `vX.Y.Z`, published as the latest release.
- `pyproject.toml` reads the version from `__version__` via hatchling; it is the single source. Tags carry the `v` prefix, `__version__` does not.
- The update check reads `/releases/latest`, which skips pre-releases, so nobody is told about a candidate. A candidate's own update check sees its final as newer (`2.3.1-rc1 < 2.3.1`, `_parse_version`), so testers are offered the final when it ships.
- N is one more than the highest number among the existing `vX.Y.Z-rc*` tags (`git tag -l "vX.Y.Z-rc*"`) and any `-rcN` already in `__version__` at HEAD; 1 when there is none. A failed candidate's number is never reused or re-tagged.

## A. Release candidate

### A1. Check CI, then ask for the version and draft notes

```bash
cd D:/Projects/RYOS && git status --porcelain && gh run list -L 3 --json conclusion,status,headSha,displayTitle \
  --jq '.[] | "\(.status)\t\(.conclusion // "-")\t\(.headSha[0:7])\t\(.displayTitle)"'
```

The tree must be clean and `HEAD` must have a **successful** run. CI has sat red for several commits without anyone noticing, so treat a failure — or a run still in progress — as a stop.

Then check the latest published tags (`gh release list -R lqvu-zen/RYOS -L 5`) and **ask the user for the version number X.Y.Z, and wait for the answer** before changing anything — you may suggest one (patch for fixes, minor for notable features), but the maintainer names it. A bare "release" or "go ahead" is not approval of a version suggested earlier in the conversation: 2.1.0 shipped that way, and the maintainer asked never to repeat it. Work out N: N is one more than the highest number among the existing `vX.Y.Z-rc*` tags (`git tag -l "vX.Y.Z-rc*"`) and any `-rcN` already in `__version__` at HEAD; 1 when there is none. A failed candidate's number is never reused or re-tagged. Gather release notes; if the user didn't give any, draft them from `git log <last final tag>..HEAD --oneline` and show them for approval. Notes are for users, not for the changelog: say what changed for someone using the app, and flag anything that will behave differently.

### A2. Set the versions, commit and push — before building

Set `__version__ = "X.Y.Z-rcN"` in `ryos/__init__.py` and `version="X.Y.Z"` in `setup_cxfreeze.py`. Commit **before** building: each exe records the commit it was built from, and the release check fails a build of a dirty tree or of a commit other than HEAD.

```bash
cd D:/Projects/RYOS && git add ryos/__init__.py setup_cxfreeze.py && git commit -m "Release candidate X.Y.Z-rcN" && git push
```

Stage deliberately — **never** `dist/`, `build/`, `scripts.db`, or `__pycache__`. Wait for CI to go green on this commit (`gh run watch <id> --exit-status`); the build can run meanwhile, but nothing is published until it is green.

### A3. Build every download — hard gate

```bash
cd D:/Projects/RYOS && uv run --extra mcp --with cx_Freeze python build_release.py 2>&1 | tail -8
```

It builds the three frozen variants from clean folders, zips all four downloads, checks what each holds and must not hold, and writes `SHA256SUMS.txt`. It ends with `build_release done`; on any problem (an exe missing, the MCP SDK in the build without it or missing from one with it, Qt or the window in the agent build, a `__pycache__` or `_build_info.py` in the source) it exits 1. **If it fails, stop and report.** Don't package anything by hand (`Compress-Archive` swept 95 stale bytecode files into 2.0.0's first portable zip). `build.bat` / `build_cxfreeze.bat` build only the `windows` variant, for development.

### A3b. Vũ signs — hard gate

Stop and ask Vũ to sign the build's checksums himself. The key and its passphrase stay with him; never ask for either, never look for the key file, never sign for him:

```bash
uv run --with cryptography python tools/sign_release.py sign <his key file> --sums dist/SHA256SUMS.txt
```

It writes `dist/SHA256SUMS.txt.sig` for the version in `ryos/__init__.py`. Wait for him to say it is done, and check the file exists. Every rebuild (A3 again, B3) changes `SHA256SUMS.txt`, so it is signed again; a `.sig` left over from an earlier build is deleted first. If the key or its passphrase is lost, a new key pair means every installed RYOS needs one manual update to a build carrying the new public key (`docs/CONTRIBUTING.md`).

### A4. Release check — hard gate

Quit any RYOS running on this machine first (the window, the tray icon, an MCP server a client started): the check's `real_folder_untouched` case compares the real `%APPDATA%\RYOS` before and after, and a running RYOS writes to it. Run nothing else that touches it meanwhile (the unit suite and `qt_smoke.py` both do).

```bash
cd D:/Projects/RYOS && uv run python tests/release_check.py 2>&1 | tail -40
```

One script over all four zips, on throwaway data, with nothing opening on the first screen. It checks the zips and checksums; that each exe's `--version` names HEAD with no `-dirty`; `launch_smoke` on every download (and on the second screen when there is one); the portable zip is exactly the tracked source and runs with uv; the command line's management commands; MCP over plain JSON-RPC (list, run, poll, stop, refusals) and the 125 refusal of the build without agents; `session_smoke` in both layouts; an upgrade from a fixture database of every past release (`tests/fixtures/db/`); the same data used by RYOS Agent and the Windows builds in both orders; the `signature` case (each frozen build's own `ryos-cli verify` accepts its zip with `SHA256SUMS.txt.sig`, and refuses a signature made with the test key or a changed `SHA256SUMS.txt`); the "compatible from" guard in every download; and that the real `%APPDATA%\RYOS` is unchanged. It must end with `RELEASE CHECK PASSED`. **Any `[FAIL]` is a stop**: fix it (with `fix-ryos-bug`), and start again from A2 with N+1. A `[SKIP] launch_visible: skipped (one monitor)` is fine.

Recommended too, before Vũ uses the candidate: check his real data on a copy (`uv run python tests/real_data_smoke.py`; `--db <backup>` for an older backup). A count that drops is a stop until you know why.

### A5. Publish the pre-release

Only once CI is green on the candidate commit. Write the notes to a file in the scratchpad (backticks and `$` get mangled on the command line), with "Which download?" and "Check your download" as in B5, and a first line saying this is a release candidate for testing:

```bash
cd D:/Projects/RYOS && gh release create vX.Y.Z-rcN dist/RYOS-windows.zip dist/RYOS-windows-ai.zip \
  dist/RYOS-agent.zip dist/RYOS-portable.zip dist/SHA256SUMS.txt dist/SHA256SUMS.txt.sig \
  -R lqvu-zen/RYOS --prerelease --latest=false --target <full sha of HEAD> \
  --title "vX.Y.Z-rcN" --notes-file <notes.md> 2>&1
```

Record the time it was published.

### A6. Test the candidate — hard gate

Spawn the tester, which hasn't seen this session:

```
Agent({ description: "Test vX.Y.Z-rcN", subagent_type: "ryos-tester", prompt: <brief> })
```

The brief gives: the candidate version and tag; `git log <last final tag>..HEAD --oneline`; the paths of the four zips in `dist/`; and the whole `release_check.py` output from A4. It reads `docs/BEHAVIOUR.md` itself. Its last line is `TESTER: PASS` or `TESTER: FAIL (n)`. **Any FAIL blocks promotion**: fix it, and start again from A2 with N+1.

### A7. Vũ's manual checklist

Write the checklist into the release plan's Status table (`docs/plans/release-X.Y.Z.md`, or the release's plan), with the tester's "not testable by an agent" items added, and the publish time from A5:

- [ ] Claude Desktop connects to the `windows-ai` build's `ryos-cli.exe mcp` and runs an exposed script.
- [ ] Claude Code connects to the `agent` build (RYOS Agent) and runs an exposed script.
- [ ] `uv run python tests/real_data_smoke.py` on your real data, and `--db <backup>` on an older backup if you have one: no count dropped (it works on copies and checks the real folder is unchanged).
- [ ] Your real data looks right after the upgrade (scripts, groups, pipelines, schedules, history).
- [ ] A fresh download from the candidate's release page: SmartScreen's flow, and "Check your download" (hash matches `SHA256SUMS.txt`).
- [ ] Properties -> Details on `RYOS.exe` and `ryos-cli.exe` shows the publisher.
- [ ] (each item from the tester's "not testable by an agent" list)

### A8. Vũ uses the candidate

Vũ uses it on his real data and ticks his checklist. There is **no minimum time** on a candidate (Vũ's decision, 2026-10-14). Any bug found is fixed through `fix-ryos-bug`, and a new candidate starts from A2 with N+1. Between a candidate's tag and its promotion, **only `docs/`-only commits may land on `main`**; any other change means a new candidate.

## B. Promote

Only when Vũ says so, with `release_check.py` passed, the tester's PASS in hand and every checklist box ticked. No minimum time since the candidate was published.

### B1. The candidate is what ships — hard gate

```bash
cd D:/Projects/RYOS && git diff --stat vX.Y.Z-rcN..HEAD -- . ':(exclude)docs'
```

Before the version commit (B2) this must print nothing; after it, only `ryos/__init__.py`, one line changed (`-rcN` dropped). Anything else is a stop: it is a new candidate, not a promotion.

### B2. Set the final version, commit and push

Set `__version__ = "X.Y.Z"` (`setup_cxfreeze.py` already says `X.Y.Z`). Run B1 again, then:

```bash
cd D:/Projects/RYOS && git add ryos/__init__.py && git commit -m "Release X.Y.Z" && git push
```

Wait for CI to go green on it.

### B3. Rebuild and check again — hard gate

A3, A3b and A4 again, on this commit, with any running RYOS quit first as in A4: `build_release.py`, Vũ signs the new `SHA256SUMS.txt` (the candidate's `.sig` is for another version and another build), then `release_check.py` must print `RELEASE CHECK PASSED`.

### B4. Release review — hard gate

Spawn a fresh reviewer:

```
Agent({ description: "Release review vX.Y.Z", subagent_type: "ryos-reviewer", prompt: <brief> })
```

(If `ryos-reviewer` isn't listed, use `subagent_type: "general-purpose"`, `model: "opus"`, `effort: "high"`, and paste `.claude/agents/ryos-reviewer.md` at the top of the brief.)

The brief starts with **"Release mode."** and includes, verbatim:

- the version being released, the candidate tag it promotes, and the last released tag (`gh release list -R lqvu-zen/RYOS -L 3`);
- the approved release notes, including "Which download?";
- the **expected lineup** below;
- the last lines of the `build_release.py` output and the whole `release_check.py` output from B3;
- the tester's last report (from A6) and the state of Vũ's checklist (A7);
- the B1 diff;
- the release plan's final step with its "Done when" items, if there is one.

Expected lineup (**update this table whenever the downloads change**, together with `problems_in()` in `build_release.py`):

| Zip | Variant | Must contain | Must not contain |
|---|---|---|---|
| `RYOS-windows.zip` | `windows` | `RYOS.exe`, `ryos-cli.exe` | the `mcp` package (`lib/mcp/`) |
| `RYOS-windows-ai.zip` | `windows-ai` | `RYOS.exe`, `ryos-cli.exe`, the `mcp` package (`lib/mcp/`) | — |
| `RYOS-agent.zip` | `agent` | `ryos-cli.exe`, the `mcp` package (`lib/mcp/`) | `RYOS.exe`, `qtui`, Qt / PySide6 / shiboken6 |
| `RYOS-portable.zip` | source | the source, `ryos/__init__.py`, `run.bat`, `install_uv.bat` | `__pycache__`, `_build_info.py` |
| all | | | `scripts.db`, a settings file, `__pycache__` in the source |

`SHA256SUMS.txt` lists exactly these four zips, and `SHA256SUMS.txt.sig` sits beside it. Three more things the lineup must show (the build puts them in; `buildinfo.COMPANY`, `COPYRIGHT`):

- **Both exes carry the publisher.** `RYOS.exe` and `ryos-cli.exe` (only the latter in the agent build) show company `Zenitus (Lê Quang Vũ)` and copyright `© 2026 Lê Quang Vũ (Zenitus)` in Properties -> Details (`(Get-Item <exe>).VersionInfo`).
- **The signature checks with each build's own tool.** For `windows`, `windows-ai` and `agent`, `ryos-cli.exe verify <its zip>` from that build's folder, with `SHA256SUMS.txt` and `SHA256SUMS.txt.sig` beside the zip, exits 0 and names the version being released.
- **Each build's `--version` names HEAD's short commit with no `-dirty`, and HEAD is the commit to be tagged** (`release_check`'s `build_commit` case).

If the reviewer reports BLOCKERS, fix them — a fix to anything outside `docs/` is a new candidate (A2) — and review again. Go on only on `READY TO PUBLISH`. Show the user every **needs a human** item it listed that the checklist does not already cover, and **wait for them to confirm each one** before publishing.

### B5. Create the GitHub release

```bash
cd D:/Projects/RYOS && gh release create vX.Y.Z dist/RYOS-windows.zip dist/RYOS-windows-ai.zip \
  dist/RYOS-agent.zip dist/RYOS-portable.zip dist/SHA256SUMS.txt dist/SHA256SUMS.txt.sig \
  -R lqvu-zen/RYOS --latest --target <full sha of HEAD> --title "vX.Y.Z" --notes-file <notes.md> 2>&1
```

Include the download guidance in the notes so users know which asset to grab:

```
<user-approved notes>

## Which download?
- **RYOS-windows.zip** — the app: extract and run `RYOS.exe`. `ryos-cli.exe` beside it is the command line. No AI agents.
- **RYOS-windows-ai.zip** — the app with AI agents: the same, and `ryos-cli.exe mcp` lets Claude run the scripts you tick **Available to agents**.
- **RYOS-agent.zip** — RYOS Agent: just `ryos-cli.exe`, for letting Claude run an allow-list of your scripts without the app. See the guide's RYOS Agent page.
- **RYOS-portable.zip** — run from source: extract and double-click `run.bat` (needs uv; run `install_uv.bat` first if needed).
- **SHA256SUMS.txt** — checksums of the four zips.
- **SHA256SUMS.txt.sig** — the signature of `SHA256SUMS.txt`: RYOS checks it before it installs an update, and `ryos-cli verify` checks a zip you downloaded by hand.

All four keep your data in the same place, so you can move between them; each one's update notice names its own zip.

## Check your download
1. Download only from https://github.com/lqvu-zen/RYOS/releases.
2. In PowerShell: `Get-FileHash .\RYOS-windows-ai.zip -Algorithm SHA256` (or the zip you downloaded). The hash must match that zip's line in `SHA256SUMS.txt` (letter case does not matter).
3. Keep `SHA256SUMS.txt` and `SHA256SUMS.txt.sig` beside the zip and run `ryos-cli.exe verify .\RYOS-windows-ai.zip` from an RYOS you already trust: it must exit 0.
4. Right-click `RYOS.exe` (or `ryos-cli.exe`) -> Properties -> Details: the company is **Zenitus (Lê Quang Vũ)**.
5. SmartScreen's "Unknown publisher" is expected: RYOS is not code-signed. Choose **More info -> Run anyway** only for a download that passed the check.
```

### B6. Clear `dist/`

The zips are on GitHub now; stale builds left in `dist/` are how an old exe gets checked or attached next time:

```bash
cd D:/Projects/RYOS && rm -rf dist/* build
```

### B7. A fixture for a new schema

If X.Y.Z's `SCHEMA_VERSION` (`ryos/db.py`) is newer than every fixture's (`tests/fixtures/db/`), add one written by this release's own code, and commit it:

```bash
cd D:/Projects/RYOS && uv run python tests/fixtures/db/make_fixtures.py vX.Y.Z
```

### B8. Archive the plan, only if it is complete

The release is published, so its plan (and its brief, if one exists) leave `docs/plans/`. First set the plan's own release row to `done, vX.Y.Z published <date>` (a `docs/`-only edit), then check the plan is complete; the check, which reads only the rows of the `## Status` table, prints nothing when it is:

```bash
cd D:/Projects/RYOS && plan=docs/plans/release-X.Y.Z.md
awk -F'|' '/^## Status/{t=1} t && /^\| [0-9]+ /{s=tolower($3); sub(/^ +/,"",s); if (s !~ /^(done|not needed)/) print "OPEN: " $2}' $plan
grep -n -i '\[ \]\|needs a human' $plan
```

Any output means the plan is **not** complete: leave it in `docs/plans/`, skip the rest of B8, and list the open rows in B9. A `done` row that still names something to run or tick is also open; read the Status table, the check is only the floor.

When it prints nothing:

```bash
cd D:/Projects/RYOS && git mv docs/plans/release-X.Y.Z.md docs/archive/release-X.Y.Z.md
[ -f docs/plans/release-X.Y.Z-brief.md ] && git mv docs/plans/release-X.Y.Z-brief.md docs/archive/release-X.Y.Z-brief.md
grep -rnF "release-X.Y.Z" --include=*.md --include=*.py . | grep -v "^./docs/archive/\|^./dist/\|^./docs/STATUS.md"
```

Point every hit at the archived path, so none dangle. `docs/STATUS.md` is left to the secretary. Commit only those paths, by path, as `docs: archive release-X.Y.Z plan`, and push. Only `docs/`-only paths may be in this commit.

### B9. Report

Give the user the release URL (`gh` prints it), the version shipped, the candidate it promotes, the assets attached, and a one-line confirmation that `release_check.py` passed, the tester reported `TESTER: PASS`, the checklist is ticked and the release review printed `READY TO PUBLISH`. Say whether the plan was archived, or which rows kept it in `docs/plans/`. Note anything you skipped or that needs follow-up.
