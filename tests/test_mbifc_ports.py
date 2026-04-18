from __future__ import annotations

import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_dispatcher_doc_has_required_protocol_sections() -> None:
    text = (REPO_ROOT / "AGENT_DISPATCHER.md").read_text(encoding="utf-8")
    assert "### Suggested next agent" in text
    assert "**No duplicates**" in text
    assert "**No circular chains**" in text
    assert "**Max depth 3**" in text
    assert "**On overflow**" in text
    assert "cart daily-brief" in text
    assert "create-skill" in text


def test_orchestra_scripts_exist_and_stay_small() -> None:
    expected = [
        "cart-today",
        "cart-state-today",
        "cart-inbox",
        "cart-worklog",
        "cart-health",
        "cart-recent",
    ]
    for name in expected:
        path = REPO_ROOT / "orchestra" / name
        text = path.read_text(encoding="utf-8")
        assert text.startswith("#!/usr/bin/env zsh\n")
        assert len(text.splitlines()) <= 15
        assert os.access(path, os.X_OK)


def test_create_skill_covers_all_interview_phases() -> None:
    text = (REPO_ROOT / "skills" / "create-skill" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    for heading in (
        "### Phase 1 — Purpose",
        "### Phase 2 — Triggers",
        "### Phase 3 — Inputs",
        "### Phase 4 — Outputs",
        "### Phase 5 — Model Fit",
        "### Phase 6 — Acceptance Test",
    ):
        assert heading in text
    assert "Do not create the file before the final confirmation" in text
    assert "YAML frontmatter" in text
