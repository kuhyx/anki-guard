# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""The daily quotas one pass checks, each with its own deck filter and ledger.

Both read the same server collection; they differ in which reviews count:

- ``anki``: every deck **except** the automation deck, 20 min every day.
- ``automation``: **only** the automation deck (PLC and industrial-control
  security study), 60 min on Mon, Fri, Sat and Sun and 20 min Tue-Thu -- the
  same light-midweek shape book-guard and leetcode-guard use.

Keeping the decks disjoint means one review never pays two quotas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from datetime import date

# Top-level deck name in the collection; its subdecks count too.
AUTOMATION_DECK: Final = "Automation"

_MINUTE: Final = 60
_LIGHT_DAYS: Final = frozenset({1, 2, 3})  # Tue, Wed, Thu (date.weekday())


@dataclass(frozen=True)
class Quota:
    """One daily bar on one slice of the collection.

    Attributes:
        name: Ledger id prefix and the label in every report line.
        deck: The deck (and its subdecks) the filter is about.
        include: ``True`` counts only that deck, ``False`` everything else.
        ledger_name: File name of this quota's ledger in the data dir.
        light_minutes: The bar on Tue-Thu.
        full_minutes: The bar on the other days.
    """

    name: str
    deck: str
    include: bool
    ledger_name: str
    light_minutes: int
    full_minutes: int

    def required_seconds(self, day: date) -> int:
        """The bar for ``day``, in seconds."""
        minutes = (
            self.light_minutes if day.weekday() in _LIGHT_DAYS else self.full_minutes
        )
        return minutes * _MINUTE


ANKI: Final = Quota(
    name="anki",
    deck=AUTOMATION_DECK,
    include=False,
    ledger_name="ledger.json",
    light_minutes=20,
    full_minutes=20,
)
AUTOMATION: Final = Quota(
    name="automation",
    deck=AUTOMATION_DECK,
    include=True,
    ledger_name="automation_ledger.json",
    light_minutes=20,
    full_minutes=60,
)

# Order is the order of the report lines.
QUOTAS: Final[tuple[Quota, ...]] = (ANKI, AUTOMATION)
