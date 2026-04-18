from __future__ import annotations

import json
import os
from pathlib import Path

from click.testing import CliRunner

from cartographer.atlas import Atlas
from cartographer.cli import main
from cartographer.working_set import add_entry as add_working_set_entry


def _init_atlas(atlas_root: Path) -> None:
    previous_skip = os.environ.get("CARTOGRAPHER_SKIP_VIMWIKI_PATCH")
    os.environ["CARTOGRAPHER_SKIP_VIMWIKI_PATCH"] = "1"
    try:
        Atlas(root=atlas_root).init()
    finally:
        if previous_skip is None:
            os.environ.pop("CARTOGRAPHER_SKIP_VIMWIKI_PATCH", None)
        else:
            os.environ["CARTOGRAPHER_SKIP_VIMWIKI_PATCH"] = previous_skip


def _write_session_note(
    path: Path,
    *,
    note_id: str,
    title: str,
    agent: str,
    date_value: str,
    summary_preview: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "---\n"
            f"id: {note_id}\n"
            f"title: {title}\n"
            "type: agent-log\n"
            f"agent: '{agent}'\n"
            f"date: '{date_value}'\n"
            f"summary_preview: '{summary_preview}'\n"
            "created: '2026-04-18'\n"
            "modified: '2026-04-18'\n"
            "---\n\n"
            "# Session\n"
        ),
        encoding="utf-8",
    )


def test_therapy_export_json_payload(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)

    add_working_set_entry(
        atlas_root,
        title="RSD spiral candidate",
        role="intake",
        scope="therapy",
        body="Need to verify Maggie evidence before acting.",
        provenance=["entities/maggie.md"],
        verification_needed=True,
    )
    _write_session_note(
        atlas_root / "agents" / "hermes" / "sessions" / "s1.md",
        note_id="hermes-session-s1",
        title="Hermes Session S1",
        agent="hermes",
        date_value="2026-04-18",
        summary_preview="held the intake line",
    )
    Atlas(root=atlas_root).refresh_index()

    runner = CliRunner()
    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))

    result = runner.invoke(main, ["therapy", "export", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == "2026-04-17"
    assert payload["surface"] == "therapy.export"
    assert payload["role"] == "intake"
    assert payload["scope"] == "therapy"
    assert payload["entry_count"] == 1
    assert payload["verification_needed_count"] == 1
    assert payload["entries"][0]["title"] == "RSD spiral candidate"
    assert payload["recent_sessions"][0]["agent"] == "hermes"


def test_therapy_export_writes_markdown_to_notes_namespace(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)

    add_working_set_entry(
        atlas_root,
        title="Counter-evidence prompt",
        role="intake",
        scope="therapy",
        provenance=["notes/example.md"],
    )

    runner = CliRunner()
    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))

    result = runner.invoke(main, ["therapy", "export"])

    assert result.exit_code == 0
    written = Path(result.output.strip())
    assert written.exists()
    assert written.parent == atlas_root / "notes" / "therapy" / "exports"
    text = written.read_text(encoding="utf-8")
    assert "Therapy Handoff" in text
    assert "Counter-evidence prompt" in text
