# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Anki's own "studied today" figure, read from a collection snapshot.

The same sum the Anki UI shows: every ``revlog`` row since the start of the
current Anki day, except manual (4) and rescheduled (5) entries. ``time`` is
in milliseconds and already capped per deck by "Maximum answer seconds" when
the review was logged, so a card left open does not count past the cap.

**The Anki day starts at the collection's rollover hour** (default 4 am), not
at midnight, and the rollover is read from the collection that actually
landed on the server -- the phone's -- never assumed. Studying at 01:00 counts
for the previous Anki day, exactly as the app shows it.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import json
import logging
import sqlite3
from typing import TYPE_CHECKING, Final

from anki_guard._snapshot import connect

if TYPE_CHECKING:
    from pathlib import Path

    from anki_guard._quota import Quota

_logger: Final = logging.getLogger(__name__)

DEFAULT_ROLLOVER: Final = 4
_EXCLUDED_KINDS: Final = (4, 5)  # manual, rescheduled
_MS: Final = 1000
_DAY_SECONDS: Final = 86400
_HOURS: Final = range(24)
_DECK_SEPARATOR: Final = "\x1f"  # how Anki stores "Parent::Child"


class CollectionError(Exception):
    """The snapshot is not a collection this module can read."""


@dataclass(frozen=True)
class Studied:
    """Today's study on the server's copy of the collection.

    Attributes:
        anki_day: The Anki day the figures belong to (its start's local date).
        required_seconds: The quota's bar for that day.
        reviews: Reviews counted.
        seconds: Time spent on them, as Anki reports it.
        crossed_at: Unix seconds of the review that took the running total to
            ``required_seconds``, or ``None`` if it has not got there.
        synced_at: Unix seconds of the collection's last modification -- the
            phone's last sync with changes, so a stale copy is visible.
    """

    anki_day: date
    required_seconds: int
    reviews: int
    seconds: float
    crossed_at: float | None
    synced_at: float


def _stored_rollover(db: sqlite3.Connection) -> object:
    """The raw rollover value: ``config`` table, else the legacy ``col.conf``."""
    try:
        row = db.execute("SELECT val FROM config WHERE key = 'rollover'").fetchone()
    except sqlite3.OperationalError as exc:
        _logger.warning("no config table (%s); trying the legacy col.conf", exc)
        conf = db.execute("SELECT conf FROM col").fetchone()
        return json.loads(conf[0]).get("rollover") if conf and conf[0] else None
    return json.loads(row[0]) if row is not None else None


def rollover_hour(db: sqlite3.Connection) -> int:
    """The collection's rollover hour, or Anki's default when unset."""
    value = _stored_rollover(db)
    if value is None:
        return DEFAULT_ROLLOVER
    if isinstance(value, int) and value in _HOURS:
        return value
    _logger.warning("rollover %r is not an hour; using %d", value, DEFAULT_ROLLOVER)
    return DEFAULT_ROLLOVER


def day_bounds(now: datetime, rollover: int) -> tuple[date, float]:
    """The current Anki day and its start in unix seconds.

    Mirrors Anki: ``next_day_at`` is the next local rollover, and the day
    began exactly 86400 s before it.
    """
    local = now.astimezone()
    anki_day = (local - timedelta(hours=rollover)).date()
    next_day = datetime.combine(anki_day + timedelta(days=1), time(rollover))
    return anki_day, next_day.astimezone().timestamp() - _DAY_SECONDS


def deck_ids(db: sqlite3.Connection, deck: str) -> set[int]:
    """Ids of ``deck`` and every subdeck; empty when the deck does not exist."""
    rows = db.execute("SELECT id, name FROM decks").fetchall()
    prefix = deck + _DECK_SEPARATOR
    return {did for did, name in rows if name == deck or name.startswith(prefix)}


def _in_quota(home_deck: int | None, decks: set[int], quota: Quota) -> bool:
    """Whether a review's card belongs to ``quota``'s slice of the collection.

    A review whose card was since deleted has no deck (``None``): it still
    counts for Anki's own total, so it goes to the excluding quota.
    """
    inside = home_deck is not None and home_deck in decks
    return inside if quota.include else not inside


def _tally(reviews: list[tuple[int, int]], required: int) -> tuple[float, float | None]:
    """Total seconds of ``reviews``, and when the running total reached ``required``."""
    total_ms = 0
    crossed_at: float | None = None
    for review_id, spent in reviews:
        total_ms += spent
        if crossed_at is None and total_ms >= required * _MS:
            crossed_at = review_id / _MS
    return total_ms / _MS, crossed_at


def studied(snapshot: Path, now: datetime, quota: Quota) -> Studied:
    """Today's reviews and time on ``snapshot`` that count for ``quota``.

    A card sitting in a filtered deck is credited to its home deck
    (``odid``), so a custom study session cannot move reviews between quotas.

    Raises:
        CollectionError: The file has no ``revlog``/``cards``/``decks``/``col`` tables.
    """
    try:
        db = connect(snapshot, read_only=True)
        with closing(db):
            anki_day, start = day_bounds(now, rollover_hour(db))
            decks = deck_ids(db, quota.deck)
            rows = db.execute(
                "SELECT r.id, r.time,"
                " CASE WHEN c.odid != 0 THEN c.odid ELSE c.did END"
                " FROM revlog r LEFT JOIN cards c ON c.id = r.cid"
                " WHERE r.id > ? AND r.type NOT IN (?, ?) ORDER BY r.id",
                (int(start * _MS), *_EXCLUDED_KINDS),
            ).fetchall()
            mod = db.execute("SELECT mod FROM col").fetchone()
    except sqlite3.DatabaseError as exc:
        msg = f"{snapshot} is not a readable Anki collection: {exc}"
        raise CollectionError(msg) from exc
    required = quota.required_seconds(anki_day)
    counted = [(rid, ms) for rid, ms, home in rows if _in_quota(home, decks, quota)]
    seconds, crossed_at = _tally(counted, required)
    return Studied(
        anki_day=anki_day,
        required_seconds=required,
        reviews=len(counted),
        seconds=seconds,
        crossed_at=crossed_at,
        synced_at=(mod[0] if mod else 0) / _MS,
    )
