from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = ROOT / ".claude" / "hooks" / "guard.py"
SESSION_PATH = ROOT / ".claude" / "hooks" / "session_start.py"
CHECKS_PATH = ROOT / "tools" / "harness_checks.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


guard = _load("ryos_harness_guard", GUARD_PATH)
session_start = _load("ryos_harness_session_start", SESSION_PATH)
harness_checks = _load("ryos_harness_checks", CHECKS_PATH)

ENV = {
    "APPDATA": r"C:\Users\Tester\AppData\Roaming",
    "LOCALAPPDATA": r"C:\Users\Tester\AppData\Local",
    "USERPROFILE": r"C:\Users\Tester",
}
SCRATCH = r"C:\Users\Tester\AppData\Local\Temp\claude\proj\session\scratchpad"


def clean() -> list[str]:
    return []


def dirty() -> list[str]:
    return ["docs/STATUS.md", "docs/plans/release-2.4.0.md"]


def verdict(command: str, tool: str = "Bash", secretary=clean):
    return guard.decide(tool, {"command": command}, ENV, secretary)


def file_verdict(path: str, tool: str = "Write"):
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    return guard.decide(tool, {key: path, "content": "x"}, ENV, clean)


class TestGuardRefuses(unittest.TestCase):
    def assertRefused(self, command: str, tool: str = "Bash", secretary=clean) -> str:
        result = verdict(command, tool, secretary)
        self.assertEqual(result.kind, "deny", f"{tool}: {command!r} was {result}")
        self.assertTrue(result.reason)
        return result.reason

    def test_writes_into_the_real_data_folder(self):
        self.assertRefused('echo x > "$APPDATA/RYOS/settings.json"')
        self.assertRefused(r"Remove-Item -Recurse $env:APPDATA\RYOS", "PowerShell")
        self.assertRefused("rm -rf /c/Users/Tester/AppData/Roaming/RYOS/logs")
        self.assertRefused('$p = "$env:APPDATA\\RYOS"; Remove-Item $p', "PowerShell")
        self.assertRefused(r'sqlite3 %APPDATA%\RYOS\scripts.db "delete from scripts"')
        self.assertRefused(r'sqlite3 %APPDATA%\RYOS\scripts.db "delete from scripts"', "PowerShell")
        self.assertRefused("cp x.db ~/AppData/Roaming/RYOS/")
        self.assertRefused(
            "uv run python -c \"open(r'C:\\Users\\Tester\\AppData\\Roaming\\RYOS\\x','w')\"")

    def test_the_local_data_folder_counts_as_real_data(self):
        self.assertRefused(r"Remove-Item -Recurse $env:LOCALAPPDATA\RYOS\updates", "PowerShell")
        self.assertRefused("rm -rf ~/AppData/Local/RYOS/updates")

    def test_a_read_feeding_a_write(self):
        self.assertRefused(r"Get-ChildItem $env:APPDATA\RYOS | Remove-Item", "PowerShell")
        self.assertRefused("ls /c/Users/Tester/AppData/Roaming/RYOS | xargs rm")

    def test_a_wrapped_write(self):
        self.assertRefused('powershell -Command "Remove-Item -Recurse $env:APPDATA\\RYOS"')
        self.assertRefused(r'cmd /c "del /q %APPDATA%\RYOS\scripts.db"')
        self.assertRefused('bash -c "rm -rf $APPDATA/RYOS"')
        self.assertRefused('echo $(rm -rf "$APPDATA/RYOS")')

    def test_a_heredoc_script_naming_the_real_folder(self):
        self.assertRefused("uv run python - <<'EOF'\n"
                           "open(r'C:\\Users\\Tester\\AppData\\Roaming\\RYOS\\x', 'w')\nEOF")

    def test_write_tools_into_the_real_folder(self):
        for tool in ("Write", "Edit", "MultiEdit"):
            result = file_verdict(r"C:\Users\Tester\AppData\Roaming\RYOS\settings.json", tool)
            self.assertEqual(result.kind, "deny", tool)
        self.assertEqual(file_verdict("/c/Users/Tester/AppData/Local/RYOS/x.ipynb",
                                      "NotebookEdit").kind, "deny")

    def test_starting_ryos_without_a_throwaway_appdata(self):
        self.assertRefused("uv run ryos list")
        self.assertRefused("uv run --extra mcp ryos mcp")
        self.assertRefused("dist/cxfreeze/ryos-cli.exe run hello")
        self.assertRefused("uv run python -m ryos")
        self.assertRefused(r"& .\dist\cxfreeze\RYOS.exe", "PowerShell")
        self.assertRefused("timeout 30 uv run ryos")
        self.assertRefused('APPDATA="$APPDATA" uv run ryos list')
        self.assertRefused("start RYOS.exe")
        self.assertRefused("cmd //c start dist/cxfreeze/RYOS.exe")
        self.assertRefused('cmd /c start "" dist/cxfreeze/RYOS.exe')
        self.assertRefused("Invoke-Item dist/cxfreeze/RYOS.exe", "PowerShell")
        self.assertRefused("ii ./RYOS.exe", "PowerShell")
        self.assertRefused("uvx --from . ryos list")
        self.assertRefused("uv tool run ryos list")

    def test_mentioning_a_harness_does_not_exempt_a_write(self):
        self.assertRefused("rm -rf ~/AppData/Roaming/RYOS tests/launch_smoke.py")
        self.assertRefused("cp tests/session_smoke.py ~/AppData/Roaming/RYOS/")

    def test_a_relative_write_after_cd(self):
        self.assertRefused('cd "$APPDATA" && rm -rf RYOS')
        self.assertRefused("cd ~/AppData/Roaming/RYOS && rm -rf logs")
        self.assertRefused("Set-Location $env:LOCALAPPDATA; Remove-Item -Recurse RYOS", "PowerShell")
        self.assertRefused("cd ~/ryos-keys")

    def test_set_appdata_outside_cmd_is_the_10_09_case(self):
        reason = self.assertRefused(r"set APPDATA=C:\tmp\x; uv run ryos list", "PowerShell")
        self.assertIn("In PowerShell this sets no environment variable", reason)
        self.assertIn("$env:APPDATA", reason)
        self.assertRefused(r"set APPDATA=C:\tmp\x")

    def test_the_signing_key(self):
        self.assertRefused("cat ~/ryos-keys/ryos-release.pem")
        self.assertRefused(r"Get-ChildItem $env:USERPROFILE\ryos-keys", "PowerShell")
        self.assertRefused("ls /c/Users/Tester/ryos-keys")
        self.assertRefused(r"type %USERPROFILE%\ryos-keys\notes.txt")
        self.assertRefused("uv run --with cryptography python tools/sign_release.py sign k.pem")
        self.assertRefused("uv run --with cryptography python tools/sign_release.py new")
        self.assertRefused("cat x.pem")
        self.assertRefused("cat ./ryos-release.pem")
        self.assertRefused("cp ryos-release.pem /tmp/")
        self.assertRefused("echo x > signing.key")
        self.assertRefused(r"Get-Content .\ryos-release.pem", "PowerShell")
        self.assertEqual(file_verdict("x.pem").kind, "deny")
        self.assertEqual(file_verdict(r"C:\Users\Tester\ryos-keys\notes.txt", "Edit").kind, "deny")

    def test_reverting_secretary_files(self):
        self.assertRefused("git checkout -- docs/STATUS.md")
        self.assertRefused(r"git restore docs\plans\release-2.4.0.md")
        self.assertRefused("git -C D:/Projects/RYOS checkout HEAD -- docs/plans/")
        self.assertRefused('powershell -Command "git checkout -- docs/STATUS.md"')
        self.assertRefused("git status --short | awk '{print $2}' | xargs -r git checkout --")
        self.assertRefused("git checkout -- $(git diff --name-only)")
        self.assertRefused("git reset --hard")
        self.assertRefused("git reset HEAD~1 --hard")
        self.assertRefused("cd docs && git checkout -- STATUS.md")
        self.assertRefused("cd docs/plans; git restore release-2.4.0.md", "PowerShell")

    def test_whole_tree_discards_while_secretary_edits_wait(self):
        for command in ("git checkout -- .", "git checkout .", "git checkout -f main",
                        "git restore :/", "git stash", "git stash -u", "git stash push",
                        "git clean -fd", "git checkout -- docs", "git restore docs/*.md",
                        "git checkout -- '*.md'", "git checkout -- 'docs/*.md'",
                        "git checkout -- STATUS.md", "git restore STATUS.md",
                        "git switch -f main", "git switch --discard-changes main",
                        "cd /c/elsewhere && git restore x"):
            reason = self.assertRefused(command, secretary=dirty)
            self.assertIn("docs/STATUS.md", reason)


class TestGuardAllows(unittest.TestCase):
    def assertAllowed(self, command: str, tool: str = "Bash", secretary=clean) -> None:
        result = verdict(command, tool, secretary)
        self.assertEqual(result.kind, "allow", f"{tool}: {command!r} was {result}")

    def test_ryos_with_a_throwaway_appdata(self):
        self.assertAllowed('APPDATA="$S/a" LOCALAPPDATA="$S/a/local" uv run ryos list')
        self.assertAllowed(f"$env:APPDATA='{SCRATCH}\\a'; & .\\dist\\cxfreeze\\ryos-cli.exe list",
                           "PowerShell")
        self.assertAllowed(r'cmd /c "set APPDATA=C:\t&& ryos-cli list"')
        self.assertAllowed('export APPDATA="$T" RYOS_NO_TOASTS=1; uv run ryos list')

    def test_harmless_ryos_commands(self):
        self.assertAllowed("uv run ryos --version")
        self.assertAllowed("dist/cxfreeze/ryos-cli.exe --help")
        self.assertAllowed("uv run ryos verify dist/RYOS-windows.zip")

    def test_self_guarding_harnesses(self):
        self.assertAllowed("uv run python tests/real_data_smoke.py")
        self.assertAllowed(r"uv run python tests/real_data_smoke.py --db %APPDATA%\RYOS\backup.db")
        self.assertAllowed("uv run python tests/release_check.py 2>&1 | tail -40")
        self.assertAllowed("uv run python tests/launch_smoke.py --exe dist/cxfreeze/RYOS.exe")

    def test_reading_and_copying_out_of_the_real_folder(self):
        self.assertAllowed('tail -50 "$APPDATA/RYOS/logs/ryos.log"')
        self.assertAllowed('Get-Content "$env:APPDATA\\RYOS\\logs\\ryos.log" | Select-Object -Last 12',
                           "PowerShell")
        self.assertAllowed('cp /c/Users/Tester/AppData/Roaming/RYOS/scripts.db "$S/copy.db"')
        self.assertAllowed(r"Copy-Item $env:APPDATA\RYOS\scripts.db -Destination C:\tmp\copy.db",
                           "PowerShell")
        self.assertAllowed('ls ~/AppData/Roaming/RYOS | grep db')
        self.assertAllowed("cd ~/AppData/Roaming/RYOS && ls")
        self.assertAllowed('cd "$APPDATA/RYOS" && cp scripts.db "$S/copy.db"')
        self.assertAllowed('$log = "$env:APPDATA\\RYOS\\logs\\ryos.log"; '
                           "Select-String -Path $log -Pattern 'starting' | Select-Object -Last 12",
                           "PowerShell")

    def test_write_tools_elsewhere(self):
        self.assertEqual(file_verdict(SCRATCH + r"\appdata\RYOS\settings.json").kind, "allow")
        self.assertEqual(file_verdict(r"D:\Projects\RYOS\ryos\cli.py", "Edit").kind, "allow")

    def test_a_commit_message_naming_the_real_folder(self):
        self.assertAllowed(
            "cd D:/Projects/RYOS && git add ryos/ && git commit -m \"$(cat <<'EOF'\n"
            "fix: never write into %APPDATA%\\RYOS from a test\n\n"
            "Co-Authored-By: Claude <noreply@anthropic.com>\nEOF\n)\" && git push")

    def test_mentions_that_are_not_the_key(self):
        self.assertAllowed('grep -n "\\.pem" .gitignore')
        self.assertAllowed("git log --oneline -- '*.pem'")
        self.assertAllowed("uv run python - <<'EOF'\n"
                           "from ryos import cardmenu\n"
                           "print([i.key for i in cardmenu.script_menu()])\nEOF")
        self.assertAllowed('uv run --no-project --with pytest pytest -q -k "f.key"')
        self.assertAllowed('grep -rn "event.key" ryos/')
        self.assertAllowed('Select-String -Pattern "item.key" -Path ryos\\qtui\\shell.py',
                           "PowerShell")
        self.assertAllowed('gh pr create --title x --body "uses item.key"')
        self.assertAllowed('git commit -m "fix: settings.key handling"')
        self.assertAllowed("uv run python -c \"print(self.key)\"")

    def test_git_that_keeps_secretary_edits(self):
        self.assertAllowed("git checkout -- ryos/qtui/shell.py", secretary=dirty)
        self.assertAllowed("git checkout -- .")
        self.assertAllowed("git restore --staged ryos/x.py", secretary=dirty)
        self.assertAllowed("git stash list", secretary=dirty)
        self.assertAllowed("git checkout -b feature/x", secretary=dirty)
        self.assertAllowed("git checkout main", secretary=dirty)
        self.assertAllowed("git switch main", secretary=dirty)
        self.assertAllowed("git restore docs/*.md")
        self.assertAllowed("cd D:/Projects/RYOS && git checkout -- ryos/cli.py", secretary=dirty)
        self.assertAllowed("git mv docs/plans/release-2.4.0.md docs/archive/release-2.4.0.md")

    def test_the_secretary_check_runs_only_for_a_discard(self):
        calls = []

        def counting() -> list[str]:
            calls.append(1)
            return []

        verdict("git status --short && uv run --no-project --with pytest pytest -q",
                secretary=counting)
        self.assertEqual(calls, [])
        verdict("git stash", secretary=counting)
        self.assertEqual(calls, [1])


class TestGuardAsks(unittest.TestCase):
    def assertAsks(self, command: str, tool: str = "Bash") -> None:
        result = verdict(command, tool)
        self.assertEqual(result.kind, "ask", f"{tool}: {command!r} was {result}")

    def test_release_and_forced_pushes(self):
        self.assertAsks("gh release create v2.4.0-rc1 dist/RYOS-windows.zip \\\n"
                        "  -R lqvu-zen/RYOS --prerelease --latest=false --title \"v2.4.0-rc1\"")
        self.assertAsks("cmd /c gh release delete v1")
        self.assertAsks("gh release upload v2.4.0 dist/SHA256SUMS.txt.sig", "PowerShell")
        self.assertAsks("gh -R lqvu-zen/RYOS release edit v2.4.0 --draft=false")
        self.assertAsks("git push --force-with-lease")
        self.assertAsks("git push origin +main")
        self.assertAsks("git push -f origin main")
        self.assertAsks("git push --mirror")
        self.assertAsks("gh api -X DELETE repos/lqvu-zen/RYOS/releases/1")
        self.assertAsks("gh api repos/lqvu-zen/RYOS/releases -f tag_name=v9")

    def test_the_guard_does_not_ask_for_release_reads(self):
        self.assertEqual(verdict("gh release list -R lqvu-zen/RYOS -L 5").kind, "allow")
        self.assertEqual(verdict("gh api repos/lqvu-zen/RYOS/releases/latest").kind, "allow")
        self.assertEqual(verdict("git push -u origin main").kind, "allow")


SKILL_COMMANDS = [
    "cd D:/Projects/RYOS && uv run --no-project --with pytest pytest -q",
    "cd D:/Projects/RYOS && uvx ruff check . && uvx mypy --platform linux",
    "cd D:/Projects/RYOS && uv run --no-project --with PySide6 python tests/qt_smoke.py",
    "uv run python tests/session_smoke.py",
    "git diff",
    "git log --oneline -5",
    "cd D:/Projects/RYOS && git add ryos/ tests/test_ryos.py && git commit -m \"$(cat <<'EOF'\n"
    "Fix the stop button\n\nCo-Authored-By: Claude <noreply@anthropic.com>\nEOF\n)\" && git push",
    "cd D:/Projects/RYOS && git add ryos/ docs/BEHAVIOUR.md && git commit -m \"$(cat <<'EOF'\n"
    "Remember the last window size\n\noptional detail\n\n"
    "Co-Authored-By: Claude <noreply@anthropic.com>\nEOF\n)\" && git push",
    "uv run python .claude/skills/run-ryos/driver.py main compact --theme dark",
    "uv run python .claude/skills/run-ryos/driver.py workspace --theme light",
    "uv run --no-project --with pytest pytest -q",
    "uv run --no-project --with PySide6 python tests/qt_smoke.py",
    "uv run python .claude/skills/review-ryos-ui/scripts/audit.py --theme light dark",
    "uv run python .claude/skills/ryos-tutorial-generator/scripts/capture.py",
    "QT_QPA_PLATFORM=offscreen RYOS_NO_REGISTRY=1 uv run --no-project --with PySide6 python tests/qt_smoke.py",
    "QT_QPA_PLATFORM=offscreen RYOS_NO_REGISTRY=1 uv run python tests/session_smoke.py",
    "cd D:/Projects/RYOS && git status --porcelain && gh run list -L 3 --json "
    "conclusion,status,headSha,displayTitle \\\n"
    "  --jq '.[] | \"\\(.status)\\t\\(.conclusion // \"-\")\\t\\(.headSha[0:7])\\t\\(.displayTitle)\"'",
    "gh release list -R lqvu-zen/RYOS -L 5",
    'git tag -l "v2.4.0-rc*"',
    "cd D:/Projects/RYOS && git add ryos/__init__.py setup_cxfreeze.py && "
    'git commit -m "Release candidate 2.4.0-rc1" && git push',
    "gh run watch 123456 --exit-status",
    "cd D:/Projects/RYOS && uv run --extra mcp --with cx_Freeze python build_release.py 2>&1 | tail -8",
    "cd D:/Projects/RYOS && uv run python tests/release_check.py 2>&1 | tail -40",
    "uv run python tests/real_data_smoke.py",
    "cd D:/Projects/RYOS && git diff --stat v2.4.0-rc1..HEAD -- . ':(exclude)docs'",
    'cd D:/Projects/RYOS && git add ryos/__init__.py && git commit -m "Release 2.4.0" && git push',
    "cd D:/Projects/RYOS && rm -rf dist/* build",
    "cd D:/Projects/RYOS && uv run python tests/fixtures/db/make_fixtures.py v2.4.0",
    "cd D:/Projects/RYOS && plan=docs/plans/release-2.4.0.md\n"
    "awk -F'|' '/^## Status/{t=1} t && /^\\| [0-9]+ /{s=tolower($3); sub(/^ +/,\"\",s); "
    "if (s !~ /^(done|not needed)/) print \"OPEN: \" $2}' $plan\n"
    "grep -n -i '\\[ \\]\\|needs a human' $plan",
    "cd D:/Projects/RYOS && git mv docs/plans/release-2.4.0.md docs/archive/release-2.4.0.md\n"
    "[ -f docs/plans/release-2.4.0-brief.md ] && git mv docs/plans/release-2.4.0-brief.md "
    "docs/archive/release-2.4.0-brief.md\n"
    'grep -rnF "release-2.4.0" --include=*.md --include=*.py . | '
    'grep -v "^./docs/archive/\\|^./dist/\\|^./docs/STATUS.md"',
    "RYOS_VARIANT=agent uv run --extra mcp --with cx_Freeze python setup_cxfreeze.py build_exe",
    "uv run python tests/launch_smoke.py --cli-only dist/cxfreeze-agent/ryos-cli.exe",
    "uv run --no-project python tools/harness_checks.py version --base 5c76e95 --head HEAD",
]

RELEASE_CREATES = [
    "cd D:/Projects/RYOS && gh release create v2.4.0-rc1 dist/RYOS-windows.zip "
    "dist/RYOS-windows-ai.zip \\\n"
    "  dist/RYOS-agent.zip dist/RYOS-portable.zip dist/SHA256SUMS.txt dist/SHA256SUMS.txt.sig \\\n"
    "  -R lqvu-zen/RYOS --prerelease --latest=false --target 0123abcd \\\n"
    '  --title "v2.4.0-rc1" --notes-file "$S/notes.md" 2>&1',
    "cd D:/Projects/RYOS && gh release create v2.4.0 dist/RYOS-windows.zip "
    "dist/RYOS-windows-ai.zip \\\n"
    "  dist/RYOS-agent.zip dist/RYOS-portable.zip dist/SHA256SUMS.txt dist/SHA256SUMS.txt.sig \\\n"
    '  -R lqvu-zen/RYOS --latest --target 0123abcd --title "v2.4.0" --notes-file "$S/notes.md" 2>&1',
]


class TestGuardSkillCommands(unittest.TestCase):
    def test_every_skill_command_runs(self):
        for command in SKILL_COMMANDS:
            with self.subTest(command=command[:70]):
                result = verdict(command, secretary=dirty)
                self.assertEqual(result.kind, "allow", f"{command!r} was {result}")

    def test_publishing_a_release_asks(self):
        for command in RELEASE_CREATES:
            with self.subTest(command=command[:70]):
                self.assertEqual(verdict(command).kind, "ask")


class TestGuardMain(unittest.TestCase):
    def run_hook(self, payload: dict) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.update(ENV)
        env["CLAUDE_PROJECT_DIR"] = str(ROOT)
        return subprocess.run([sys.executable, str(GUARD_PATH)], input=json.dumps(payload),
                              capture_output=True, text=True, encoding="utf-8", env=env,
                              timeout=30)

    def test_refused_exits_2_with_the_reason(self):
        result = self.run_hook({"tool_name": "Bash", "tool_input": {"command": "uv run ryos list"}})
        self.assertEqual(result.returncode, 2)
        self.assertIn("APPDATA", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_refused_file_write(self):
        result = self.run_hook({"tool_name": "Write", "tool_input": {
            "file_path": r"C:\Users\Tester\AppData\Roaming\RYOS\settings.json", "content": "{}"}})
        self.assertEqual(result.returncode, 2)
        self.assertIn("real RYOS data", result.stderr)

    def test_allowed_is_silent(self):
        result = self.run_hook({"tool_name": "Bash", "tool_input": {
            "command": 'APPDATA="$S/a" LOCALAPPDATA="$S/l" uv run ryos list'}})
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_ask_prints_the_decision(self):
        result = self.run_hook({"tool_name": "PowerShell", "tool_input": {
            "command": "gh release delete v1 -R lqvu-zen/RYOS"}})
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PreToolUse")
        self.assertEqual(output["permissionDecision"], "ask")
        self.assertIn("gh release delete", output["permissionDecisionReason"])

    def test_a_crash_fails_open_visibly(self):
        env = dict(os.environ)
        result = subprocess.run([sys.executable, str(GUARD_PATH)], input="not json",
                                capture_output=True, text=True, encoding="utf-8", env=env,
                                timeout=30)
        self.assertEqual(result.returncode, 1)
        self.assertIn("guard.py failed", result.stderr)
        self.assertIn("not checked", result.stderr)


PLAN = """# Release 2.4.0

## Steps

### 1 — Fix

## Order

1. **Fixes** 1, 2, 3 (small, independent). Done.
2. **Harness and loop rules, before step 11** (added 2026-10-19): 31, then 32. 33 runs alongside (docs only).
3. **Part A**, the riskiest:
   1. 4 and 6 can run in parallel;
   2. then 5, 7;
   3. then **12**, the early candidate, so A gets real use for the rest of 2.4.
4. **Backlog** 13, then `step 99` (P22).

## Parallel lanes and merging

Nothing 77 here.

## Status

| Step | State |
| --- | --- |
| 1 Fix OP-15 | done: fixed |
| 2 Fix GR-33 | done: fixed |
| 3 Fix SM-16 | ✅ |
| 4 A1 Find and download | done |
| 5 A1 Background | — |
| 6 A2 Signature | done |
| 7 Vũ makes the key | — |
| 12 Early candidate | — |
| 13 Backlog | — |
| 31 Harness: permissions, hooks, checks | — |
| 32 Loop rules | — |
| 33 The plan as a graph | started 2026-10-19: Gate lines |
| 40 Not in the order | — |
"""

STATUS = """# Status

| Release | What | Plan |
|---|---|---|
| **2.3.1** (published) | fixes | `docs/archive/release-2.3.1.md` |
| **2.4** (in progress, 10 of 36 steps done) | self-update | `docs/plans/release-2.4.0.md` (approved) |

See also docs/plans/release-2.5.0.md.
"""


class TestSessionStart(unittest.TestCase):
    def test_order_from_the_plan(self):
        self.assertEqual(session_start.step_order(PLAN), [1, 2, 3, 31, 32, 33, 4, 6, 5, 7, 12, 13])

    def test_a_bold_number_and_a_sentence_final_number(self):
        plan = "## Order\n\n1. First **12**, then 40.\n2. **Part B** 41 and 7.\n"
        self.assertEqual(session_start.step_order(plan), [12, 40, 41, 7])

    def test_states_and_next_step(self):
        order = session_start.step_order(PLAN)
        states = session_start.step_states(PLAN)
        self.assertEqual(states[31], ("Harness: permissions, hooks, checks", "—"))
        self.assertEqual(session_start.next_open(order, states), 31)
        self.assertEqual(session_start.started(order, states, 31), [33])

    def test_rows_missing_from_the_order_come_last(self):
        plan = "## Order\n\n1. 1, then 2.\n\n## Status\n\n| 1 A | done |\n| 9 C | — |\n| 2 B | done |\n"
        order = session_start.step_order(plan)
        self.assertEqual(session_start.next_open(order, session_start.step_states(plan)), 9)

    def test_plan_lines(self):
        lines = session_start.plan_lines("docs/plans/release-2.4.0.md", PLAN)
        self.assertEqual(lines, [
            "Plan: docs/plans/release-2.4.0.md",
            "Next open step in Order: 31 Harness: permissions, hooks, checks",
            "Also started: 33 The plan as a graph",
        ])

    def test_fallbacks(self):
        lines = session_start.plan_lines("docs/plans/x.md", "garbage, no sections at all")
        self.assertIn("couldn't read the Order and Status of docs/plans/x.md", lines[-1])
        done = "## Order\n\n1. 1 then 2.\n\n## Status\n\n| 1 A | done |\n| 2 B | done: yes |\n"
        self.assertEqual(session_start.plan_lines("docs/plans/x.md", done)[-1],
                         "Every step of docs/plans/x.md is done.")

    def test_current_plan(self):
        self.assertEqual(session_start.current_plan(STATUS), "docs/plans/release-2.4.0.md")
        self.assertEqual(session_start.current_plan("Read docs/plans/release-9.md first."),
                         "docs/plans/release-9.md")
        self.assertIsNone(session_start.current_plan("nothing"))

    def test_ci_when_gh_is_missing(self):
        self.assertEqual(session_start.ci_line(lambda argv: None, "d900395abc", "origin/main", 1),
                         "CI: unknown (gh unavailable)")

    def test_ci_not_pushed(self):
        def answers(argv):
            if argv[:3] == ["gh", "run", "list"]:
                return "[]" if argv[4] == "d900395abc" else (
                    '[{"status": "completed", "conclusion": "success", "workflowName": "CI"}]')
            if argv == ["git", "rev-parse", "origin/main"]:
                return "ef7600d1234"
            return None

        self.assertEqual(session_start.ci_line(answers, "d900395abc", "origin/main", 1),
                         "CI on HEAD d900395: no run (not pushed). origin/main ef7600d: CI success.")

    def test_ci_success_and_in_progress(self):
        def success(argv):
            return '[{"status": "completed", "conclusion": "success", "workflowName": "CI"}]'

        def running(argv):
            return '[{"status": "in_progress", "conclusion": "", "workflowName": "CI"}]'

        self.assertEqual(session_start.ci_line(success, "abcdef123", "origin/main", 0),
                         "CI on HEAD abcdef1: CI success.")
        self.assertEqual(session_start.ci_line(running, "abcdef123", "origin/main", 0),
                         "CI on HEAD abcdef1: CI in_progress.")

    def test_nothing_runs_past_the_deadline(self):
        bounded = session_start.runner_until(100.0, clock=lambda: 100.5)
        self.assertIsNone(bounded([sys.executable, "-c", "print('ran')"]))
        bounded = session_start.runner_until(100.0, clock=lambda: 90.0)
        self.assertEqual(bounded([sys.executable, "-c", "print('ran')"]), "ran")

    def test_branch_line(self):
        self.assertEqual(session_start.branch_line(("main", "origin/main", 1, 0, "abc")),
                         "Branch: main (1 ahead of origin/main)")
        self.assertEqual(session_start.branch_line(("main", "origin/main", 0, 0, "abc")),
                         "Branch: main (up to date with origin/main)")
        self.assertEqual(session_start.branch_line(("x", "", 0, 0, "abc")), "Branch: x (no upstream)")

    def test_changes_and_secretary_line(self):
        many = "\n".join(f"?? file{i}.txt" for i in range(17))
        lines = session_start.change_lines(lambda argv: " M docs/STATUS.md\n" + many)
        self.assertEqual(lines[0], "Uncommitted (18):")
        self.assertEqual(lines[1], "   M docs/STATUS.md")
        self.assertEqual(lines[16], "  … and 3 more")
        self.assertTrue(lines[-1].startswith("Secretary edits waiting: docs/STATUS.md."))


class GitRepo:
    def __init__(self, folder: Path):
        self.folder = folder
        self.env = dict(os.environ)
        self.env.update({
            "GIT_AUTHOR_NAME": "Tester", "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "Tester", "GIT_COMMITTER_EMAIL": "t@example.com",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
        })
        self.git("init", "-q", "-b", "main")

    def git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false", *args],
            cwd=self.folder, capture_output=True, text=True, encoding="utf-8", env=self.env)
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        return result.stdout.strip()

    def commit(self, title: str, files: dict[str, str | None]) -> str:
        for name, body in files.items():
            path = self.folder / name
            if body is None:
                path.unlink()
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8", newline="\n")
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", title)
        return self.git("rev-parse", "HEAD")


def init_file(version: str) -> str:
    return f'"""RYOS."""\n\n__version__ = "{version}"\n'


def setup_file(version: str) -> str:
    return f'setup(\n    name="RYOS",\n        version="{version}",\n)\n'


class _RepoCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ryos-harness-"))
        self.repo = GitRepo(self.tmp)
        self.root = self.repo.commit("Initial", {
            "ryos/__init__.py": init_file("2.3.1"),
            "setup_cxfreeze.py": setup_file("2.3.1"),
            "ryos/a.py": "def a():\n    return 1  # keeps one\n",
        })

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestVersionCheck(_RepoCase):
    def problems(self, base: str | None = None, head: str = "HEAD") -> list[str]:
        return harness_checks.version_problems(str(self.tmp), base or self.root, head)

    def test_the_release_titles_match(self):
        match = harness_checks.RELEASE_TITLE.match
        self.assertEqual(match("Release candidate 2.3.1-rc1").group(1), "2.3.1-rc1")
        self.assertEqual(match("Release 2.3.1").group(2), "2.3.1")
        self.assertIsNone(match("Release 2.3.1 and a fix"))
        self.assertIsNone(match("feat: Release 2.3.1"))

    def test_a_feature_commit_bumping_the_version_fails(self):
        sha = self.repo.commit("feat: x", {"ryos/__init__.py": init_file("2.3.2")})
        problems = self.problems()
        self.assertEqual(len(problems), 1)
        self.assertIn(f'{sha[:7]} "feat: x" changes __version__ 2.3.1 -> 2.3.2', problems[0])
        self.assertIn("(CLAUDE.md, Versions)", problems[0])

    def test_a_title_that_does_not_match_the_version_fails(self):
        self.repo.commit("Release 2.4.0", {"ryos/__init__.py": init_file("2.4.1")})
        self.assertIn("sets __version__ to 2.4.1, not 2.4.0", self.problems()[0])

    def test_setup_alone_in_a_feature_commit_fails(self):
        self.repo.commit("feat: y", {"setup_cxfreeze.py": setup_file("2.4.0")})
        self.assertIn("changes setup_cxfreeze.py version 2.3.1 -> 2.4.0", self.problems()[0])

    def test_reverting_a_release_fails(self):
        self.repo.commit("Release 2.4.0", {"ryos/__init__.py": init_file("2.4.0")})
        self.repo.commit('Revert "Release 2.4.0"', {"ryos/__init__.py": init_file("2.3.1")})
        problems = self.problems()
        self.assertEqual(len(problems), 1)
        self.assertIn('Revert', problems[0])

    def test_clean_and_release_commits_pass(self):
        self.repo.commit("feat: clean", {"ryos/a.py": "def a():\n    return 2  # keeps one\n"})
        self.repo.commit("Release candidate 2.4.0-rc1", {
            "ryos/__init__.py": init_file("2.4.0-rc1"), "setup_cxfreeze.py": setup_file("2.4.0")})
        self.repo.commit("Release 2.4.0", {"ryos/__init__.py": init_file("2.4.0")})
        self.assertEqual(self.problems(), [])

    def test_a_candidate_with_the_rc_in_setup_fails(self):
        self.repo.commit("Release candidate 2.4.0-rc1", {
            "ryos/__init__.py": init_file("2.4.0-rc1"), "setup_cxfreeze.py": setup_file("2.4.0-rc1")})
        self.assertIn("sets setup_cxfreeze.py version to 2.4.0-rc1, not 2.4.0", self.problems()[0])

    def test_without_a_base_it_starts_from_origin_main(self):
        bad = self.repo.commit("feat: bump", {"ryos/__init__.py": init_file("2.3.2")})
        self.repo.git("update-ref", "refs/remotes/origin/main", bad)
        self.repo.commit("feat: clean", {"ryos/a.py": "x = 1\n"})
        repo = str(self.tmp)
        self.assertEqual(harness_checks.version_problems(repo, "0" * 40, "HEAD"), [])
        self.assertEqual(harness_checks.version_problems(repo, "12" * 20, "HEAD"), [])
        self.assertEqual(harness_checks.version_problems(repo, None, "HEAD"), [])
        self.assertEqual(len(harness_checks.version_problems(repo, self.root, "HEAD")), 1)

    def test_with_origin_main_at_head_it_checks_the_last_commit(self):
        self.repo.commit("feat: bump", {"ryos/__init__.py": init_file("2.3.2")})
        self.repo.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.assertEqual(len(harness_checks.version_problems(str(self.tmp), "0" * 40, "HEAD")), 1)

    def test_merges_are_skipped(self):
        self.repo.git("checkout", "-q", "-b", "rel")
        self.repo.commit("Release 2.4.0", {"ryos/__init__.py": init_file("2.4.0")})
        self.repo.git("checkout", "-q", "main")
        self.repo.commit("feat: other", {"ryos/b.py": "x = 1\n"})
        self.repo.git("merge", "-q", "--no-ff", "-m", "Merge branch rel", "rel")
        merge = self.repo.git("rev-parse", "HEAD")
        self.assertNotIn(merge, harness_checks.commits_in(str(self.tmp), self.root, "HEAD"))
        self.assertEqual(self.problems(), [])

    def test_main_reports_and_exits(self):
        self.repo.commit("feat: x", {"ryos/__init__.py": init_file("2.3.2")})
        result = subprocess.run([sys.executable, str(CHECKS_PATH), "version", "--base", self.root,
                                 "--head", "HEAD", "--repo", str(self.tmp)],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 1)
        self.assertIn("changes __version__", result.stdout)
        result = subprocess.run([sys.executable, str(CHECKS_PATH), "comments", "--base", self.root,
                                 "--head", "HEAD", "--repo", str(self.tmp)],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "comments: ok (1 commits)"))


class TestCommentCheck(_RepoCase):
    def problems(self) -> list[str]:
        return harness_checks.comment_problems(str(self.tmp), self.root, "HEAD")

    def test_a_full_line_comment_fails(self):
        self.repo.commit("feat", {"ryos/a.py": "def a():\n    # why\n    return 1  # keeps one\n"})
        self.assertEqual(self.problems(),
                         ['ryos/a.py:2: new comment "# why" (CLAUDE.md, Code Style)'])

    def test_a_trailing_comment_fails(self):
        self.repo.commit("feat", {"ryos/a.py": "def a():\n    return 1  # keeps one\nb = 2  # two\n"})
        self.assertEqual(len(self.problems()), 1)
        self.assertIn("ryos/a.py:3", self.problems()[0])

    def test_a_new_file_with_a_comment_fails(self):
        self.repo.commit("feat", {"ryos/c.py": "x = 1\n# note\n"})
        self.assertIn('ryos/c.py:2: new comment "# note"', self.problems()[0])

    def test_a_file_that_does_not_tokenize_fails(self):
        self.repo.commit("feat", {"ryos/c.py": 'x = """never closed\n'})
        self.assertIn("ryos/c.py: could not read its tokens", self.problems()[0])

    def test_what_is_not_a_new_comment_passes(self):
        self.repo.commit("feat", {
            "ryos/a.py": "def a():\n    return 1\n",
            "ryos/b.py": "def b():\n    return 1  # keeps one\n",
            "ryos/c.py": "#!/usr/bin/env python\n# -*- coding: utf-8 -*-\n"
                         'import os  # noqa: E402\nx = "# not a comment"\n'
                         'y = 1  # type: ignore[assignment]\n\n\ndef f():\n    """A docstring."""\n',
            "tests/x.py": "# a comment in tests\n",
        })
        self.assertEqual(self.problems(), [])

    def test_a_rewritten_line_keeping_its_comment_passes(self):
        self.repo.commit("feat", {"ryos/a.py": "def a():\n    return 2  # keeps one\n"})
        self.assertEqual(self.problems(), [])


if __name__ == "__main__":
    unittest.main()
