# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
from __future__ import annotations

import logging
import shutil
from typing import TYPE_CHECKING

import pytest

from anki_guard import _snapshot
from anki_guard._snapshot import SnapshotError, connect, snapshot
from anki_guard.tests._collection import make_collection

if TYPE_CHECKING:
    from pathlib import Path


def _count(path: Path) -> int:
    db = connect(path, read_only=True)
    try:
        return int(db.execute("SELECT count() FROM revlog").fetchone()[0])
    finally:
        db.close()


def test_copies_database_and_wal_together(tmp_path: Path) -> None:
    source = tmp_path / "collection.anki2"
    make_collection(source, reviews=[(1, 1000, 1), (2, 1000, 1)], wal=True)
    assert source.with_name("collection.anki2-wal").stat().st_size > 0
    with snapshot(source) as copy:
        assert copy != source
        assert _count(copy) == 2  # the rows only exist in the WAL
    assert not copy.exists()


def test_without_a_wal(tmp_path: Path) -> None:
    source = tmp_path / "collection.anki2"
    make_collection(source, reviews=[(1, 1000, 1)])
    with snapshot(source) as copy:
        assert _count(copy) == 1


def test_missing_collection_is_an_error(tmp_path: Path) -> None:
    with (
        pytest.raises(SnapshotError, match="has the phone synced yet"),
        snapshot(tmp_path / "nope.anki2"),
    ):
        pass  # pragma: no cover


def test_collation_is_needed_for_quick_check(tmp_path: Path) -> None:
    import sqlite3

    source = tmp_path / "collection.anki2"
    make_collection(source)
    plain = sqlite3.connect(source)
    with pytest.raises(sqlite3.OperationalError, match="unicase"):
        plain.execute("PRAGMA quick_check").fetchone()
    plain.close()
    assert _snapshot._healthy(source)


def test_unicase_orders_case_insensitively() -> None:
    assert _snapshot._unicase("a", "B") == -1
    assert _snapshot._unicase("B", "a") == 1
    assert _snapshot._unicase("Rollover", "rollover") == 0


def test_torn_copy_retries_then_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    source = tmp_path / "collection.anki2"
    make_collection(source, reviews=[(1, 1000, 1)])
    real = _snapshot._fingerprint
    calls = {"n": 0}

    def flaky(path: Path) -> _snapshot.Fingerprint:
        calls["n"] += 1
        got = real(path)
        return (None, None) if calls["n"] == 2 else got  # "after" differs once

    monkeypatch.setattr(_snapshot, "_fingerprint", flaky)
    with caplog.at_level(logging.WARNING), snapshot(source, pause=0) as copy:
        assert _count(copy) == 1
    assert "changed while copying" in caplog.text


def test_never_settles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "collection.anki2"
    make_collection(source)
    monkeypatch.setattr(_snapshot, "_copy_once", lambda s, t: False)
    slept: list[float] = []
    monkeypatch.setattr("anki_guard._snapshot.time.sleep", slept.append)
    with (
        pytest.raises(SnapshotError, match="after 3 attempts"),
        snapshot(source, attempts=3, pause=0.5),
    ):
        pass  # pragma: no cover
    assert slept == [0.5, 0.5]


def test_checkpoint_during_copy_is_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    source = tmp_path / "collection.anki2"
    make_collection(source)
    real = _snapshot._copy_once
    calls = {"n": 0}

    def racing(s: Path, t: Path) -> bool:
        calls["n"] += 1
        if calls["n"] == 1:
            msg = "collection.anki2-wal"
            raise FileNotFoundError(msg)
        return real(s, t)

    monkeypatch.setattr(_snapshot, "_copy_once", racing)
    with caplog.at_level(logging.WARNING), snapshot(source, pause=0):
        pass
    assert "moved under the copy" in caplog.text


def test_unreadable_source_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "collection.anki2"
    make_collection(source)

    def denied(*_args: object) -> None:
        msg = "denied"
        raise PermissionError(msg)

    monkeypatch.setattr(shutil, "copyfile", denied)
    with pytest.raises(SnapshotError, match="cannot copy"), snapshot(source):
        pass  # pragma: no cover


def test_callers_error_is_not_swallowed(tmp_path: Path) -> None:
    source = tmp_path / "collection.anki2"
    make_collection(source)
    callers = OSError("caller")
    with pytest.raises(OSError, match="caller"), snapshot(source):
        raise callers


def test_garbage_copy_is_unreadable(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    copy = tmp_path / "bad.anki2"
    copy.write_bytes(b"not a database at all" * 100)
    with caplog.at_level(logging.WARNING):
        assert not _snapshot._healthy(copy)
    assert "unreadable" in caplog.text


def test_quick_check_not_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    copy = tmp_path / "c.anki2"
    make_collection(copy)

    class FakeDb:
        def execute(self, _sql: str) -> FakeDb:
            return self

        def fetchone(self) -> tuple[str]:
            return ("*** in database main ***",)

        def close(self) -> None:
            pass

    monkeypatch.setattr(_snapshot, "connect", lambda _p: FakeDb())
    with caplog.at_level(logging.WARNING):
        assert not _snapshot._healthy(copy)
    assert "failed quick_check" in caplog.text
