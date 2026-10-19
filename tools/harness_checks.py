from __future__ import annotations

import argparse
import io
import re
import subprocess
import sys
import tokenize
from collections import Counter

RELEASE_TITLE = re.compile(r"^Release candidate (\d+\.\d+\.\d+-rc\d+)$|^Release (\d+\.\d+\.\d+)$")
INIT = "ryos/__init__.py"
SETUP = "setup_cxfreeze.py"
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
VERSIONS_RULE = '(CLAUDE.md, Versions)'
DIRECTIVE = re.compile(r"#\s*(noqa|type:\s*ignore|pragma|pyright:|mypy:|ruff:|fmt:)", re.IGNORECASE)
CODING = re.compile(r"^#.*coding[:=]\s*[-\w.]+")
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class GitError(Exception):
    pass


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


def version_of(text: str, path: str) -> str | None:
    if path == INIT:
        match = re.search(r'^__version__ = "([^"]+)"', text, re.MULTILINE)
    else:
        match = re.search(r'^\s*version="([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else None


def _show(repo: str, ref: str) -> str | None:
    try:
        return git(repo, "show", ref)
    except GitError:
        return None


def version_changes(repo: str, commit: str) -> dict[str, tuple[str | None, str | None]]:
    touched = set(git(repo, "diff-tree", "--root", "--no-commit-id", "--name-only", "-r",
                      commit, "--", INIT, SETUP).split())
    changes: dict[str, tuple[str | None, str | None]] = {}
    for path in (INIT, SETUP):
        if path not in touched:
            continue
        old_text = _show(repo, f"{commit}^:{path}")
        new_text = _show(repo, f"{commit}:{path}")
        old = version_of(old_text, path) if old_text is not None else None
        new = version_of(new_text, path) if new_text is not None else None
        if old != new:
            changes[path] = (old, new)
    return changes


def _title(repo: str, commit: str) -> str:
    return git(repo, "log", "-1", "--format=%s", commit).strip()


def _short_title(title: str) -> str:
    return title if len(title) <= 50 else title[:49] + "…"


def version_problems_in(repo: str, commits: list[str]) -> list[str]:
    problems: list[str] = []
    for commit in commits:
        changes = version_changes(repo, commit)
        if not changes:
            continue
        title = _title(repo, commit)
        match = RELEASE_TITLE.match(title)
        label = f'{commit[:7]} "{_short_title(title)}"'
        if not match:
            for path, (old, new) in changes.items():
                what = "__version__" if path == INIT else f"{SETUP} version"
                problems.append(f'{label} changes {what} {old} -> {new}: only "Release candidate '
                                f'X.Y.Z-rcN" or "Release X.Y.Z" may {VERSIONS_RULE}')
            continue
        wanted = match.group(1) or match.group(2)
        if INIT in changes and changes[INIT][1] != wanted:
            problems.append(f"{label} sets __version__ to {changes[INIT][1]}, not {wanted} "
                            f"{VERSIONS_RULE}")
        numbers = re.sub(r"-rc\d+$", "", wanted)
        if SETUP in changes and changes[SETUP][1] != numbers:
            problems.append(f"{label} sets {SETUP} version to {changes[SETUP][1]}, not {numbers} "
                            f"{VERSIONS_RULE}")
    return problems


def version_problems(repo: str, base: str | None, head: str) -> list[str]:
    start = commit_range(repo, base, head)
    return version_problems_in(repo, commits_in(repo, start, head))


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


def added_lines(repo: str, start: str | None, head: str, path: str) -> set[int]:
    diff = git(repo, "diff", "-U0", "--no-renames", start or EMPTY_TREE, head, "--", path)
    return _hunks(diff)[1]


def _removed_lines(repo: str, start: str | None, head: str, path: str) -> set[int]:
    diff = git(repo, "diff", "-U0", "--no-renames", start or EMPTY_TREE, head, "--", path)
    return _hunks(diff)[0]


def _changed_python(repo: str, start: str | None, head: str) -> list[tuple[str, str]]:
    out = git(repo, "diff", "--name-status", "--no-renames", start or EMPTY_TREE, head)
    changed = []
    for line in out.splitlines():
        status, _, path = line.partition("\t")
        if path.endswith(".py"):
            changed.append((status[:1], path))
    return changed


def comment_problems_in(repo: str, start: str | None, head: str) -> list[str]:
    changed = _changed_python(repo, start, head)
    removed: Counter[str] = Counter()
    if start:
        for status, path in changed:
            if status not in ("M", "D"):
                continue
            old = _show(repo, f"{start}:{path}")
            if old is None:
                continue
            lines = _removed_lines(repo, start, head, path)
            try:
                tokens = comment_tokens(old)
            except (tokenize.TokenError, SyntaxError):
                continue
            removed.update(text.strip() for line, text in tokens if line in lines)
    problems: list[str] = []
    for status, path in changed:
        if status not in ("A", "M") or not path.startswith("ryos/"):
            continue
        new = _show(repo, f"{head}:{path}")
        if new is None:
            continue
        lines = added_lines(repo, start, head, path)
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
            problems.append(f'{path}:{line}: new comment "{key}" (CLAUDE.md, Code Style)')
    return problems


def comment_problems(repo: str, base: str | None, head: str) -> list[str]:
    start = commit_range(repo, base, head)
    return comment_problems_in(repo, start, head)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RYOS harness checks for CI.")
    parser.add_argument("check", choices=("version", "comments"))
    parser.add_argument("--base", default="")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--repo", default=".")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        start = commit_range(args.repo, args.base or None, args.head)
        count = len(commits_in(args.repo, start, args.head))
        if args.check == "version":
            problems = version_problems(args.repo, args.base or None, args.head)
        else:
            problems = comment_problems(args.repo, args.base or None, args.head)
    except GitError as error:
        print(f"harness_checks {args.check}: {error}")
        return 1
    for problem in problems:
        print(problem)
    if problems:
        return 1
    print(f"{args.check}: ok ({count} commits)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
