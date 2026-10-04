# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Regressions in scripts/phone_*.py found on the real phone (2026-10-04).

The scripts are not part of the package; pytest's ``pythonpath`` puts
``scripts/`` on the path, and every adb/journalctl call returns canned output.
"""

from __future__ import annotations

import subprocess

import phone_setup_auto
import phone_ui
import pytest

# Verbatim shape of an anki-syncserver journal line: tracing colours it even
# when stderr is the journal, splitting `uid="kuhy"` with escape codes.
_E = "\x1b"
_LINE = (
    f"{_E}[2m2026-10-04T18:46:41Z{_E}[0m {_E}[32m INFO{_E}[0m {_E}[1mrequest{_E}[0m"
    f'{_E}[1m{{{_E}[0m{_E}[3muri{_E}[0m{_E}[2m={_E}[0m"{{uri}}" {_E}[3mip{_E}[0m'
    f'{_E}[2m={_E}[0m"127.0.0.1" {_E}[3muid{_E}[0m{_E}[2m={_E}[0m"kuhy" '
    f'{_E}[3mclient{_E}[0m{_E}[2m={_E}[0m"25.09.2,3890e12c,android" session'
)


def _done(stdout: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")


def test_phone_requests_reads_coloured_journal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Uploads must be visible through the colour codes, or the guard is blind."""
    journal = "\n".join(
        _LINE.replace("{uri}", u) for u in ("/sync/download", "/sync/upload")
    )
    monkeypatch.setattr(phone_setup_auto, "run", lambda _cmd: _done(journal))
    assert phone_setup_auto.phone_requests("2026-10-04 20:30:00", "kuhy") == [
        ("/sync/download", "25.09.2,3890e12c,android"),
        ("/sync/upload", "25.09.2,3890e12c,android"),
    ]


def _node(package: str, text: str) -> str:
    return f'<node text="{text}" package="{package}" bounds="[0,0][100,100]" />'


def _phone(monkeypatch: pytest.MonkeyPatch, dumps: list[str]) -> list[list[str]]:
    """A Phone whose dumps come from ``dumps``; returns every adb argv run."""
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kw: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return _done(dumps.pop(0) if "uiautomator" in cmd else "")

    monkeypatch.setattr(phone_ui, "run", fake_run)
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/adb")
    monkeypatch.setattr("time.sleep", lambda _s: None)
    return calls


def test_dump_declines_google_save_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """Google's "save password?" sheet gets "Not now", then the app is read."""
    gms = "com.google.android.gms"
    calls = _phone(
        monkeypatch,
        [
            _node(gms, "Zapisz") + _node(gms, "Nie teraz"),
            _node("com.ichi2.anki", "LeetCode"),
        ],
    )
    screen = phone_ui.Phone("com.ichi2.anki").dump()
    assert screen.find(texts=frozenset({"LeetCode"})) is not None
    assert ["/usr/bin/adb", "shell", "input", "-d", "0", "tap", "50", "50"] in calls


def test_dump_refuses_other_foreign_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anything else, or a sheet that will not go away, stops the run."""
    gms = "com.google.android.gms"
    _phone(monkeypatch, [_node(gms, "Nie teraz"), _node(gms, "Nie teraz")])
    with pytest.raises(phone_ui.StepError, match=r"not com\.ichi2\.anki"):
        phone_ui.Phone("com.ichi2.anki").dump()
    _phone(monkeypatch, [_node("com.android.systemui", "Nie teraz")])
    with pytest.raises(phone_ui.StepError, match=r"not com\.ichi2\.anki"):
        phone_ui.Phone("com.ichi2.anki").dump()
