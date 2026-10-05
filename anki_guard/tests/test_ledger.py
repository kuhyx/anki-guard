# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
from __future__ import annotations

from datetime import UTC, date, datetime
import json
import logging
from typing import TYPE_CHECKING

from earned_time import verified
import pytest

from anki_guard import _ledger
from anki_guard._quota import ANKI
from anki_guard._studied import Studied

if TYPE_CHECKING:
    from pathlib import Path


KEY = b"k" * 32
NOW = datetime(2026, 10, 4, 17, 0, tzinfo=UTC)
DONE = Studied(
    date(2026, 10, 4),
    required_seconds=1200,
    reviews=43,
    seconds=2520.4,
    crossed_at=1791135962.3721,
    synced_at=1.0,
)


def test_credit_row_is_signed_and_complete() -> None:
    row = _ledger.credit_row(DONE, ANKI, KEY, now=NOW)
    assert verified(row, KEY)
    assert row["entry_id"] == "anki:2026-10-04"
    assert row["kind"] == "credit"
    assert row["amount"] == 42
    assert row["created_at"] == "2026-10-04T17:00:00+00:00"
    assert row["detail"] == {
        "anki_day": "2026-10-04",
        "minutes": "42.0",
        "reviews": "43",
        "studied_at": "1791135962.372",
    }
    assert not verified({**row, "amount": 99}, KEY)


def test_no_credit_row_below_the_bar() -> None:
    short = Studied(date(2026, 10, 4), 1200, 1, 60.0, None, 1.0)
    with pytest.raises(ValueError, match="earns no credit"):
        _ledger.credit_row(short, ANKI, KEY, now=NOW)


def test_read_key(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    key = tmp_path / "key"
    key.write_bytes(KEY + b"\n")
    assert _ledger.read_key(key) == KEY
    key.write_bytes(b"  \n")
    with caplog.at_level(logging.WARNING):
        assert _ledger.read_key(key) is None
        assert _ledger.read_key(tmp_path / "missing") is None
    assert "is empty" in caplog.text
    assert "cannot read the signing key" in caplog.text


def test_missing_ledger_is_empty(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        assert _ledger.read_rows(tmp_path / "ledger.json") == []
    assert "starting it" in caplog.text


@pytest.mark.parametrize(
    ("body", "match"),
    [
        ("{", "not valid JSON"),
        ("[]", "no entries array"),
        ('{"entries": {}}', "no entries array"),
    ],
)
def test_corrupt_ledger_is_never_emptied(tmp_path: Path, body: str, match: str) -> None:
    ledger = tmp_path / "ledger.json"
    ledger.write_text(body)
    with pytest.raises(_ledger.LedgerError, match=match):
        _ledger.read_rows(ledger)


def test_write_then_read_round_trip_keeps_foreign_rows(tmp_path: Path) -> None:
    ledger = tmp_path / "sub" / "ledger.json"
    foreign = {"entry_id": "x", "kind": "other"}
    row = _ledger.credit_row(DONE, ANKI, KEY, now=NOW)
    _ledger.write_rows(ledger, [foreign, row])
    assert json.loads(ledger.read_text()) == {"entries": [foreign, row]}
    assert _ledger.read_rows(ledger) == [foreign, row]
    assert list(ledger.parent.iterdir()) == [ledger]  # no temp file left


def test_has_credit_needs_a_verified_credit_with_the_id() -> None:
    row = _ledger.credit_row(DONE, ANKI, KEY, now=NOW)
    assert _ledger.has_credit(["junk", row], "anki:2026-10-04", KEY)
    assert not _ledger.has_credit([row], "anki:2026-10-05", KEY)
    assert not _ledger.has_credit([{**row, "hmac": "0" * 64}], "anki:2026-10-04", KEY)
    forged_kind = {**row, "kind": "escape"}
    assert not _ledger.has_credit([forged_kind], "anki:2026-10-04", KEY)


def test_exclusive_lock(tmp_path: Path) -> None:
    lock = tmp_path / "d" / "write.lock"
    with _ledger.exclusive(lock):
        assert lock.exists()
