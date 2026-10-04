# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Every on-disk location anki-guard reads or writes.

Resolved through :func:`paths` at call time, never captured at import, so the
test suite can point the whole tree at a temp directory with one patch -- a
module constant copied into another module is how a sibling suite once wrote
fake rows into a live ledger.

``ANKI_GUARD_ROOT`` relocates the data dir (and with it the sync server's
``SYNC_BASE``) for a sandbox run; ``ANKI_GUARD_KEY`` swaps the signing key.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Final

_REAL_KEY: Final = Path("/etc/workout-locker/hmac.key")
_DEFAULT_USER: Final = "kuhy"


@dataclass(frozen=True)
class Paths:
    """The locations of one anki-guard installation.

    Attributes:
        data_dir: Private state: the ledger and the sync server's base.
        sync_user: The sync server account whose collection is read.
        key_file: The HMAC key shared with the sibling lockers.
    """

    data_dir: Path
    sync_user: str
    key_file: Path

    @property
    def ledger(self) -> Path:
        """The signed credit ledger the consumers read."""
        return self.data_dir / "ledger.json"

    @property
    def sync_base(self) -> Path:
        """``SYNC_BASE`` of ``anki --syncserver``: one folder per account."""
        return self.data_dir / "syncserver"

    @property
    def collection(self) -> Path:
        """The account's live collection, held open (exclusive, WAL) by the server."""
        return self.sync_base / self.sync_user / "collection.anki2"

    @property
    def write_lock(self) -> Path:
        """Serialises ledger writers (the timer and a manual ``check``)."""
        return self.data_dir / "write.lock"


def paths() -> Paths:
    """The active locations, honouring the sandbox environment variables."""
    root = os.environ.get("ANKI_GUARD_ROOT")
    data_dir = Path(root) if root else Path.home() / ".local" / "share" / "anki_guard"
    key = os.environ.get("ANKI_GUARD_KEY")
    return Paths(
        data_dir=data_dir,
        sync_user=os.environ.get("ANKI_GUARD_USER", _DEFAULT_USER),
        key_file=Path(key) if key else _REAL_KEY,
    )
