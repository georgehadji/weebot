"""The ICM system map stays true to the code (ICM A3).

`map/objects/_index.md` is generated from the cards, and every citation in a
verified card resolves to a tracked file and an existing line. A verified card
that is silently wrong costs more than a missing one.
"""

from __future__ import annotations

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_object_index_is_the_generated_one():
    gen = _load("gen_map_index")
    current = (ROOT / "map" / "objects" / "_index.md").read_text(encoding="utf-8")
    assert current.replace("\r\n", "\n") == gen.render(), "run python scripts/gen_map_index.py"


def test_verified_cards_cite_real_files_and_lines():
    assert _load("check_map_citations").broken_citations() == []


def test_a_shifted_citation_is_found_at_its_new_line_and_a_changed_one_is_not():
    relocate = _load("check_map_citations")._relocate
    new = ["import x", "", "def f():", "    return 1", "def g():", "    return 1"]
    assert relocate(["def f():", "    return 1"], new, 1) == 3
    assert relocate(["    return 1"], new, 7) == 6  # nearest of two matches
    assert relocate(["def h():"], new, 3) is None


def test_the_tasks_index_is_the_generated_one():
    gen = _load("gen_tasks_index")
    current = (ROOT / "tasks" / "_index.md").read_text(encoding="utf-8")
    assert current.replace("\r\n", "\n") == gen.render(), "run python scripts/gen_tasks_index.py"


def test_drift_is_enforced_by_make_check_and_advisory_in_ci():
    """A code move must not turn every unrelated PR red (main was red for 5 runs).

    `make check` is what an author runs before merging, so it enforces drift. CI
    blocks only on the stable checks (indexes, broken citations) and reports drift
    as an advisory step.
    """
    import pytest

    yaml = pytest.importorskip("yaml")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    check_line = next(line for line in makefile.splitlines() if line.startswith("check:"))
    assert "lint-map-drift" in check_line.split()
    assert "check_map_citations.py --drift" not in makefile.split("lint-map-drift:")[0].split(
        "lint-map:"
    )[-1], "lint-map must not run the drift check"

    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "architecture.yml").read_text(encoding="utf-8")
    )
    steps = [s for job in workflow["jobs"].values() for s in job.get("steps", [])]
    by_run = {s.get("run"): s for s in steps if s.get("run")}
    assert not by_run["make lint-map"].get("continue-on-error")
    assert by_run["make lint-map-drift"].get("continue-on-error") is True


def test_a_record_with_an_unknown_status_fails_the_generator(monkeypatch, capsys):
    """A typo'd status (`wip`) used to vanish from the index without a word."""
    import sys

    gen = _load("gen_tasks_index")
    monkeypatch.setattr(gen, "records", lambda: [("wip", "2026-10-26", "x.md", "X", "")])
    monkeypatch.setattr(sys, "argv", ["gen_tasks_index.py"])
    assert gen.main() == 1, "the generator must refuse a status outside the known set"
    assert "x.md" in capsys.readouterr().out


def _git(repo, *args):
    import subprocess

    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": __import__("os").environ["PATH"],
           "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}
    out = subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, text=True,
                         check=True)
    return out.stdout.strip()


def _card_repo(tmp_path, monkeypatch):
    """A tiny repo: weebot/mod.py, and a verified card citing `weebot/mod.py:3` at its commit."""
    cm = _load("check_map_citations")
    monkeypatch.setattr(cm, "ROOT", tmp_path)
    _git(tmp_path, "init", "-q")
    (tmp_path / "weebot").mkdir()
    (tmp_path / "weebot" / "mod.py").write_text("import os\n\ndef f():\n    return 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "one")
    sha = _git(tmp_path, "rev-parse", "--short", "HEAD")
    card = tmp_path / "map" / "objects" / "x" / "Card.md"
    card.parent.mkdir(parents=True)
    card.write_text(f"---\nstatus: verified\nverified: 2026-01-01\ncommit: {sha}\n---\n"
                    "`f` is at `weebot/mod.py:3`.\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "card")
    return cm, card


def test_fix_moves_a_shifted_citation_and_keeps_the_card_verified(tmp_path, monkeypatch):
    cm, card = _card_repo(tmp_path, monkeypatch)
    (tmp_path / "weebot" / "mod.py").write_text("import os\nimport sys\n\ndef f():\n    return 1\n")
    _git(tmp_path, "commit", "-q", "-am", "shift")
    assert cm.drifted_citations() != []
    cm.drifted_citations(fix=True)
    text = card.read_text()
    assert "weebot/mod.py:4" in text and "status: verified" in text
    assert cm.drifted_citations() == []


def test_fix_marks_the_card_stale_when_the_cited_text_is_gone(tmp_path, monkeypatch):
    cm, card = _card_repo(tmp_path, monkeypatch)
    (tmp_path / "weebot" / "mod.py").write_text("import os\n\ndef g():\n    return 2\n")
    _git(tmp_path, "commit", "-q", "-am", "rewrite")
    problems = cm.drifted_citations(fix=True)
    assert any("no longer says" in p for p in problems)
    assert "status: stale" in card.read_text()


def test_a_card_whose_commit_is_not_in_the_clone_is_reported_not_skipped(tmp_path, monkeypatch):
    """A shallow CI checkout lacks the card's commit; every citation was then skipped silently."""
    cm, card = _card_repo(tmp_path, monkeypatch)
    card.write_text(card.read_text().replace(
        card.read_text().split("commit: ")[1].split("\n")[0], "deadbeef1"))
    problems = cm.drifted_citations()
    assert any("deadbeef1" in p and "not in this clone" in p for p in problems)


def test_the_citation_check_covers_process_cards():
    """Wrong `PlanActFlow.run` lines sat in a process card the check never opened."""
    cards = _load("check_map_citations")._cards()
    assert any(p.parent.name == "processes" for p in cards)
    assert any("objects" in p.parts for p in cards)


def _index_with(monkeypatch, rows, succ):
    import sys

    gen = _load("gen_tasks_index")
    monkeypatch.setattr(gen, "records", lambda: rows)
    monkeypatch.setattr(gen, "successors", lambda: succ)
    monkeypatch.setattr(sys, "argv", ["gen_tasks_index.py"])
    return gen


def test_a_superseded_record_must_be_named_by_its_successor(monkeypatch, capsys):
    rows = [("superseded", "2026-10-27", "old.md", "Old", "")]
    assert _index_with(monkeypatch, rows, {}).main() == 1
    assert "old.md" in capsys.readouterr().out


def test_supersedes_must_name_a_superseded_record(monkeypatch, capsys):
    rows = [("done", "2026-10-27", "old.md", "Old", ""),
            ("done", "2026-10-27", "new.md", "New", "")]
    assert _index_with(monkeypatch, rows, {"old.md": ["new.md"]}).main() == 1
    assert "old.md" in capsys.readouterr().out


def test_the_index_says_what_superseded_a_record(monkeypatch):
    rows = [("superseded", "2026-10-27", "old.md", "Old", ""),
            ("done", "2026-10-27", "new.md", "New", "")]
    gen = _index_with(monkeypatch, rows, {"old.md": ["new.md"]})
    assert "superseded by [New](new.md)" in gen.render(rows, {"old.md": ["new.md"]})


def test_fix_keeps_a_list_followed_by_a_range_intact(tmp_path, monkeypatch):
    """`a, b-c` lost its `-c` tail or kept it unshifted (`441, 452-449`)."""
    cm, card = _card_repo(tmp_path, monkeypatch)
    lines = [f"line {i}" for i in range(1, 9)]
    (tmp_path / "weebot" / "mod.py").write_text("\n".join(lines) + "\n")
    _git(tmp_path, "commit", "-q", "-am", "eight lines")
    sha = _git(tmp_path, "rev-parse", "--short", "HEAD")
    card.write_text(f"---\nstatus: verified\nverified: 2026-01-01\ncommit: {sha}\n---\n"
                    "`f` is at `weebot/mod.py:2, 5-6`.\n")
    _git(tmp_path, "commit", "-q", "-am", "card2")
    (tmp_path / "weebot" / "mod.py").write_text("\n".join(["new", *lines]) + "\n")
    _git(tmp_path, "commit", "-q", "-am", "shift")
    cm.drifted_citations(fix=True)
    assert "weebot/mod.py:3, 6-7" in card.read_text()


def test_fix_is_idempotent_on_a_card_it_marks_stale(tmp_path, monkeypatch):
    """Relocated numbers without a restamped commit were shifted again by the next run."""
    cm, card = _card_repo(tmp_path, monkeypatch)
    lines = [f"line {i}" for i in range(1, 9)]
    (tmp_path / "weebot" / "mod.py").write_text("\n".join(lines) + "\n")
    _git(tmp_path, "commit", "-q", "-am", "eight lines")
    sha = _git(tmp_path, "rev-parse", "--short", "HEAD")
    card.write_text(f"---\nstatus: verified\nverified: 2026-01-01\ncommit: {sha}\n---\n"
                    "`a` is at `weebot/mod.py:3`, and `b` is at `weebot/mod.py:6`.\n")
    _git(tmp_path, "commit", "-q", "-am", "card2")
    changed = ["new", *lines]
    changed[6] = "line 6 rewritten"  # line 6 moves to 7 and its text changes
    (tmp_path / "weebot" / "mod.py").write_text("\n".join(changed) + "\n")
    _git(tmp_path, "commit", "-q", "-am", "shift and rewrite")
    cm.drifted_citations(fix=True)
    once = card.read_text()
    assert "status: stale" in once and "weebot/mod.py:4" in once
    # A person re-reading the card flips it back to verified; the numbers it kept must not
    # be shifted a second time.
    card.write_text(once.replace("status: stale", "status: verified"))
    cm.drifted_citations(fix=True)
    assert "weebot/mod.py:4" in card.read_text()
