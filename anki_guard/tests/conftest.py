# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
"""Hermetic defaults: every path points into ``tmp_path``.

The real ledger, the sync server's collection and the real HMAC key are never
touched -- the sandbox variables are set for every test, and ``key`` is a
throwaway file.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import pytest

from anki_guard._paths import Paths, paths
from anki_guard.tests._collection import make_collection

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _warsaw(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Pin local time to the PC's zone, DST included, whatever the runner's is."""
    monkeypatch.setenv("TZ", "Europe/Warsaw")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture(autouse=True)
def ag_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Paths:
    """The active anki-guard paths for this test, all under ``tmp_path``."""
    key = tmp_path / "hmac.key"
    key.write_bytes(b"k" * 32)
    monkeypatch.setenv("ANKI_GUARD_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("ANKI_GUARD_KEY", str(key))
    monkeypatch.setenv("ANKI_GUARD_USER", "tester")
    return paths()


@pytest.fixture
def server_collection(ag_paths: Paths) -> Callable[..., Path]:
    """Build the sync server's collection for the test account."""

    def build(**kwargs: Any) -> Path:
        ag_paths.collection.parent.mkdir(parents=True, exist_ok=True)
        make_collection(ag_paths.collection, **kwargs)
        return ag_paths.collection

    return build
