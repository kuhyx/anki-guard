# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The two quotas split one collection: no review pays both."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

import freedays
import pytest

from anki_guard import _ledger
from anki_guard._gate import Status, run
from anki_guard._quota import ANKI, AUTOMATION, QUOTAS
from anki_guard._studied import studied

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from anki_guard._paths import Paths

NOW = datetime(2026, 10, 5, 17, 0, tzinfo=UTC)  # Monday 19:00 CEST
DECKS = {
    1: "Default",
    2: "Automation",
    3: "Automation\x1fPLC",
    4: "Automation Extra",  # a sibling whose name merely starts the same
    5: "Filtered",
}
# card id -> (deck, original deck)
CARDS = {10: (1, 0), 20: (2, 0), 30: (3, 0), 40: (4, 0), 50: (5, 2), 60: (5, 1)}


def _minutes(cid: int | None, count: int, start: int = 0) -> list[tuple[int, ...]]:
    """``count`` one-minute reviews of card ``cid`` from 09:00 local."""
    rows: list[tuple[int, ...]] = []
    for m in range(start, start + count):
        at = datetime(2026, 10, 5, 9, 0).astimezone() + timedelta(minutes=m)
        stamp = int(at.timestamp() * 1000)
        rows.append((stamp, 60_000, 1) if cid is None else (stamp, 60_000, 1, cid))
    return rows


@pytest.mark.parametrize(
    ("day", "anki", "automation"),
    [
        (date(2026, 10, 5), 20, 25),  # Mon
        (date(2026, 10, 6), 12, 8),  # Tue
        (date(2026, 10, 7), 12, 8),  # Wed
        (date(2026, 10, 8), 12, 8),  # Thu
        (date(2026, 10, 9), 20, 25),  # Fri
        (date(2026, 10, 10), 20, 25),  # Sat
        (date(2026, 10, 11), 20, 25),  # Sun
    ],
)
def test_weekday_bars(day: date, anki: int, automation: int) -> None:
    assert ANKI.required_seconds(day) == anki * 60
    assert AUTOMATION.required_seconds(day) == automation * 60


def test_cheap_days_are_the_shared_freedays_workdays() -> None:
    week = [date(2026, 10, 5) + timedelta(days=n) for n in range(7)]
    cheap = {d.weekday() for d in week if ANKI.required_seconds(d) < 20 * 60}
    assert cheap == freedays.WORKDAYS


def test_workday_bars_fit_twenty_minutes_together() -> None:
    tuesday = date(2026, 10, 6)
    assert sum(q.required_seconds(tuesday) for q in QUOTAS) <= 20 * 60


def test_no_bar_exceeds_twenty_five_minutes() -> None:
    week = [date(2026, 10, 5) + timedelta(days=n) for n in range(7)]
    assert max(q.required_seconds(d) for q in QUOTAS for d in week) <= 25 * 60


def test_each_review_counts_for_exactly_one_quota(
    server_collection: Callable[..., Path],
) -> None:
    reviews = (
        _minutes(10, 1, 0)  # Default -> anki
        + _minutes(20, 1, 1)  # Automation -> automation
        + _minutes(30, 1, 2)  # Automation::PLC subdeck -> automation
        + _minutes(40, 1, 3)  # "Automation Extra" is not a subdeck -> anki
        + _minutes(50, 1, 4)  # filtered, home deck Automation -> automation
        + _minutes(60, 1, 5)  # filtered, home deck Default -> anki
        + _minutes(None, 1, 6)  # card since deleted -> anki
    )
    path = server_collection(rollover=0, reviews=reviews, decks=DECKS, cards=CARDS)
    got = {q.name: studied(path, NOW, q) for q in QUOTAS}
    assert got["anki"].reviews == 4
    assert got["automation"].reviews == 3
    assert sum(s.seconds for s in got.values()) == len(reviews) * 60


def test_no_automation_deck_leaves_anki_as_before(
    server_collection: Callable[..., Path],
) -> None:
    path = server_collection(rollover=0, reviews=_minutes(10, 21), cards={10: (1, 0)})
    assert studied(path, NOW, ANKI).crossed_at is not None
    assert studied(path, NOW, AUTOMATION).reviews == 0


def test_quotas_credit_separately_into_their_own_ledgers(
    ag_paths: Paths, server_collection: Callable[..., Path]
) -> None:
    # 25 min of automation on a Monday, only 5 of anything else.
    reviews = _minutes(20, 25) + _minutes(10, 5, 25)
    server_collection(rollover=0, reviews=reviews, decks=DECKS, cards=CARDS)
    assert run(ag_paths, NOW, AUTOMATION, write=True).status is Status.CREDITED
    assert run(ag_paths, NOW, ANKI, write=True).status is Status.SHORT
    rows = _ledger.read_rows(ag_paths.ledger(AUTOMATION))
    assert [r["entry_id"] for r in rows if isinstance(r, dict)] == [
        "automation:2026-10-05"
    ]
    assert not ag_paths.ledger(ANKI).exists()


def test_twenty_four_minutes_is_short_on_a_full_day(
    ag_paths: Paths, server_collection: Callable[..., Path]
) -> None:
    server_collection(rollover=0, reviews=_minutes(20, 24), decks=DECKS, cards=CARDS)
    report = run(ag_paths, NOW, AUTOMATION, write=True)
    assert report.status is Status.SHORT
    assert report.studied is not None
    assert report.studied.required_seconds == 25 * 60
