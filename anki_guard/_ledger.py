# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The signed, append-only credit ledger -- the only state that carries value.

Same row shape and key as book-guard and leetcode-guard (``entry_id``,
``kind``, ``day``, ``created_at``, ``amount``, ``device``, ``detail``,
``hmac``), signed with ``earned_time.entry_signature``, so the consumers read
it through ``earned_time.done_today`` with no Anki-specific code.

One ``credit`` row per quota and Anki day, id ``<quota>:<YYYY-MM-DD>``
(``anki:`` in ``ledger.json``, ``automation:`` in ``automation_ledger.json``
-- each quota has its own file, so each earner reads one). ``detail`` values
are strings: ``anki_day`` (what the earner matches on), ``minutes``,
``reviews`` and ``studied_at`` (unix seconds of the review that crossed the
threshold). There are no negative rows: a day without a credit is a "no".

Tamper-evident, not tamper-proof: the key is world-readable, as for every
sibling locker.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import fcntl
import json
import logging
import os
from pathlib import Path
import socket
import tempfile
from typing import TYPE_CHECKING, Final

from earned_time import entry_signature, verified

if TYPE_CHECKING:
    from collections.abc import Iterator

    from anki_guard._quota import Quota
    from anki_guard._studied import Studied

_logger: Final = logging.getLogger(__name__)

CREDIT: Final = "credit"


class LedgerError(Exception):
    """The ledger exists but is not a ledger -- never silently emptied."""


def read_key(key_file: Path) -> bytes | None:
    """The signing key, or ``None`` (logged) when it is unreadable or empty."""
    try:
        key = key_file.read_bytes().strip()
    except OSError as exc:
        _logger.warning("cannot read the signing key at %s (%s)", key_file, exc)
        return None
    if not key:
        _logger.warning("the signing key at %s is empty", key_file)
    return key or None


def entry_id(studied: Studied, quota: Quota) -> str:
    """The one row id a given quota and Anki day can have."""
    return f"{quota.name}:{studied.anki_day.isoformat()}"


def credit_row(
    studied: Studied, quota: Quota, key: bytes, *, now: datetime
) -> dict[str, object]:
    """A signed credit row for a day that crossed the threshold."""
    if studied.crossed_at is None:
        msg = "a day below the threshold earns no credit row"
        raise ValueError(msg)
    row: dict[str, object] = {
        "entry_id": entry_id(studied, quota),
        "kind": CREDIT,
        "day": studied.anki_day.isoformat(),
        "created_at": now.astimezone(UTC).isoformat(),
        "amount": int(studied.seconds // 60),
        "device": socket.gethostname(),
        "detail": {
            "anki_day": studied.anki_day.isoformat(),
            "minutes": f"{studied.seconds / 60:.1f}",
            "reviews": str(studied.reviews),
            "studied_at": f"{studied.crossed_at:.3f}",
        },
    }
    row["hmac"] = entry_signature(row, key)
    return row


def read_rows(ledger: Path) -> list[object]:
    """The raw ``entries`` array, kept verbatim; a missing file is empty.

    Raises:
        LedgerError: The file is not JSON or has no ``entries`` array.
    """
    try:
        raw = json.loads(ledger.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _logger.warning("no ledger at %s yet; starting it", ledger)
        return []
    except ValueError as exc:
        msg = f"{ledger} is not valid JSON: {exc}"
        raise LedgerError(msg) from exc
    rows = raw.get("entries") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        msg = f"{ledger} has no entries array"
        raise LedgerError(msg)
    return rows


def has_credit(rows: list[object], row_id: str, key: bytes) -> bool:
    """Whether a verified credit with ``row_id`` is already recorded."""
    return any(
        isinstance(row, dict)
        and row.get("entry_id") == row_id
        and row.get("kind") == CREDIT
        and verified(row, key)
        for row in rows
    )


def write_rows(ledger: Path, rows: list[object]) -> None:
    """Atomically replace the ledger: readers see the old file or the new one."""
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=ledger.parent, suffix=".tmp", delete=False
    ) as handle:
        json.dump({"entries": rows}, handle, indent=1)
        handle.flush()
        os.fsync(handle.fileno())
    Path(handle.name).replace(ledger)


@contextmanager
def exclusive(lock_file: Path) -> Iterator[None]:
    """Hold the ledger write lock; the kernel drops it if the holder dies."""
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with lock_file.open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
