# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""A minimal Anki collection: just the tables and collation anki-guard touches.

The ``unicase`` index mirrors the real schema, so ``quick_check`` fails on a
connection that forgot to register the collation -- the bug that made every
real read fail on 2026-10-04.
"""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

from anki_guard._snapshot import connect

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

# (revlog id in ms, time in ms, type), optionally + the card id it reviewed;
# without one the card counts as deleted (no deck).
Review = tuple[int, int, int] | tuple[int, int, int, int]
# card id -> (deck id, original deck id; 0 unless in a filtered deck)
Cards = dict[int, tuple[int, int]]


def _revlog_row(review: Review) -> tuple[int, int | None, int, int]:
    """``review`` in ``revlog`` column order, ``cid`` NULL when it has none."""
    review_id, spent, kind, *card = review
    return (review_id, card[0] if card else None, spent, kind)


def make_collection(
    path: Path,
    *,
    reviews: Iterable[Review] = (),
    decks: dict[int, str] | None = None,
    cards: Cards | None = None,
    rollover: object = None,
    legacy_conf: dict[str, object] | None = None,
    mod_ms: int = 1_700_000_000_000,
    wal: bool = False,
) -> None:
    """Create ``path`` as a tiny collection; ``wal`` leaves rows in a -wal file.

    ``legacy_conf`` builds the pre-``config``-table schema with ``col.conf``.
    ``decks`` maps id to the stored name (``\x1f`` between levels).
    """
    db = connect(path)
    try:
        if wal:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA wal_autocheckpoint=0")
        db.execute("CREATE TABLE col (mod INTEGER, conf TEXT)")
        db.execute(
            "INSERT INTO col VALUES (?, ?)",
            (mod_ms, json.dumps(legacy_conf) if legacy_conf is not None else ""),
        )
        if legacy_conf is None:
            db.execute(
                "CREATE TABLE config (key TEXT NOT NULL PRIMARY KEY COLLATE unicase, val BLOB)"
            )
            if rollover is not None:
                db.execute(
                    "INSERT INTO config VALUES ('rollover', ?)",
                    (json.dumps(rollover).encode(),),
                )
        db.execute(
            "CREATE TABLE revlog"
            " (id INTEGER PRIMARY KEY, cid INTEGER, time INTEGER, type INTEGER)"
        )
        db.executemany(
            "INSERT INTO revlog VALUES (?, ?, ?, ?)",
            [_revlog_row(r) for r in reviews],
        )
        db.execute(
            "CREATE TABLE decks (id INTEGER PRIMARY KEY, name TEXT COLLATE unicase)"
        )
        deck_rows = {1: "Default"} if decks is None else decks
        db.executemany("INSERT INTO decks VALUES (?, ?)", list(deck_rows.items()))
        db.execute(
            "CREATE TABLE cards (id INTEGER PRIMARY KEY, did INTEGER, odid INTEGER)"
        )
        db.executemany(
            "INSERT INTO cards VALUES (?, ?, ?)",
            [(cid, did, odid) for cid, (did, odid) in (cards or {}).items()],
        )
        db.commit()
        if wal:
            # Keep the WAL: copy it out before close() checkpoints it away.
            wal_file = path.with_name(path.name + "-wal")
            saved = wal_file.read_bytes()
            main = path.read_bytes()
    finally:
        db.close()
    if wal:
        path.write_bytes(main)
        wal_file.write_bytes(saved)


def raw(path: Path) -> sqlite3.Connection:
    """A plain connection, for tests that corrupt or inspect a file."""
    return sqlite3.connect(path)
