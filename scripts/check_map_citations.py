"""Fail when a verified map card cites a file or line that is not there (ICM A3).

Cards under map/objects/, map/processes/ and map/effects/ cite source as `path` or `path:line[-line]`. A
verified card that is silently wrong costs more than a missing one, so this
checks every citation in every `status: verified` card:

- the path resolves to a tracked file (as written, under weebot/, or as the
  unique tracked file ending with it, since cards use short forms);
- a cited line is within the file.

It does not check that the line still says what the card claims; re-verify
cards against source for that (map/_meta/schema.md).

Usage: python scripts/check_map_citations.py   (exit 1 on any broken citation)
"""

from __future__ import annotations

import re
from datetime import date
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_CITE = re.compile(
    r"`([\w./\\\-\[\]]+\.(?:py|tsx|ts|mjs|json|toml|yml|yaml))"
    # groups 2-5: first line, separator ("-" range or "," list), second line, tail of `a, b-c`
    r"(?::(\d+)(?:([-,])\s?(\d+))?(?:-(\d+))?)?"
)

# `--fix` rewrites a citation whose cited text is gone to `path:[stale N]`, keeping the old number
# where a person can see it and where no line check can mistake it for a current citation.
_STALE_MARK = re.compile(r"`([^`\s]+):\[stale ([^\]]*)\]")
# A bare `:N` ("the file cited before"). Nothing can check it: the drift check reads only
# `path:N`, yet `--fix` restamps the card, so a bare number into a moved file went wrong while
# the card claimed HEAD. Guessing the file was measured wrong too often, so it is rejected.
_BARE = re.compile(r"`(:\d[\d, -]*)`")


def _tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    return out.stdout.splitlines()


def _resolve(path: str, tracked: list[str], tracked_set: set[str]) -> str | None:
    path = path.replace("\\", "/")
    while path.startswith("./"):  # not lstrip("./"): that also ate the dot of .github
        path = path[2:]
    for candidate in (path, f"weebot/{path}"):
        if candidate in tracked_set:
            return candidate
    hits = [t for t in tracked if t.endswith("/" + path)]
    return hits[0] if len(hits) == 1 else None


def _cards() -> list[Path]:
    """Object, process and effects cards: the files with a `status` and a `commit` to check."""
    return sorted(
        p for sub in ("objects", "processes", "effects") for p in (ROOT / "map" / sub).rglob("*.md")
    )


def broken_citations() -> list[str]:
    tracked = _tracked()
    tracked_set = set(tracked)
    lengths: dict[str, int] = {}
    problems: list[str] = []
    for card in _cards():
        if card.name in ("_index.md", "CONTEXT.md"):
            continue
        text = card.read_text(encoding="utf-8")
        if "status: verified" not in text:
            continue
        rel = card.relative_to(ROOT).as_posix()
        for mark in _STALE_MARK.finditer(text):
            problems.append(
                f"{rel}: unresolved stale citation {mark.group(1)}:[stale {mark.group(2)}]"
            )
        for bare in _BARE.finditer(text):
            line = text.count("\n", 0, bare.start()) + 1
            problems.append(f"{rel}:{line}: bare citation `{bare.group(1)}`: write the file path")
        for m in _CITE.finditer(text):
            path, first, last = m.group(1), m.group(2), m.group(5) or m.group(4)
            resolved = _resolve(path, tracked, tracked_set)
            if resolved is None:
                if "/" in path:  # a bare file name ("config.py") is prose, not a citation
                    problems.append(f"{rel}: {path} is not a tracked file")
                continue
            if first:
                if resolved not in lengths:
                    lengths[resolved] = sum(
                        1 for _ in (ROOT / resolved).open(encoding="utf-8", errors="ignore")
                    )
                line = int(last or first)
                if line > lengths[resolved]:
                    problems.append(
                        f"{rel}: {path}:{line} is past the end ({lengths[resolved]} lines)"
                    )
    return problems


def _lines_at(rev: str, path: str, cache: dict) -> list[str] | None:
    if (rev, path) not in cache:
        out = subprocess.run(
            ["git", "show", f"{rev}:{path}"], cwd=ROOT, capture_output=True,
            text=True, encoding="utf-8", errors="ignore",
        )
        cache[(rev, path)] = out.stdout.splitlines() if out.returncode == 0 else None
    return cache[(rev, path)]


def _commit_exists(rev: str) -> bool:
    done = subprocess.run(["git", "cat-file", "-e", f"{rev}^{{commit}}"], cwd=ROOT,
                          capture_output=True)
    return done.returncode == 0


def _stale_mark(m: re.Match) -> str:
    """`path:[stale N]`: the citation as written, set aside until a person re-reads it."""
    return f"{m.group(1)}:[stale {m.group(0)[len(m.group(1)) + 2:]}]"


def _relocate(block: list[str], new: list[str], old_start: int) -> int | None:
    """1-based start of *block* in *new*, nearest to *old_start*; None if absent."""
    n = len(block)
    starts = [i + 1 for i in range(len(new) - n + 1) if new[i:i + n] == block]
    return min(starts, key=lambda s: abs(s - old_start)) if starts else None


def drifted_citations(fix: bool = False) -> list[str]:
    """Citations whose lines no longer say what they said at the card's `commit`.

    A shift (same text, new line numbers) is fixable: with *fix*, the card's
    numbers are rewritten and, when every citation then holds, its commit and
    date move to HEAD. Text that is gone needs a human re-read: *fix* marks
    that card `stale` and the citation is reported.

    The premise is that the citation was CORRECT at the card's `commit`. When it was
    not -- someone rewrote the citation without advancing `commit:`, which nothing
    detects -- the "moved" answer is a relocation of whatever unrelated text sat at
    that line in the baseline, and it looks exactly as confident as a real one. That
    is how `FlowRouter.md` came to cite `plan_act_flow.py:661` while declaring
    `commit: 50a5d748`, a commit where 661 held `elif isinstance(initial_state,
    PlanningState):` rather than the `get_last_plan()` the claim named. Reproduced
    2026-10-25: `--fix` wanted to relocate a correct citation to a line holding an
    unrelated block.

    So after a heavy refactor, READ the moves before accepting them, and prefer
    repointing each citation at the construct its claim names. See `map/CLAUDE.md`.
    """
    tracked = _tracked()
    tracked_set = set(tracked)
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True, check=True).stdout.strip()
    cache: dict = {}
    problems: list[str] = []
    for card in _cards():
        text = card.read_text(encoding="utf-8")
        commit = re.search(r"^commit:\s*([0-9a-f]{7,40})\b", text, re.M)
        if "status: verified" not in text or not commit:
            continue
        rel = card.relative_to(ROOT).as_posix()
        if not _commit_exists(commit.group(1)):
            # Without it every citation of the card would be skipped and the gate would pass.
            problems.append(f"{rel}: commit {commit.group(1)} is not in this clone "
                            "(shallow checkout?); its citations were not checked")
            continue
        edits: list[tuple[int, int, str]] = []
        gone: list[str] = []
        for m in _CITE.finditer(text):
            if not m.group(2):
                continue
            resolved = _resolve(m.group(1), tracked, tracked_set)
            old = _lines_at(commit.group(1), resolved, cache) if resolved else None
            new = _lines_at("HEAD", resolved, cache) if resolved else None
            if new is None:
                continue  # not committed yet: nothing to compare against
            if old is None:
                gone.append(f"{rel}: {m.group(1)} did not exist at {commit.group(1)}")
                edits.append((m.start(1), m.end(), _stale_mark(m)))
                continue
            first = int(m.group(2))
            # "a-b" is a range; "a, b" two lines; "a, b-c" a line and a range.
            second = int(m.group(4)) if m.group(4) else None
            if m.group(3) == "-":
                spans = [(first, second)]
            elif second is None:
                spans = [(first, first)]
            else:
                spans = [(first, first), (second, int(m.group(5) or second))]
            moved = []
            lost = False
            for a, b in spans:
                block = old[a - 1:max(a, b)]
                if new[a - 1:max(a, b)] == block:
                    moved.append(a)
                    continue
                at = _relocate(block, new, a) if any(s.strip() for s in block) else None
                if at is None:
                    lost = True
                    gone.append(f"{rel}: {m.group(1)}:{a} no longer says what it said at "
                                f"{commit.group(1)}")
                moved.append(at or a)
            if lost:
                edits.append((m.start(1), m.end(), _stale_mark(m)))
            elif moved != [a for a, _ in spans]:
                cite = m.group(1) + ":" + ", ".join(
                    f"{mv}-{mv + b - a}" if b != a else str(mv)
                    for mv, (a, b) in zip(moved, spans, strict=True)
                )
                edits.append((m.start(1), m.end(), cite))
                problems.append(f"{rel}: {m.group(0)[1:]} moved to {cite}")
        problems.extend(gone)
        if fix and (edits or gone):
            for start, end, cite in sorted(edits, reverse=True):
                text = text[:start] + cite + text[end:]
            # The relocated numbers are right for HEAD, so the commit moves with them: left at
            # the old commit, the next run (or a person flipping the card back to verified)
            # would shift them a second time. Citations whose text is gone were set aside as
            # `[stale N]` markers, which `broken_citations` rejects in a verified card, so
            # restamping cannot hide them. The verified date moves only when nothing is gone.
            text = re.sub(r"^commit:.*$", f"commit: {head}", text, count=1, flags=re.M)
            if gone:
                text = text.replace("status: verified", "status: stale", 1)
            else:
                text = re.sub(r"^verified:.*$", f"verified: {date.today().isoformat()}",
                              text, count=1, flags=re.M)
            card.write_text(text, encoding="utf-8")
    return problems


def main() -> int:
    problems = broken_citations()
    for p in problems:
        print(p)
    print(f"{len(problems)} broken citation(s) in verified map cards")
    if "--drift" in sys.argv or "--fix" in sys.argv:
        drift = drifted_citations(fix="--fix" in sys.argv)
        for p in drift:
            print(p)
        print(f"{len(drift)} drifted citation(s)" + (" (fixed or marked stale)" if "--fix" in
                                                       sys.argv else "; run with --fix"))
        problems += [] if "--fix" in sys.argv else drift
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
