# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""One pass: read today's study off the server and credit a finished day.

The gate only publishes a fact. It never writes the shutdown schedule or the
gaming budget -- earned_time's ``anki`` earner turns a credit row into time.

**"Could not check" is not "no".** A missing collection, a torn copy or an
unreadable key is ``UNKNOWN`` and exits non-zero, so the timer's journal
shows it; it writes nothing. A copy that reads fine but shows little study may
just be stale (the phone has not synced yet), which is why every report
carries ``synced_at``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import logging
from typing import TYPE_CHECKING, Final

from anki_guard import _ledger
from anki_guard._snapshot import SnapshotError, snapshot
from anki_guard._studied import CollectionError, Studied, studied

if TYPE_CHECKING:
    from datetime import datetime

    from anki_guard._paths import Paths

_logger: Final = logging.getLogger(__name__)

# Anki's own studied-today figure must reach this, every day.
REQUIRED_SECONDS: Final = 20 * 60


class Status(StrEnum):
    """Where today stands."""

    CREDITED = "credited"  # crossed the bar; this pass wrote the row
    ALREADY = "already"  # crossed the bar; the row was already there
    DONE = "done"  # crossed the bar; read-only pass, nothing written
    SHORT = "short"  # below the bar on the server's copy
    UNKNOWN = "unknown"  # could not read the collection, ledger or key


@dataclass(frozen=True)
class Report:
    """The outcome of one pass."""

    status: Status
    studied: Studied | None = None
    reason: str = ""


def _read(paths: Paths, now: datetime) -> Studied:
    with snapshot(paths.collection) as copy:
        return studied(copy, now, REQUIRED_SECONDS)


def run(paths: Paths, now: datetime, *, write: bool) -> Report:
    """Read today's study and, when ``write``, record a finished day."""
    try:
        today = _read(paths, now)
    except (SnapshotError, CollectionError) as exc:
        _logger.warning("cannot read the Anki collection: %s", exc)
        return Report(Status.UNKNOWN, reason=str(exc))
    if today.crossed_at is None:
        return Report(Status.SHORT, today)
    if not write:
        return Report(Status.DONE, today)
    return _record(paths, today, now)


def _record(paths: Paths, today: Studied, now: datetime) -> Report:
    """Append today's credit unless it is already there."""
    key = _ledger.read_key(paths.key_file)
    if key is None:
        return Report(Status.UNKNOWN, today, f"no signing key at {paths.key_file}")
    try:
        with _ledger.exclusive(paths.write_lock):
            rows = _ledger.read_rows(paths.ledger)
            if _ledger.has_credit(rows, _ledger.entry_id(today), key):
                return Report(Status.ALREADY, today)
            rows.append(_ledger.credit_row(today, key, now=now))
            _ledger.write_rows(paths.ledger, rows)
    except (_ledger.LedgerError, OSError) as exc:
        _logger.warning("cannot record today's credit: %s", exc)
        return Report(Status.UNKNOWN, today, str(exc))
    return Report(Status.CREDITED, today)
