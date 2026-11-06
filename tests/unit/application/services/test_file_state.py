"""FileStateRegistry remembers what the model last saw of each file (H6)."""

from __future__ import annotations

import os

from weebot.application.services.file_state import FileStateRegistry


def test_a_file_never_recorded_is_not_safe_to_write(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("one", encoding="utf-8")

    assert "not viewed" in FileStateRegistry().check(f)


def test_a_recorded_file_that_has_not_changed_is_safe(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("one", encoding="utf-8")
    state = FileStateRegistry()
    state.record(f)

    assert state.check(f) is None


def test_a_changed_file_is_not_safe(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("one", encoding="utf-8")
    state = FileStateRegistry()
    state.record(f)
    f.write_text("three", encoding="utf-8")

    assert "changed since you last viewed" in state.check(f)


def test_a_change_that_keeps_size_and_mtime_is_a_known_blind_spot(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("one", encoding="utf-8")
    state = FileStateRegistry()
    state.record(f)
    before = f.stat()
    f.write_text("two", encoding="utf-8")
    os.utime(f, ns=(before.st_atime_ns, before.st_mtime_ns))  # same size, same mtime

    assert state.check(f) is None  # undetectable without hashing on every check: a known limit

    os.utime(f, ns=(before.st_atime_ns, before.st_mtime_ns + 10**9))
    assert "changed since you last viewed" in state.check(f)


def test_a_touched_file_with_the_same_content_is_safe_and_refreshed(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("one", encoding="utf-8")
    state = FileStateRegistry()
    state.record(f)
    stat = f.stat()
    os.utime(f, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))

    assert state.check(f) is None
    assert state.check(f) is None  # the second check needs no hashing: the stamp was refreshed


def test_the_oldest_file_is_forgotten_past_capacity(tmp_path):
    state = FileStateRegistry(capacity=2)
    files = []
    for name in ("a", "b", "c"):
        f = tmp_path / f"{name}.txt"
        f.write_text(name, encoding="utf-8")
        state.record(f)
        files.append(f)

    assert "not viewed" in state.check(files[0])
    assert state.check(files[1]) is None and state.check(files[2]) is None


def test_purge_forgets_everything(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("one", encoding="utf-8")
    state = FileStateRegistry()
    state.record(f)

    state.purge()

    assert "not viewed" in state.check(f)


def test_a_recorded_file_that_is_deleted_does_not_block_the_write(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("one", encoding="utf-8")
    state = FileStateRegistry()
    state.record(f)
    f.unlink()

    assert state.check(f) is None  # the write itself reports the missing file


def test_recording_a_missing_file_forgets_it(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("one", encoding="utf-8")
    state = FileStateRegistry()
    state.record(f)
    f.unlink()

    state.record(f)

    assert "not viewed" in state.check(f)
