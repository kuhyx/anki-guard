# anki-guard -- notes for agents

Read README.md first. These are the invariants that are easy to break.

## Invariants

- **The gate only publishes facts.** One HMAC-signed `credit` row per Anki
  day in `~/.local/share/anki_guard/ledger.json`. It never writes the
  shutdown schedule or the gaming budget: earned_time's `anki` earner does.
- **Anki's own figure.** `revlog` since the collection's rollover, excluding
  manual (4) and rescheduled (5) rows; verified equal to
  `Collection.studied_today()` on 2026-10-04. Never hard-code the rollover.
- **Never open the live collection.** The sync server holds it exclusive/WAL;
  `_snapshot` copies `.anki2` + `-wal`, retries a torn copy, and needs the
  `unicase` collation for `quick_check`.
- **"Could not check" is not "no".** Unreadable = `unknown`, exit 3, nothing
  written. A readable but stale copy shows `synced_at`.
- **The sync account is secret.** `~/.config/anki_guard/syncserver.env`
  (0600) holds `SYNC_USER1`; never commit it or put it in a unit.

## Layout

- `anki_guard/` -- the gate (`check` = timer pass, `status` = read only).
- `anki-syncserver.service` -- `python3 -m anki.syncserver` (system anki-git).
- `anki-guard.{service,timer}` -- the ten-minute pass. `install.sh` installs all.
- `scripts/setup_phone.sh` -- AnkiDroid -> this server, `--verify-only` rerun.

## Commands

The sandbox is `ANKI_GUARD_ROOT=<dir>` (its own ledger and `syncserver/`) plus
`ANKI_GUARD_KEY=<file>`; the timer runs the installed copy, never this tree.

- run: `ANKI_GUARD_ROOT=.demo ANKI_GUARD_KEY=.demo/key .venv/bin/python -m anki_guard status`
- test: `.venv/bin/python -m pytest -q`
- test-changed: `scripts/test_changed.sh`
- lint: `.venv/bin/ruff check . && .venv/bin/python -m mypy anki_guard`
- coverage: `.venv/bin/python -m pytest -q --cov-report=lcov:coverage.lcov`
- coverage-gaps: `coverage-gaps coverage.lcov`
