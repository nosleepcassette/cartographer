from __future__ import annotations

import os
from pathlib import Path

from click.testing import CliRunner

from cartographer.atlas import Atlas
from cartographer.cli import main
from cartographer.graph_export import load_graph_payload


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


def test_graph_export_html_writes_visual_graph(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    _write_note(
        atlas_root / "projects" / "alpha.md",
        note_id="alpha",
        title="Alpha",
        note_type="project",
        body="# Alpha\n\nSee [[beta]].",
    )
    _write_note(
        atlas_root / "entities" / "beta.md",
        note_id="beta",
        title="Beta",
        note_type="entity",
        body="# Beta\n",
    )
    Atlas(root=atlas_root).refresh_index()

    runner = CliRunner()
    output_path = atlas_root / "graph.html"
    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))

    result = runner.invoke(main, ["graph", "--format", "html", "--export", str(output_path)])

    assert result.exit_code == 0
    html = output_path.read_text(encoding="utf-8")
    assert "atlasGraphPayload" in html
    assert "Knowledge Graph V1" in html
    assert '"id": "alpha"' in html
    assert '"source": "alpha"' in html


def test_graph_export_json_still_writes_payload(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    _write_note(
        atlas_root / "notes" / "solo.md",
        note_id="solo",
        title="Solo",
        note_type="note",
        body="# Solo\n",
    )
    Atlas(root=atlas_root).refresh_index()

    runner = CliRunner()
    output_path = atlas_root / "graph.json"
    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))

    result = runner.invoke(main, ["graph", "--format", "json", "--export", str(output_path)])

    assert result.exit_code == 0
    payload = output_path.read_text(encoding="utf-8")
    assert '"node_count":' in payload
    assert '"id": "solo"' in payload


def test_graph_payload_normalizes_path_targets_to_canonical_ids(tmp_path) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    _write_note(
        atlas_root / "projects" / "alpha.md",
        note_id="alpha",
        title="Alpha",
        note_type="project",
        body="# Alpha\n\nSee [[entities/index]].",
    )
    Atlas(root=atlas_root).refresh_index()

    payload = load_graph_payload(atlas_root)
    edges = {(edge["source"], edge["target"]) for edge in payload["edges"]}

    assert ("alpha", "entities-index") in edges
    assert all(edge["target"] != "entities/index" for edge in payload["edges"])


def test_graph_payload_includes_semantic_wires(tmp_path) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    _write_note(
        atlas_root / "projects" / "alpha.md",
        note_id="alpha",
        title="Alpha",
        note_type="project",
        body=(
            "# Alpha\n\n"
            '<!-- cart:wire target="beta" predicate="supports" -->\n'
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

    payload = load_graph_payload(atlas_root)
    wire_edges = [edge for edge in payload["edges"] if edge.get("kind") == "wire"]

    assert payload["wire_count"] == 1
    assert wire_edges == [
        {
            "source": "alpha",
            "target": "beta",
            "kind": "wire",
            "predicate": "supports",
            "bidirectional": False,
        }
    ]
