from __future__ import annotations

import json
import os
from pathlib import Path

from click.testing import CliRunner

from cartographer.atlas import Atlas
from cartographer.cli import main


def _init_atlas(atlas_root: Path, *, profile_ref: str | None = None) -> None:
    previous_skip = os.environ.get("CARTOGRAPHER_SKIP_VIMWIKI_PATCH")
    os.environ["CARTOGRAPHER_SKIP_VIMWIKI_PATCH"] = "1"
    try:
        Atlas(root=atlas_root).init(profile_ref=profile_ref)
    finally:
        if previous_skip is None:
            os.environ.pop("CARTOGRAPHER_SKIP_VIMWIKI_PATCH", None)
        else:
            os.environ["CARTOGRAPHER_SKIP_VIMWIKI_PATCH"] = previous_skip


def _write_note(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_trace_command_filters_by_predicate(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    _write_note(
        atlas_root / "projects" / "alpha.md",
        (
            "---\n"
            "id: alpha\n"
            "title: Alpha\n"
            "type: project\n"
            "created: '2026-04-21'\n"
            "modified: '2026-04-21'\n"
            "---\n\n"
            "# Alpha\n\n"
            '<!-- cart:wire target="beta" predicate="supports" -->\n'
            '<!-- cart:wire target="gamma" predicate="contradicts" -->\n'
        ),
    )
    _write_note(
        atlas_root / "projects" / "beta.md",
        (
            "---\n"
            "id: beta\n"
            "title: Beta\n"
            "type: project\n"
            "created: '2026-04-21'\n"
            "modified: '2026-04-21'\n"
            "---\n\n# Beta\n"
        ),
    )
    _write_note(
        atlas_root / "projects" / "gamma.md",
        (
            "---\n"
            "id: gamma\n"
            "title: Gamma\n"
            "type: project\n"
            "created: '2026-04-21'\n"
            "modified: '2026-04-21'\n"
            "---\n\n# Gamma\n"
        ),
    )
    Atlas(root=atlas_root).refresh_index()

    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))
    runner = CliRunner()
    result = runner.invoke(main, ["trace", "alpha", "--type", "supports", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["surface"] == "trace"
    assert [item["note_id"] for item in payload["results"]] == ["beta"]


def test_discover_export_outputs_raw_candidate_list(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    _write_note(
        atlas_root / "projects" / "alpha.md",
        (
            "---\n"
            "id: alpha\n"
            "title: Alpha\n"
            "type: project\n"
            "tags:\n- bridge\n- memory\n"
            "created: '2026-04-21'\n"
            "modified: '2026-04-21'\n"
            "---\n\nbridge memory support\n"
        ),
    )
    _write_note(
        atlas_root / "projects" / "beta.md",
        (
            "---\n"
            "id: beta\n"
            "title: Beta\n"
            "type: project\n"
            "tags:\n- bridge\n- memory\n"
            "created: '2026-04-21'\n"
            "modified: '2026-04-21'\n"
            "---\n\nbridge memory support\n"
        ),
    )
    Atlas(root=atlas_root).refresh_index()

    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))
    runner = CliRunner()
    result = runner.invoke(main, ["discover", "--threshold", "0.1", "--export"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert isinstance(payload, list)
    assert any({item["left_id"], item["right_id"]} == {"alpha", "beta"} for item in payload)


def test_profile_apply_reports_discovery_pass(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root, profile_ref="default")
    _write_note(
        atlas_root / "projects" / "alpha.md",
        (
            "---\n"
            "id: alpha\n"
            "title: Alpha\n"
            "type: project\n"
            "tags:\n- bridge\n- memory\n"
            "created: '2026-04-21'\n"
            "modified: '2026-04-21'\n"
            "---\n\nbridge memory support\n"
        ),
    )
    _write_note(
        atlas_root / "projects" / "beta.md",
        (
            "---\n"
            "id: beta\n"
            "title: Beta\n"
            "type: project\n"
            "tags:\n- bridge\n- memory\n"
            "created: '2026-04-21'\n"
            "modified: '2026-04-21'\n"
            "---\n\nbridge memory support\n"
        ),
    )
    Atlas(root=atlas_root).refresh_index()

    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))
    runner = CliRunner()
    result = runner.invoke(main, ["profile", "apply", "emotional-topology"])

    assert result.exit_code == 0
    assert "Profile applied: emotional-topology" in result.output
    assert "Running discovery pass with updated predicate vocabulary..." in result.output
    assert "Review with `cart discover --interactive`." in result.output
