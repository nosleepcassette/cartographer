from __future__ import annotations

import json
import os
from pathlib import Path

from click.testing import CliRunner

from cartographer.atlas import Atlas
from cartographer.cli import main


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
            "created: '2026-04-18'\n"
            "modified: '2026-04-18'\n"
            "---\n\n"
            f"{body}\n"
        ),
        encoding="utf-8",
    )


def test_wire_add_list_and_traverse_json(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    _write_note(
        atlas_root / "projects" / "alpha.md",
        note_id="alpha",
        title="Alpha",
        note_type="project",
        body=(
            "# Alpha\n\n"
            '<!-- cart:block id="b-alpha-1" -->\n'
            "Alpha evidence.\n"
            "<!-- /cart:block -->"
        ),
    )
    _write_note(
        atlas_root / "projects" / "beta.md",
        note_id="beta",
        title="Beta",
        note_type="project",
        body="# Beta\n",
    )
    Atlas(root=atlas_root).refresh_index()

    runner = CliRunner()
    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))

    add_result = runner.invoke(
        main,
        [
            "wire",
            "add",
            "alpha#b-alpha-1",
            "beta",
            "--predicate",
            "supports",
            "--json",
        ],
    )

    assert add_result.exit_code == 0
    add_payload = json.loads(add_result.output)
    assert add_payload["surface"] == "wire.add"
    assert add_payload["created"] is True

    alpha_text = (atlas_root / "projects" / "alpha.md").read_text(encoding="utf-8")
    assert '<!-- cart:wire target="beta" predicate="supports" -->' in alpha_text

    list_result = runner.invoke(main, ["wire", "ls", "alpha#b-alpha-1", "--json"])

    assert list_result.exit_code == 0
    list_payload = json.loads(list_result.output)
    assert list_payload["surface"] == "wire.list"
    assert list_payload["count"] == 1
    assert list_payload["wires"][0]["predicate"] == "supports"
    assert list_payload["wires"][0]["target_note"] == "beta"

    traverse_result = runner.invoke(main, ["wire", "traverse", "alpha", "--json"])

    assert traverse_result.exit_code == 0
    traverse_payload = json.loads(traverse_result.output)
    assert traverse_payload["surface"] == "wire.traverse"
    assert "beta" in traverse_payload["visited"]
    assert traverse_payload["edge_count"] == 1


def test_wire_doctor_reports_invalid_and_orphan_targets(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    _write_note(
        atlas_root / "notes" / "alpha.md",
        note_id="alpha",
        title="Alpha",
        note_type="note",
        body=(
            "# Alpha\n\n"
            '<!-- cart:wire target="ghost" predicate="supports" -->\n'
            '<!-- cart:wire target="ghost" predicate="nonsense" -->\n'
            '<!-- cart:wire target="beta" -->\n'
        ),
    )
    _write_note(
        atlas_root / "notes" / "beta.md",
        note_id="beta",
        title="Beta",
        note_type="note",
        body="# Beta\n",
    )
    Atlas(root=atlas_root).refresh_index()

    runner = CliRunner()
    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))

    result = runner.invoke(main, ["wire", "doctor", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    codes = {issue["code"] for issue in payload["issues"]}
    assert payload["surface"] == "wire.doctor"
    assert "orphan_target_note" in codes
    assert "invalid_predicate" in codes
    assert "missing_predicate" in codes


def test_wire_gc_preview_and_apply_remove_problem_comments(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    alpha_path = atlas_root / "notes" / "alpha.md"
    _write_note(
        alpha_path,
        note_id="alpha",
        title="Alpha",
        note_type="note",
        body=(
            "# Alpha\n\n"
            '<!-- cart:wire target="ghost" predicate="supports" -->\n'
            '<!-- cart:wire target="beta" -->\n'
        ),
    )
    _write_note(
        atlas_root / "notes" / "beta.md",
        note_id="beta",
        title="Beta",
        note_type="note",
        body="# Beta\n",
    )
    Atlas(root=atlas_root).refresh_index()

    runner = CliRunner()
    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))

    preview_result = runner.invoke(main, ["wire", "gc", "--json"])

    assert preview_result.exit_code == 0
    preview_payload = json.loads(preview_result.output)
    assert preview_payload["surface"] == "wire.gc"
    assert preview_payload["candidate_count"] == 2
    assert preview_payload["removed_count"] == 0

    apply_result = runner.invoke(main, ["wire", "gc", "--apply", "--json"])

    assert apply_result.exit_code == 0
    apply_payload = json.loads(apply_result.output)
    assert apply_payload["removed_count"] == 2
    assert '<!-- cart:wire' not in alpha_path.read_text(encoding="utf-8")

    doctor_result = runner.invoke(main, ["wire", "doctor", "--json"])
    doctor_payload = json.loads(doctor_result.output)
    assert doctor_payload["issue_count"] == 0
