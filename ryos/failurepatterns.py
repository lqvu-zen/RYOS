"""Failure patterns: a script's rules for failing a run by what it prints.

A run whose output has a line matching one of its script's patterns is
failed, even when its exit code is 0. The rules are the script's own regular
expressions (Python ``re``, searched anywhere in a line, case-sensitive) and,
when ticked, the common set. Matching happens in the run's reader thread, so
this module stays free of any toolkit and of the queue.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .logger import get_logger

_log = get_logger("failurepatterns")

COMMON_PATTERNS = ("error:", "FAILED", "Traceback")
MAX_MATCH_CHARS = 1000
MAX_SHOWN_CHARS = 300

_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


@dataclass(frozen=True)
class Rule:
    pattern: str
    common: bool
    regex: re.Pattern


def compile_rules(patterns, use_common: bool) -> tuple[Rule, ...]:
    """The script's own patterns in order, then the common set when ticked.
    A blank or broken pattern is skipped with a warning, never raised."""
    rules: list[Rule] = []
    for pattern in patterns or ():
        if not pattern or not pattern.strip():
            continue
        try:
            rules.append(Rule(pattern, False, re.compile(pattern)))
        except re.error as e:
            _log.warning("Skipping failure pattern %r: %s", pattern, e)
    if use_common:
        rules.extend(Rule(p, True, re.compile(re.escape(p))) for p in COMMON_PATTERNS)
    return tuple(rules)


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text) if "\x1b" in text else text


@dataclass(frozen=True)
class Hit:
    rule: str
    common: bool
    line: str
    line_no: int

    def as_dict(self) -> dict:
        return {"rule": self.rule, "common": self.common, "line": self.line,
                "line_no": self.line_no}


def _shown(line: str) -> str:
    line = strip_ansi(line).rstrip()
    return line if len(line) <= MAX_SHOWN_CHARS else line[:MAX_SHOWN_CHARS] + "…"


class Watch:
    """One attempt's matcher: fed every line, keeps the first hit."""

    def __init__(self, rules) -> None:
        self.rules = tuple(rules)
        self.lines = 0
        self.hit: Hit | None = None

    def feed(self, line: str) -> None:
        self.lines += 1
        if self.hit is not None:
            return
        text = strip_ansi(line[:MAX_MATCH_CHARS])
        for rule in self.rules:
            if rule.regex.search(text):
                self.hit = Hit(rule.pattern, rule.common, _shown(line), self.lines)
                return


def to_json(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False)


def from_json(text) -> dict | None:
    """The stored reason, or None when there is none or it is unreadable."""
    if not text:
        return None
    try:
        d = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(d, dict) or not isinstance(d.get("rule"), str):
        return None
    return d


def describe(d: dict) -> str:
    """'matched "error:" (common pattern) on line 12: gcc: error: x'"""
    kind = " (common pattern)" if d.get("common") else ""
    return (f'matched "{d.get("rule", "")}"{kind} on line '
            f'{d.get("line_no", "?")}: {d.get("line", "")}')


def footer_line(d: dict) -> str:
    return "  ✗ " + describe(d) + "\n"
