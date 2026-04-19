from __future__ import annotations

import json
import os
from pathlib import Path

from click.testing import CliRunner

from cartographer.atlas import Atlas
from cartographer.cli import main
from cartographer.graph_export import load_graph_payload, render_graph_html


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


def _write_note_with_frontmatter(path: Path, frontmatter: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "---\n"
            f"{frontmatter}"
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
    assert "Atlas Graph" in html
    assert 'data-theme="baseline"' in html
    assert "show-sessions" in html
    assert "show-all-types" in html
    assert "export-png" in html
    assert "copy-link" in html
    assert "const THREE = {" in html
    assert "new THREE.WebGLRenderer" in html
    assert "privacy-mode" in html
    assert "show-all-folders" in html
    assert "folder-chip-list" in html
    assert "theme-picker" in html
    assert "toggle-help" in html
    assert "show-wires" in html
    assert "smartFitCamera" in html
    assert "createGlyphTexture" in html
    assert "new THREE.SpriteMaterial" in html
    assert "edge-label" in html
    assert "ASTRAL_WIRE_ASPECTS" in html
    assert "renderPreviewMarkdown" in html
    assert "detailPreviewEl.innerHTML" in html
    assert "Emotional Topology" in html
    assert "detail-emotional" in html
    assert "wiki-link" in html
    assert ".preview table" in html
    assert "window.CART_THEMES" in html
    assert "<!-- CART-THEME-SCRIPTS -->" in html
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


def test_graph_export_command_rebuilds_stale_index_before_export(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    alpha_path = atlas_root / "projects" / "alpha.md"
    _write_note(
        alpha_path,
        note_id="alpha",
        title="Alpha",
        note_type="project",
        body="# Alpha\n",
    )
    _write_note(
        atlas_root / "entities" / "maps.md",
        note_id="maps",
        title="maps",
        note_type="entity",
        body="# maps\n",
    )
    Atlas(root=atlas_root).refresh_index()

    alpha_path.write_text(
        (
            "---\n"
            "id: alpha\n"
            "title: Alpha\n"
            "type: project\n"
            "created: '2026-04-18'\n"
            "modified: '2026-04-18'\n"
            "---\n\n"
            "# Alpha\n\n"
            '<!-- cart:wire target="maps" predicate="active-project" relationship="active-project" emotional_valence="positive" energy_impact="energizing" avoidance_risk="medium" growth_edge="true" current_state="building" -->\n'
        ),
        encoding="utf-8",
    )

    runner = CliRunner()
    output_path = atlas_root / "graph.json"
    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))

    result = runner.invoke(main, ["graph", "--format", "json", "--export", str(output_path)])

    assert result.exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    alpha = next(node for node in payload["nodes"] if node["id"] == "alpha")
    wire = next(edge for edge in payload["edges"] if edge.get("kind") == "wire")
    assert alpha["emotional_valence"] == "positive"
    assert alpha["avoidance_risk"] == "medium"
    assert wire["predicate"] == "active-project"
    assert wire["emotional_valence"] == "positive"


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
    assert len(wire_edges) == 1
    assert wire_edges[0]["source"] == "alpha"
    assert wire_edges[0]["target"] == "beta"
    assert wire_edges[0]["kind"] == "wire"
    assert wire_edges[0]["predicate"] == "supports"
    assert wire_edges[0]["bidirectional"] is False
    assert wire_edges[0]["emotional_valence"] is None


def test_graph_payload_includes_preview_and_session_flag(tmp_path) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    _write_note(
        atlas_root / "agents" / "sessions" / "nightly.md",
        note_id="nightly",
        title="Nightly",
        note_type="session",
        body="# Nightly\n\nThis is the reflected preview body.",
    )
    Atlas(root=atlas_root).refresh_index()

    payload = load_graph_payload(atlas_root)
    node = next(item for item in payload["nodes"] if item["id"] == "nightly")

    assert node["is_session"] is True
    assert node["preview"].startswith("# Nightly")
    assert "\n\n" in node["preview"]
    assert "reflected preview body" in node["preview"].lower()


def test_graph_payload_promotes_entity_people_to_person_type(tmp_path) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    _write_note_with_frontmatter(
        atlas_root / "entities" / "killian.md",
        (
            "id: killian\n"
            "title: Killian\n"
            "type: entity\n"
            "entity_type: person\n"
            "created: '2026-04-18'\n"
            "modified: '2026-04-18'\n"
        ),
        "# Killian\n",
    )
    _write_note_with_frontmatter(
        atlas_root / "entities" / "maggie.md",
        (
            "id: maggie\n"
            "title: Maggie\n"
            "type: entity\n"
            "created: '2026-04-18'\n"
            "modified: '2026-04-18'\n"
        ),
        "# Maggie\n",
    )
    Atlas(root=atlas_root).refresh_index()

    payload = load_graph_payload(atlas_root)
    node_types = {node["id"]: node["type"] for node in payload["nodes"]}

    assert node_types["killian"] == "person"
    assert node_types["maggie"] == "person"
    assert payload["type_counts"]["person"] == 2


def test_graph_payload_surfaces_emotional_topology_on_nodes_and_edges(tmp_path) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    _write_note_with_frontmatter(
        atlas_root / "entities" / "sarah.md",
        (
            "id: sarah\n"
            "title: Sarah\n"
            "type: entity\n"
            "entity_type: person\n"
            "created: '2026-04-18'\n"
            "modified: '2026-04-18'\n"
        ),
        (
            "# Sarah\n\n"
            '<!-- cart:wire target="maps" predicate="relates_to_person" relationship="relates_to_person" emotional_valence="mixed" energy_impact="energizing" avoidance_risk="high" growth_edge="true" current_state="building" valence_note="growth territory" -->\n'
        ),
    )
    _write_note_with_frontmatter(
        atlas_root / "entities" / "maps.md",
        (
            "id: maps\n"
            "title: maps\n"
            "type: entity\n"
            "entity_type: person\n"
            "created: '2026-04-18'\n"
            "modified: '2026-04-18'\n"
        ),
        "# maps\n",
    )
    Atlas(root=atlas_root).refresh_index()

    payload = load_graph_payload(atlas_root)
    sarah = next(node for node in payload["nodes"] if node["id"] == "sarah")
    wire_edge = next(edge for edge in payload["edges"] if edge.get("kind") == "wire")

    assert sarah["emotional_valence"] == "mixed"
    assert sarah["avoidance_risk"] == "high"
    assert sarah["growth_edge"] is True
    assert sarah["current_state"] == "building"
    assert sarah["base_radius"] > 4.8
    assert wire_edge["emotional_valence"] == "mixed"
    assert wire_edge["avoidance_risk"] == "high"
    assert wire_edge["valence_note"] == "growth territory"


def test_graph_payload_embeds_graph_config_defaults(tmp_path) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    _write_note(
        atlas_root / "entities" / "maps.md",
        note_id="maps",
        title="maps",
        note_type="entity",
        body="# maps\n",
    )
    Atlas(root=atlas_root).refresh_index()

    payload = load_graph_payload(atlas_root)
    graph_config = payload["graph_config"]

    assert graph_config["theme_preset"] == "baseline"
    assert graph_config["available_theme_presets"] == ["astral", "baseline"]
    assert graph_config["theme_script_paths"] == []
    assert graph_config["privacy"]["mode"] == "off"
    assert graph_config["privacy"]["person_order"] == ["maps", "maggie", "sarah"]
    assert graph_config["always_visible_people"] == ["maps", "cassette"]


def test_graph_payload_respects_atlas_theme_override(tmp_path) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    config_dir = atlas_root / ".cartographer"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.toml").write_text(
        (
            "[graph]\n"
            'theme_preset = "astral"\n'
        ),
        encoding="utf-8",
    )
    _write_note(
        atlas_root / "entities" / "maps.md",
        note_id="maps",
        title="maps",
        note_type="entity",
        body="# maps\n",
    )
    Atlas(root=atlas_root).refresh_index()

    payload = load_graph_payload(atlas_root)

    assert payload["graph_config"]["theme_preset"] == "astral"


def test_graph_payload_discovers_external_theme_scripts(tmp_path) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    theme_dir = atlas_root / "themes"
    theme_dir.mkdir(parents=True, exist_ok=True)
    (theme_dir / "synaptic-wizard.js").write_text(
        "window.CART_THEMES.register({ id: 'synaptic-wizard', preset: { id: 'synaptic-wizard', title: 'Synaptic Wizard' } });\n",
        encoding="utf-8",
    )
    config_dir = atlas_root / ".cartographer"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.toml").write_text(
        (
            "[graph]\n"
            'theme_preset = "synaptic-wizard"\n'
        ),
        encoding="utf-8",
    )
    _write_note(
        atlas_root / "entities" / "maps.md",
        note_id="maps",
        title="maps",
        note_type="entity",
        body="# maps\n",
    )
    Atlas(root=atlas_root).refresh_index()

    payload = load_graph_payload(atlas_root)
    html = render_graph_html(payload)

    assert payload["graph_config"]["theme_preset"] == "synaptic-wizard"
    assert "synaptic-wizard" in payload["graph_config"]["available_theme_presets"]
    assert payload["graph_config"]["theme_script_paths"] == ["./themes/synaptic-wizard.js"]
    assert '<script src="./themes/synaptic-wizard.js"></script>' in html


def test_graph_payload_assigns_stable_person_aliases_from_config(tmp_path) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    _write_note_with_frontmatter(
        atlas_root / "entities" / "maps.md",
        (
            "id: maps\n"
            "title: maps\n"
            "type: entity\n"
            "entity_type: person\n"
            "created: '2026-04-18'\n"
            "modified: '2026-04-18'\n"
        ),
        "# maps\n",
    )
    _write_note_with_frontmatter(
        atlas_root / "entities" / "maggie.md",
        (
            "id: maggie\n"
            "title: Maggie\n"
            "type: entity\n"
            "entity_type: person\n"
            "created: '2026-04-18'\n"
            "modified: '2026-04-18'\n"
        ),
        "# Maggie\n",
    )
    _write_note_with_frontmatter(
        atlas_root / "entities" / "sarah.md",
        (
            "id: sarah\n"
            "title: Sarah\n"
            "type: entity\n"
            "entity_type: person\n"
            "created: '2026-04-18'\n"
            "modified: '2026-04-18'\n"
        ),
        "# Sarah\n",
    )
    _write_note_with_frontmatter(
        atlas_root / "entities" / "killian.md",
        (
            "id: killian\n"
            "title: Killian\n"
            "type: entity\n"
            "entity_type: person\n"
            "created: '2026-04-18'\n"
            "modified: '2026-04-18'\n"
        ),
        "# Killian\n",
    )
    Atlas(root=atlas_root).refresh_index()

    payload = load_graph_payload(atlas_root)
    aliases = {
        node["id"]: (node["person_order_index"], node["privacy_alias"])
        for node in payload["nodes"]
        if node["type"] == "person"
    }
    graph_config = payload["graph_config"]

    assert aliases["maps"] == (1, "Person 1")
    assert aliases["maggie"] == (2, "Person 2")
    assert aliases["sarah"] == (3, "Person 3")
    assert graph_config["always_visible_people"] == ["maps", "cassette"]
    assert graph_config["privacy"]["mode"] == "off"
    assert graph_config["privacy"]["person_order"] == ["maps", "maggie", "sarah"]
