# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from earned_time import Earner, done_today

from anki_guard import _ledger
from anki_guard._gate import Status, run
from anki_guard._quota import ANKI as QUOTA

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest

    from anki_guard._paths import Paths


NOW = datetime(2026, 10, 4, 17, 0, tzinfo=UTC)  # 19:00 CEST
STUDY = [
    (int(datetime(2026, 10, 4, 9, m).astimezone().timestamp() * 1000), 60_000, 1)
    for m in range(21)
]


def _anki_match(row: dict[str, object], window: tuple[float, float]) -> bool:
    local = datetime.fromtimestamp(window[0], tz=UTC).astimezone().date()
    detail = row["detail"]
    assert isinstance(detail, dict)
    return bool(detail["anki_day"] == local.isoformat())


ANKI = Earner(
    "anki", "Anki", 30, 30, ledger="x", match=_anki_match, missing_ledger_is_no=True
)


def test_unknown_without_a_collection(ag_paths: Paths) -> None:
    report = run(ag_paths, NOW, QUOTA, write=True)
    assert report.status is Status.UNKNOWN
    assert "has the phone synced yet" in report.reason
    assert not ag_paths.ledger(QUOTA).exists()


def test_short_writes_nothing(
    ag_paths: Paths, server_collection: Callable[..., Path]
) -> None:
    server_collection(rollover=0, reviews=STUDY[:5])
    report = run(ag_paths, NOW, QUOTA, write=True)
    assert report.status is Status.SHORT
    assert report.studied is not None
    assert report.studied.reviews == 5
    assert not ag_paths.ledger(QUOTA).exists()


def test_status_never_writes(
    ag_paths: Paths, server_collection: Callable[..., Path]
) -> None:
    server_collection(rollover=0, reviews=STUDY)
    assert run(ag_paths, NOW, QUOTA, write=False).status is Status.DONE
    assert not ag_paths.ledger(QUOTA).exists()


def test_credit_once_and_consumers_see_it(
    ag_paths: Paths, server_collection: Callable[..., Path]
) -> None:
    server_collection(rollover=0, reviews=STUDY)
    assert run(ag_paths, NOW, QUOTA, write=True).status is Status.CREDITED
    assert run(ag_paths, NOW, QUOTA, write=True).status is Status.ALREADY
    rows = _ledger.read_rows(ag_paths.ledger(QUOTA))
    assert len(rows) == 1
    # The consumer side: earned_time's shared reader on the same files.
    assert done_today(ANKI, ag_paths.ledger(QUOTA), ag_paths.key_file, now=NOW) is True
    tomorrow = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
    assert (
        done_today(ANKI, ag_paths.ledger(QUOTA), ag_paths.key_file, now=tomorrow)
        is False
    )


def test_late_night_study_belongs_to_the_previous_anki_day(
    ag_paths: Paths, server_collection: Callable[..., Path]
) -> None:
    late = [
        (int(datetime(2026, 10, 5, 1, m).astimezone().timestamp() * 1000), 60_000, 1)
        for m in range(21)
    ]
    server_collection(rollover=4, reviews=late)
    report = run(
        ag_paths, datetime(2026, 10, 4, 23, 30, tzinfo=UTC), QUOTA, write=True
    )  # 01:30 local
    assert report.studied is not None
    assert report.studied.anki_day == date(2026, 10, 4)
    assert report.status is Status.CREDITED


def test_no_key_is_unknown(
    ag_paths: Paths, server_collection: Callable[..., Path]
) -> None:
    server_collection(rollover=0, reviews=STUDY)
    ag_paths.key_file.unlink()
    report = run(ag_paths, NOW, QUOTA, write=True)
    assert report.status is Status.UNKNOWN
    assert "no signing key" in report.reason


def test_corrupt_ledger_is_unknown_and_untouched(
    ag_paths: Paths, server_collection: Callable[..., Path]
) -> None:
    server_collection(rollover=0, reviews=STUDY)
    ag_paths.ledger(QUOTA).parent.mkdir(parents=True, exist_ok=True)
    ag_paths.ledger(QUOTA).write_text("{")
    report = run(ag_paths, NOW, QUOTA, write=True)
    assert report.status is Status.UNKNOWN
    assert Path(ag_paths.ledger(QUOTA)).read_text() == "{"


def test_not_a_collection_is_unknown(
    ag_paths: Paths,
    server_collection: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("anki_guard._snapshot.time.sleep", lambda _s: None)
    path = server_collection()
    path.write_bytes(b"x" * 4096)
    report = run(ag_paths, NOW, QUOTA, write=False)
    assert report.status is Status.UNKNOWN


def test_an_uncheckable_copy_is_unknown(
    ag_paths: Paths,
    server_collection: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from anki_guard import _gate
    from anki_guard._studied import CollectionError

    server_collection()

    def broken(*_args: object) -> None:
        msg = "schema"
        raise CollectionError(msg)

    monkeypatch.setattr(_gate, "studied", broken)
    assert run(ag_paths, NOW, QUOTA, write=True).status is Status.UNKNOWN
