"""Small, dependency-free parsing helpers shared by the tools and the baseline.

Everything here works on a plain list of log lines and returns 1-based line
numbers, because 1-based line numbers are the currency of this whole project:
they are what the model cites, what ground truth records, and what the
evidence check validates against.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

STATE_RE = re.compile(r"State:\s+([A-Z0-9_]+)\s+->\s+([A-Z0-9_]+)")
CTRL_EVENT_RE = re.compile(r"(CTRL-EVENT-[A-Z0-9-]+)")
REASON_RE = re.compile(r"reason=(\d+)|Reason:\s*(\d+)")
STATUS_RE = re.compile(r"status_code=(\d+)|\bstatus=(\d+)")
SIGNAL_RE = re.compile(r"signal=(-?\d+)")


@dataclass(frozen=True)
class Transition:
    line_no: int
    frm: str
    to: str
    text: str


def split_lines(log: str) -> list[str]:
    """Split a log into lines, dropping a single trailing newline only."""
    return log.split("\n") if not log.endswith("\n") else log[:-1].split("\n")


def transitions(lines: list[str]) -> list[Transition]:
    out: list[Transition] = []
    for i, line in enumerate(lines, start=1):
        m = STATE_RE.search(line)
        if m:
            out.append(Transition(i, m.group(1), m.group(2), line.strip()))
    return out


def ctrl_events(lines: list[str]) -> list[tuple[int, str, str]]:
    """Return (line_no, event_name, full_line) for every CTRL-EVENT-* line."""
    out = []
    for i, line in enumerate(lines, start=1):
        m = CTRL_EVENT_RE.search(line)
        if m:
            out.append((i, m.group(1), line.strip()))
    return out


def find(
    lines: list[str], pattern: str, *, max_hits: int = 20, ignore_case: bool = True
) -> list[tuple[int, str]]:
    """Regex search returning up to ``max_hits`` (line_no, text) pairs.

    Invalid regexes are not an error the model should have to reason about, so
    a bad pattern falls back to a literal substring search.
    """
    flags = re.IGNORECASE if ignore_case else 0
    try:
        rx = re.compile(pattern, flags)
        match = rx.search
    except re.error:
        needle = pattern.lower() if ignore_case else pattern

        def match(s: str):  # type: ignore[misc]
            return (needle in (s.lower() if ignore_case else s)) or None

    hits: list[tuple[int, str]] = []
    for i, line in enumerate(lines, start=1):
        if match(line):
            hits.append((i, line.strip()))
            if len(hits) >= max_hits:
                break
    return hits


def last_signal(lines: list[str]) -> int | None:
    vals = [int(m.group(1)) for line in lines if (m := SIGNAL_RE.search(line))]
    return vals[-1] if vals else None


def min_signal(lines: list[str]) -> int | None:
    vals = [int(m.group(1)) for line in lines if (m := SIGNAL_RE.search(line))]
    return min(vals) if vals else None


def truncate_for_prompt(
    lines: list[str], max_lines: int = 2000, keep_window: int = 6
) -> tuple[list[int], list[str]]:
    """Reduce a long log to at most ``max_lines`` lines, keeping what matters.

    Returns ``(kept_line_numbers, kept_lines)``. Line numbers are preserved so
    citations still refer to the original log. Priority order: state
    transitions and CTRL-EVENT lines plus a window around each, then error-ish
    lines, then head and tail, then whatever fits.
    """
    n = len(lines)
    if n <= max_lines:
        return list(range(1, n + 1)), lines

    keep: set[int] = set()
    anchors = [t.line_no for t in transitions(lines)] + [i for i, _, _ in ctrl_events(lines)]
    for a in anchors:
        keep.update(range(max(1, a - keep_window), min(n, a + keep_window) + 1))
    if len(keep) < max_lines:
        err = re.compile(
            r"fail|timeout|reject|deauth|disassoc|error|warn|no lease|No DHCPOFFERS", re.IGNORECASE
        )
        for i, line in enumerate(lines, start=1):
            if err.search(line):
                keep.add(i)
    keep.update(range(1, min(30, n) + 1))
    keep.update(range(max(1, n - 29), n + 1))
    if len(keep) > max_lines:
        # Drop from the middle first: keep anchors nearest the end of the log,
        # which is where the failure usually is.
        ordered = sorted(keep, reverse=True)[:max_lines]
        keep = set(ordered)
    elif len(keep) < max_lines:
        for i in range(1, n + 1):
            if len(keep) >= max_lines:
                break
            keep.add(i)
    nums = sorted(keep)
    return nums, [lines[i - 1] for i in nums]
