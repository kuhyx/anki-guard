# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
from __future__ import annotations

from datetime import UTC, date, datetime
import logging
from typing import TYPE_CHECKING

import pytest

from anki_guard._studied import (
    DEFAULT_ROLLOVER,
    CollectionError,
    day_bounds,
    studied,
)
from anki_guard.tests._collection import make_collection, raw

if TYPE_CHECKING:
    from pathlib import Path


# 2026-10-04 19:00 CEST
NOW = datetime(2026, 10, 4, 17, 0, tzinfo=UTC)


def _ms(year: int, month: int, day: int, hour: int, minute: int) -> int:
    local = datetime(year, month, day, hour, minute).astimezone()
    return int(local.timestamp() * 1000)


def test_day_bounds_match_ankis_next_day_at() -> None:
    # Measured against Collection.sched.day_cutoff on 2026-10-04: 1791165600.
    day, start = day_bounds(NOW, 4)
    assert day == date(2026, 10, 4)
    assert start + 86400 == 1791165600


def test_before_rollover_is_still_yesterday() -> None:
    day, start = day_bounds(datetime(2026, 10, 4, 0, 30, tzinfo=UTC), 4)  # 02:30 local
    assert day == date(2026, 10, 3)
    assert start == datetime(2026, 10, 3, 4).astimezone().timestamp()


def test_rollover_zero_is_the_calendar_day() -> None:
    day, start = day_bounds(NOW, 0)
    assert day == date(2026, 10, 4)
    assert start == datetime(2026, 10, 4).astimezone().timestamp()


def test_sums_todays_reviews_and_finds_the_crossing(tmp_path: Path) -> None:
    path = tmp_path / "c.anki2"
    make_collection(
        path,
        rollover=4,
        mod_ms=1_791_000_000_000,
        reviews=[
            (_ms(2026, 10, 4, 3, 59), 600_000, 1),  # before rollover: yesterday
            (_ms(2026, 10, 4, 9, 0), 600_000, 1),
            (_ms(2026, 10, 4, 9, 30), 60_000, 4),  # manual: not counted
            (_ms(2026, 10, 4, 10, 0), 300_000, 5),  # rescheduled: not counted
            (_ms(2026, 10, 4, 11, 0), 600_000, 2),  # reaches 20 min here
            (_ms(2026, 10, 4, 12, 0), 30_000, 3),
        ],
    )
    got = studied(path, NOW, 1200)
    assert got.anki_day == date(2026, 10, 4)
    assert got.reviews == 3
    assert got.seconds == 1230
    assert got.crossed_at == _ms(2026, 10, 4, 11, 0) / 1000
    assert got.synced_at == 1_791_000_000


def test_below_the_bar_has_no_crossing(tmp_path: Path) -> None:
    path = tmp_path / "c.anki2"
    make_collection(path, rollover=0, reviews=[(_ms(2026, 10, 4, 9, 0), 1_199_999, 1)])
    got = studied(path, NOW, 1200)
    assert (got.reviews, got.crossed_at) == (1, None)


@pytest.mark.parametrize("stored", [None, 24, -1, "4", 4.5])
def test_missing_or_bad_rollover_uses_ankis_default(
    tmp_path: Path, stored: object, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "c.anki2"
    make_collection(path, rollover=stored)
    with caplog.at_level(logging.WARNING):
        got = studied(path, NOW, 1200)
    assert got.anki_day == day_bounds(NOW, DEFAULT_ROLLOVER)[0]
    assert ("not an hour" in caplog.text) is (stored is not None)


@pytest.mark.parametrize(
    ("conf", "expected"),
    [({"rollover": 0}, date(2026, 10, 4)), ({}, date(2026, 10, 4))],
)
def test_legacy_col_conf_rollover(
    tmp_path: Path,
    conf: dict[str, object],
    expected: date,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = tmp_path / "c.anki2"
    make_collection(path, legacy_conf=conf)
    with caplog.at_level(logging.WARNING):
        assert studied(path, NOW, 1200).anki_day == expected
    assert "legacy col.conf" in caplog.text


def test_legacy_empty_conf_uses_default(tmp_path: Path) -> None:
    path = tmp_path / "c.anki2"
    make_collection(path, legacy_conf={})
    with raw(path) as db:
        db.execute("UPDATE col SET conf = ''")
    db.close()
    early = datetime(2026, 10, 4, 0, 30, tzinfo=UTC)  # 02:30: default 4 -> yesterday
    assert studied(path, early, 1200).anki_day == date(2026, 10, 3)


def test_empty_col_table_reports_zero_sync(tmp_path: Path) -> None:
    path = tmp_path / "c.anki2"
    make_collection(path)
    with raw(path) as db:
        db.execute("DELETE FROM col")
    db.close()
    assert studied(path, NOW, 1200).synced_at == 0


def test_not_a_collection(tmp_path: Path) -> None:
    path = tmp_path / "c.anki2"
    with raw(path) as db:
        db.execute("CREATE TABLE x (y)")
    db.close()
    with pytest.raises(CollectionError, match="not a readable Anki collection"):
        studied(path, NOW, 1200)
