# Copyright (c) 2026 Krzysztof Rudnicki. MIT License.
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from anki_guard._paths import paths

if TYPE_CHECKING:
    import pytest

    from anki_guard._paths import Paths


def test_sandbox_variables(tmp_path: Path, ag_paths: Paths) -> None:
    assert ag_paths.data_dir == tmp_path / "data"
    assert ag_paths.ledger == tmp_path / "data" / "ledger.json"
    assert (
        ag_paths.collection
        == tmp_path / "data" / "syncserver" / "tester" / "collection.anki2"
    )
    assert ag_paths.write_lock == tmp_path / "data" / "write.lock"
    assert ag_paths.key_file == tmp_path / "hmac.key"


def test_real_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ANKI_GUARD_ROOT", "ANKI_GUARD_KEY", "ANKI_GUARD_USER"):
        monkeypatch.delenv(name)
    real = paths()
    assert real.data_dir == Path.home() / ".local" / "share" / "anki_guard"
    assert real.sync_user == "kuhy"
    assert real.key_file == Path("/etc/workout-locker/hmac.key")
