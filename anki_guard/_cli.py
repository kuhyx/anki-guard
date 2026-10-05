# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""``python -m anki_guard {check,status}``.

``check`` is the timer's pass: it reads and records each finished quota.
``status`` reads only. Both print one line per quota; exit 0 when every quota
could be read, 3 when any could not (so the timer unit shows as failed).
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import logging
from typing import TYPE_CHECKING, Final

from anki_guard._gate import Report, Status, run
from anki_guard._paths import paths
from anki_guard._quota import QUOTAS

if TYPE_CHECKING:
    from collections.abc import Sequence

EXIT_UNKNOWN: Final = 3


def _clock(stamp: float) -> str:
    return datetime.fromtimestamp(stamp, tz=UTC).astimezone().strftime("%H:%M")


def _stamp(stamp: float) -> str:
    return datetime.fromtimestamp(stamp, tz=UTC).astimezone().strftime("%Y-%m-%d %H:%M")


def render(report: Report) -> str:
    """The one-line summary of one quota both commands print."""
    head = f"anki-guard {report.quota.name}: {report.status}"
    today = report.studied
    if today is None:
        return f"{head} -- {report.reason}"
    figures = (
        f"{today.seconds / 60:.1f}/{today.required_seconds // 60} min,"
        f" {today.reviews} reviews on Anki day {today.anki_day}"
    )
    synced = f"server copy last changed {_stamp(today.synced_at)}"
    line = f"{head} -- {figures} ({synced})"
    if today.crossed_at is not None:
        line += f"; bar crossed at {_clock(today.crossed_at)}"
    if report.reason:
        line += f"; {report.reason}"
    return line


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command and return the process exit code."""
    parser = argparse.ArgumentParser(prog="anki_guard", description=__doc__)
    parser.add_argument("command", choices=("check", "status"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    now = datetime.now(tz=UTC)
    reports = [
        run(paths(), now, quota, write=args.command == "check") for quota in QUOTAS
    ]
    for report in reports:
        print(render(report))
    return EXIT_UNKNOWN if any(r.status is Status.UNKNOWN for r in reports) else 0
