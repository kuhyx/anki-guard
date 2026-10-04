# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
from __future__ import annotations

from datetime import UTC, date, datetime
import runpy

import pytest

from anki_guard import _cli
from anki_guard._gate import Report, Status
from anki_guard._studied import Studied

STAMP = datetime(2026, 10, 4, 17, 46, tzinfo=UTC).timestamp()


def test_render_unknown() -> None:
    assert (
        _cli.render(Report(Status.UNKNOWN, reason="no collection"))
        == "anki-guard: unknown -- no collection"
    )


def test_render_done_with_crossing_and_reason() -> None:
    studied = Studied(date(2026, 10, 4), 43, 2520.0, STAMP, STAMP)
    line = _cli.render(Report(Status.UNKNOWN, studied, "disk full"))
    assert line == (
        "anki-guard: unknown -- 42.0/20 min, 43 reviews on Anki day 2026-10-04"
        " (server copy last changed 2026-10-04 19:46); bar crossed at 19:46; disk full"
    )


def test_render_short() -> None:
    studied = Studied(date(2026, 10, 4), 2, 90.0, None, STAMP)
    assert _cli.render(Report(Status.SHORT, studied)).endswith(
        "(server copy last changed 2026-10-04 19:46)"
    )


@pytest.mark.parametrize(("command", "write"), [("check", True), ("status", False)])
def test_main_exit_codes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    write: bool,
) -> None:
    seen: dict[str, bool] = {}

    def fake_run(paths: object, now: object, *, write: bool) -> Report:
        seen["write"] = write
        return Report(Status.SHORT, Studied(date(2026, 10, 4), 0, 0.0, None, STAMP))

    monkeypatch.setattr(_cli, "run", fake_run)
    assert _cli.main([command]) == 0
    assert seen["write"] is write
    assert capsys.readouterr().out.startswith("anki-guard: short")


def test_main_unknown_exits_3(capsys: pytest.CaptureFixture[str]) -> None:
    assert _cli.main(["check"]) == _cli.EXIT_UNKNOWN
    assert "has the phone synced yet" in capsys.readouterr().out


def test_module_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["anki_guard", "status"])
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("anki_guard", run_name="__main__")
    assert exit_info.value.code == _cli.EXIT_UNKNOWN
