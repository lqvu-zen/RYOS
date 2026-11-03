from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
import tokenize
from collections import Counter
from typing import Any, Mapping, NamedTuple

RELEASE_TITLE = re.compile(r"^Release candidate (\d+\.\d+\.\d+-rc\d+)$|^Release (\d+\.\d+\.\d+)$")
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
VERSIONS_RULE = "(.claude/devflow.md, Release)"
COMMENTS_RULE = "(.claude/devflow.md, Architecture rules)"
DIRECTIVE = re.compile(r"#\s*(noqa|type:\s*ignore|pragma|pyright:|mypy:|ruff:|fmt:)", re.IGNORECASE)
CODING = re.compile(r"^#.*coding[:=]\s*[-\w.]+")
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class GitError(Exception):
    pass


class VersionFile(NamedTuple):
    path: str
    pattern: re.Pattern
    numbers_only: bool


class Checks(NamedTuple):
    version_files: tuple[VersionFile, ...]
    comment_dirs: tuple[str, ...]
    default_base: str


def checks_from(config: Mapping[str, Any]) -> Checks:
    section = config.get("checks") if isinstance(config.get("checks"), Mapping) else {}
    files: list[VersionFile] = []
    for item in section.get("version_files") or []:
        if isinstance(item, Mapping) and isinstance(item.get("path"), str) \
                and isinstance(item.get("pattern"), str):
            files.append(VersionFile(item["path"], re.compile(item["pattern"], re.MULTILINE),
                                     bool(item.get("numbers_only"))))
    dirs = tuple(d.replace("\\", "/") for d in section.get("no_new_python_comments") or []
                 if isinstance(d, str) and d)
    branch = config.get("main_branch") if isinstance(config.get("main_branch"), str) else "main"
    return Checks(tuple(files), dirs, f"origin/{branch}")


def load_config(repo: str) -> dict:
    path = os.path.join(repo, ".claude", "devflow.json")
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must hold a JSON object")
    return data


def git(repo: str, *args: str) -> str:
    result = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def _sha(repo: str, ref: str) -> str | None:
    try:
        return git(repo, "rev-parse", "--verify", "--quiet", ref + "^{commit}").strip() or None
    except GitError:
        return None


def _merge_base(repo: str, a: str, b: str) -> str | None:
    try:
        return git(repo, "merge-base", a, b).strip() or None
    except GitError:
        return None


def commit_range(repo: str, base: str | None, head: str, default: str = "origin/main") -> str | None:
    head_sha = _sha(repo, head)
    if head_sha is None:
        raise GitError(f"unknown head {head}")
    if base and base.strip("0") and _sha(repo, base):
        start = _merge_base(repo, base, head_sha)
        if start:
            return start
    start = _merge_base(repo, default, head_sha) if _sha(repo, default) else None
    if start and start != head_sha:
        return start
    return _sha(repo, head_sha + "^")


def commits_in(repo: str, start: str | None, head: str) -> list[str]:
    span = f"{start}..{head}" if start else head
    return git(repo, "rev-list", "--no-merges", "--reverse", span).split()


def version_of(text: str, file: VersionFile) -> str | None:
    match = file.pattern.search(text)
    return match.group(1) if match else None


def _show(repo: str, ref: str) -> str | None:
    try:
        return git(repo, "show", ref)
    except GitError:
        return None


def version_changes(repo: str, commit: str,
                    files: tuple[VersionFile, ...]) -> dict[str, tuple[str | None, str | None]]:
    paths = [f.path for f in files]
    touched = set(git(repo, "diff-tree", "--root", "--no-commit-id", "--name-only", "-r",
                      commit, "--", *paths).split())
    changes: dict[str, tuple[str | None, str | None]] = {}
    for file in files:
        if file.path not in touched:
            continue
        old_text = _show(repo, f"{commit}^:{file.path}")
        new_text = _show(repo, f"{commit}:{file.path}")
        old = version_of(old_text, file) if old_text is not None else None
        new = version_of(new_text, file) if new_text is not None else None
        if old != new:
            changes[file.path] = (old, new)
    return changes


def _title(repo: str, commit: str) -> str:
    return git(repo, "log", "-1", "--format=%s", commit).strip()


def _short_title(title: str) -> str:
    return title if len(title) <= 50 else title[:49] + "…"


def _release_problem(repo: str, commit: str, label: str, file: VersionFile, expected: str,
                     changed: bool) -> str | None:
    text = _show(repo, f"{commit}:{file.path}")
    if text is None:
        return f"{label} has no {file.path}; it should say {expected} {VERSIONS_RULE}"
    value = version_of(text, file)
    if value is None:
        return (f"{label} has no version in {file.path} that its pattern matches; it should say "
                f"{expected} {VERSIONS_RULE}")
    if value == expected:
        return None
    if changed:
        return f"{label} sets the version in {file.path} to {value}, not {expected} {VERSIONS_RULE}"
    return f"{label} leaves the version in {file.path} at {value}, not {expected} {VERSIONS_RULE}"


def version_problems_in(repo: str, commits: list[str],
                        files: tuple[VersionFile, ...]) -> list[str]:
    if not files:
        return []
    problems: list[str] = []
    for commit in commits:
        changes = version_changes(repo, commit, files)
        title = _title(repo, commit)
        match = RELEASE_TITLE.match(title)
        label = f'{commit[:7]} "{_short_title(title)}"'
        if not match:
            if not changes:
                continue
            for path, (old, new) in changes.items():
                problems.append(f'{label} changes the version in {path} {old} -> {new}: only '
                                f'"Release candidate X.Y.Z-rcN" or "Release X.Y.Z" may '
                                f'{VERSIONS_RULE}')
            continue
        wanted = match.group(1) or match.group(2)
        numbers = re.sub(r"-rc\d+$", "", wanted)
        for file in files:
            expected = numbers if file.numbers_only else wanted
            problem = _release_problem(repo, commit, label, file, expected, file.path in changes)
            if problem:
                problems.append(problem)
    return problems


def comment_tokens(source: str) -> list[tuple[int, str]]:
    found = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            found.append((token.start[0], token.string))
    return found


def is_directive(text: str, line: int) -> bool:
    if line == 1 and text.startswith("#!"):
        return True
    if line <= 2 and CODING.match(text):
        return True
    return bool(DIRECTIVE.match(text))


def _hunks(diff: str) -> tuple[set[int], set[int]]:
    removed: set[int] = set()
    added: set[int] = set()
    for line in diff.splitlines():
        match = HUNK.match(line)
        if not match:
            continue
        old_start, old_count = int(match.group(1)), int(match.group(2) or "1")
        new_start, new_count = int(match.group(3)), int(match.group(4) or "1")
        removed.update(range(old_start, old_start + old_count))
        added.update(range(new_start, new_start + new_count))
    return removed, added


def _diff_lines(repo: str, start: str | None, head: str, path: str) -> tuple[set[int], set[int]]:
    diff = git(repo, "diff", "-U0", "--no-renames", start or EMPTY_TREE, head, "--", path)
    return _hunks(diff)


def _changed_python(repo: str, start: str | None, head: str) -> list[tuple[str, str]]:
    out = git(repo, "diff", "--name-status", "--no-renames", start or EMPTY_TREE, head)
    changed = []
    for line in out.splitlines():
        status, _, path = line.partition("\t")
        if path.endswith(".py"):
            changed.append((status[:1], path))
    return changed


def comment_problems_in(repo: str, start: str | None, head: str,
                        dirs: tuple[str, ...]) -> list[str]:
    if not dirs:
        return []
    changed = _changed_python(repo, start, head)
    removed: Counter[str] = Counter()
    if start:
        for status, path in changed:
            if status not in ("M", "D"):
                continue
            old = _show(repo, f"{start}:{path}")
            if old is None:
                continue
            lines = _diff_lines(repo, start, head, path)[0]
            try:
                tokens = comment_tokens(old)
            except (tokenize.TokenError, SyntaxError):
                continue
            removed.update(text.strip() for line, text in tokens if line in lines)
    problems: list[str] = []
    for status, path in changed:
        if status not in ("A", "M") or not path.startswith(dirs):
            continue
        new = _show(repo, f"{head}:{path}")
        if new is None:
            continue
        lines = _diff_lines(repo, start, head, path)[1]
        try:
            tokens = comment_tokens(new)
        except (tokenize.TokenError, SyntaxError) as error:
            problems.append(f"{path}: could not read its tokens ({error})")
            continue
        for line, text in tokens:
            if line not in lines or is_directive(text, line):
                continue
            key = text.strip()
            if removed[key] > 0:
                removed[key] -= 1
                continue
            problems.append(f'{path}:{line}: new comment "{key}" {COMMENTS_RULE}')
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="devflow process checks for CI.")
    parser.add_argument("check", choices=("version", "comments"))
    parser.add_argument("--base", default="")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--repo", default=".")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        checks = checks_from(load_config(args.repo))
        start = commit_range(args.repo, args.base or None, args.head, checks.default_base)
        commits = commits_in(args.repo, start, args.head)
        if args.check == "version":
            problems = version_problems_in(args.repo, commits, checks.version_files)
        else:
            problems = comment_problems_in(args.repo, start, args.head, checks.comment_dirs)
    except (GitError, OSError, ValueError) as error:
        print(f"devflow_checks {args.check}: {error}")
        return 1
    for problem in problems:
        print(problem)
    if problems:
        return 1
    print(f"{args.check}: ok ({len(commits)} commits)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
