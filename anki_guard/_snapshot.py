# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""A consistent private copy of a collection the sync server holds open.

``anki --syncserver`` keeps each account's collection open with
``locking_mode=exclusive`` in WAL mode, so even a ``mode=ro`` connection gets
``database is locked`` (measured 2026-10-04). Reading means copying
``collection.anki2`` and ``collection.anki2-wal`` together and opening the
copy, where SQLite replays the WAL. ``-shm`` is skipped: it is rebuilt from
the WAL.

A copy taken while a sync is writing can be torn. Both files are stat'ed
before and after; any change, or a copy that fails ``quick_check``, is
retried. A copy that never settles is an error -- never a silent zero.
"""

from __future__ import annotations

from contextlib import contextmanager
import logging
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterator

_logger: Final = logging.getLogger(__name__)

ATTEMPTS: Final = 5
RETRY_SECONDS: Final = 2.0

Fingerprint = tuple[tuple[int, int] | None, ...]


class SnapshotError(Exception):
    """The collection could not be copied into a readable, consistent state."""


def _unicase(left: str, right: str) -> int:
    """Anki's case-insensitive collation; its indexes cannot be checked without it."""
    a, b = left.casefold(), right.casefold()
    return (a > b) - (a < b)


def connect(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    """Open a collection copy with the collation Anki's schema declares."""
    uri = f"file:{path}{'?mode=ro' if read_only else ''}"
    db = sqlite3.connect(uri, uri=True)
    db.create_collation("unicase", _unicase)
    return db


def _wal(path: Path) -> Path:
    return path.with_name(path.name + "-wal")


def _fingerprint(path: Path) -> Fingerprint:
    """(size, mtime_ns) of the database and its WAL; ``None`` if absent."""
    out: list[tuple[int, int] | None] = []
    for part in (path, _wal(path)):
        # A WAL that vanishes between exists() and stat() is a checkpoint;
        # the FileNotFoundError reaches snapshot(), which logs and retries.
        if not part.exists():
            out.append(None)
            continue
        stat = part.stat()
        out.append((stat.st_size, stat.st_mtime_ns))
    return tuple(out)


def _healthy(copy: Path) -> bool:
    """Whether the copy opens and passes ``quick_check``."""
    try:
        db = connect(copy)
        try:
            row = db.execute("PRAGMA quick_check").fetchone()
        finally:
            db.close()
    except sqlite3.DatabaseError as exc:
        _logger.warning("snapshot %s is unreadable (%s); retrying", copy, exc)
        return False
    if row is None or row[0] != "ok":
        _logger.warning("snapshot %s failed quick_check (%r); retrying", copy, row)
        return False
    return True


def _copy_once(source: Path, target: Path) -> bool:
    """One attempt: copy both files and report whether the copy is usable."""
    before = _fingerprint(source)
    if before[0] is None:
        msg = f"no collection at {source} (has the phone synced yet?)"
        raise SnapshotError(msg)
    _wal(target).unlink(missing_ok=True)
    shutil.copyfile(source, target)
    if before[1] is not None:
        shutil.copyfile(_wal(source), _wal(target))
    if _fingerprint(source) != before:
        _logger.warning("collection changed while copying; retrying")
        return False
    return _healthy(target)


def _attempt(source: Path, target: Path) -> bool:
    """One copy attempt; a checkpoint racing the copy is a retry, not an error.

    Raises:
        SnapshotError: The collection is missing or cannot be read at all.
    """
    try:
        return _copy_once(source, target)
    except FileNotFoundError as exc:
        # The WAL vanished between the stat and the copy: a checkpoint.
        _logger.warning("collection moved under the copy (%s); retrying", exc)
        return False
    except OSError as exc:
        msg = f"cannot copy {source}: {exc}"
        raise SnapshotError(msg) from exc


@contextmanager
def snapshot(
    source: Path,
    *,
    attempts: int = ATTEMPTS,
    pause: float = RETRY_SECONDS,
) -> Iterator[Path]:
    """Yield the path of a consistent copy of ``source``, removed afterwards.

    Raises:
        SnapshotError: No collection exists, it cannot be read, or every
            attempt was torn by a concurrent sync.
    """
    with tempfile.TemporaryDirectory(prefix="anki_guard-") as tmp:
        target = Path(tmp) / "collection.anki2"
        for attempt in range(attempts):
            if _attempt(source, target):
                break
            if attempt + 1 < attempts:
                time.sleep(pause)
        else:
            msg = f"no consistent copy of {source} after {attempts} attempts"
            raise SnapshotError(msg)
        yield target
