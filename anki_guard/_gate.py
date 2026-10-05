# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""One pass: read today's study off the server and credit each finished quota.

The gate only publishes facts. It never writes the shutdown schedule or the
gaming budget -- earned_time's ``anki`` and ``automation`` earners turn a
credit row into time. Every quota reads its own snapshot copy and is judged
on its own, so one unreadable read never blocks the other's credit.

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
    from anki_guard._quota import Quota

_logger: Final = logging.getLogger(__name__)


class Status(StrEnum):
    """Where today stands."""

    CREDITED = "credited"  # crossed the bar; this pass wrote the row
    ALREADY = "already"  # crossed the bar; the row was already there
    DONE = "done"  # crossed the bar; read-only pass, nothing written
    SHORT = "short"  # below the bar on the server's copy
    UNKNOWN = "unknown"  # could not read the collection, ledger or key


@dataclass(frozen=True)
class Report:
    """The outcome of one quota's pass."""

    quota: Quota
    status: Status
    studied: Studied | None = None
    reason: str = ""


def _read(paths: Paths, now: datetime, quota: Quota) -> Studied:
    with snapshot(paths.collection) as copy:
        return studied(copy, now, quota)


def run(paths: Paths, now: datetime, quota: Quota, *, write: bool) -> Report:
    """Read ``quota``'s study today and, when ``write``, record a finished day."""
    try:
        today = _read(paths, now, quota)
    except (SnapshotError, CollectionError) as exc:
        _logger.warning("cannot read the Anki collection: %s", exc)
        return Report(quota, Status.UNKNOWN, reason=str(exc))
    if today.crossed_at is None:
        return Report(quota, Status.SHORT, today)
    if not write:
        return Report(quota, Status.DONE, today)
    return _record(paths, quota, today, now)


def _record(paths: Paths, quota: Quota, today: Studied, now: datetime) -> Report:
    """Append today's credit to ``quota``'s ledger unless it is already there."""
    key = _ledger.read_key(paths.key_file)
    if key is None:
        return Report(
            quota, Status.UNKNOWN, today, f"no signing key at {paths.key_file}"
        )
    ledger = paths.ledger(quota)
    try:
        with _ledger.exclusive(paths.write_lock):
            rows = _ledger.read_rows(ledger)
            if _ledger.has_credit(rows, _ledger.entry_id(today, quota), key):
                return Report(quota, Status.ALREADY, today)
            rows.append(_ledger.credit_row(today, quota, key, now=now))
            _ledger.write_rows(ledger, rows)
    except (_ledger.LedgerError, OSError) as exc:
        _logger.warning("cannot record today's %s credit: %s", quota.name, exc)
        return Report(quota, Status.UNKNOWN, today, str(exc))
    return Report(quota, Status.CREDITED, today)
