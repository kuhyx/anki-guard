# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The daily quotas one pass checks, each with its own deck filter and ledger.

Both read the same server collection; they differ in which reviews count:

- ``anki``: every deck **except** the automation deck, 12 min on workdays
  and 20 min on the other days.
- ``automation``: **only** the automation deck (PLC and industrial-control
  security study), 8 min on workdays and 25 min on the other days.

Workdays are ``freedays.WORKDAYS`` (Tue-Thu), the one definition
leetcode-guard, screen-locker and wake-alarm also read, so "cheap day" cannot
drift between gates. Since 2026-10-09 the two workday bars sum to 20 min, so
both fit between getting home (18:10) and 19:30. The split favours ``anki``:
it is the mature review deck, where a skipped day piles up as backlog, while
the automation deck is new material that can slow down for a day. The
automation bar never exceeds 25 min, the shutdown time it earns back, so the
task never costs more time than it returns (60 min until 2026-10-09).

Keeping the decks disjoint means one review never pays two quotas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import freedays

if TYPE_CHECKING:
    from datetime import date

# Top-level deck name in the collection; its subdecks count too.
AUTOMATION_DECK: Final = "Automation"

_MINUTE: Final = 60


@dataclass(frozen=True)
class Quota:
    """One daily bar on one slice of the collection.

    Attributes:
        name: Ledger id prefix and the label in every report line.
        deck: The deck (and its subdecks) the filter is about.
        include: ``True`` counts only that deck, ``False`` everything else.
        ledger_name: File name of this quota's ledger in the data dir.
        light_minutes: The bar on a workday (``freedays.WORKDAYS``).
        full_minutes: The bar on the other days.
    """

    name: str
    deck: str
    include: bool
    ledger_name: str
    light_minutes: int
    full_minutes: int

    def required_seconds(self, day: date) -> int:
        """The bar for ``day``, in seconds.

        Classifies the ``day`` it is given, never the wall clock, so the bar
        follows the Anki day being read.
        """
        workday = day.weekday() in freedays.WORKDAYS
        minutes = self.light_minutes if workday else self.full_minutes
        return minutes * _MINUTE


ANKI: Final = Quota(
    name="anki",
    deck=AUTOMATION_DECK,
    include=False,
    ledger_name="ledger.json",
    light_minutes=12,
    full_minutes=20,
)
AUTOMATION: Final = Quota(
    name="automation",
    deck=AUTOMATION_DECK,
    include=True,
    ledger_name="automation_ledger.json",
    light_minutes=8,
    full_minutes=25,
)

# Order is the order of the report lines.
QUOTAS: Final[tuple[Quota, ...]] = (ANKI, AUTOMATION)
