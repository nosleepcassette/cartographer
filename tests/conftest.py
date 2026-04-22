from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _skip_auto_embed_during_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARTOGRAPHER_SKIP_AUTO_EMBED", "1")
