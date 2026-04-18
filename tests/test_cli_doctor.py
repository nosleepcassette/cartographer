from __future__ import annotations

import json
import os
from pathlib import Path

from click.testing import CliRunner

from cartographer.atlas import Atlas
from cartographer.cli import main
from cartographer.config import save_config
from cartographer.tasks import append_task


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


def _write_note(path: Path, *, note_id: str, title: str, note_type: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "---\n"
            f"id: {note_id}\n"
            f"title: {title}\n"
            f"type: {note_type}\n"
            "created: '2026-04-17'\n"
            "modified: '2026-04-17'\n"
            "---\n\n"
            f"{body}\n"
        ),
        encoding="utf-8",
    )


def test_doctor_status_and_query_json_outputs(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    export_dir = tmp_path / "mapsos-exports"
    export_dir.mkdir(parents=True)
    (export_dir / "session_20260417_120000.json").write_text(
        '{"date":"2026-04-17","state":"stable"}',
        encoding="utf-8",
    )

    _init_atlas(atlas_root)
    atlas = Atlas(root=atlas_root)
    config = atlas.config
    config.setdefault("mapsos", {})["export_dir"] = str(export_dir)
    save_config(config, root=atlas_root)

    _write_note(
        atlas_root / "notes" / "alpha.md",
        note_id="alpha",
        title="Alpha",
        note_type="note",
        body="# Alpha\n",
    )
    append_task(atlas_root, "Ship doctor output", priority="P1", project="ops")
    atlas.refresh_index()

    runner = CliRunner()
    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))

    doctor_result = runner.invoke(main, ["doctor", "--json"])
    assert doctor_result.exit_code == 0
    doctor_payload = json.loads(doctor_result.output)
    assert doctor_payload["root"] == str(atlas_root)
    assert doctor_payload["initialized"] is True
    assert doctor_payload["mapsos"]["export_count"] == 1
    assert doctor_payload["index"]["exists"] is True

    status_result = runner.invoke(main, ["status", "--json"])
    assert status_result.exit_code == 0
    status_payload = json.loads(status_result.output)
    assert status_payload["root"] == str(atlas_root)
    assert status_payload["note_count"] >= 1

    query_result = runner.invoke(main, ["query", "--json", "type:note"])
    assert query_result.exit_code == 0
    query_payload = json.loads(query_result.output)
    assert any(str(atlas_root / "notes" / "alpha.md") == path for path in query_payload["results"])

    todo_result = runner.invoke(main, ["todo", "query", "--json", "status:open"])
    assert todo_result.exit_code == 0
    todo_payload = json.loads(todo_result.output)
    assert len(todo_payload["tasks"]) == 1
    assert todo_payload["tasks"][0]["text"] == "Ship doctor output"
    assert todo_payload["tasks"][0]["project"] == "ops"


def test_worklog_status_json_output(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)

    runner = CliRunner()
    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))

    result = runner.invoke(main, ["worklog", "status", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["current_session_id"] is None
    assert payload["in_progress"] == []
