from __future__ import annotations

import json
import os
from pathlib import Path

import yaml
from click.testing import CliRunner

from cartographer.atlas import Atlas
from cartographer.cli import main
from cartographer.index import Index


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


def _write_note(path: Path, frontmatter: dict[str, object], body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        + yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=False).strip()
        + "\n---\n\n"
        + body
        + ("" if body.endswith("\n") else "\n"),
        encoding="utf-8",
    )


def test_think_command_returns_ranked_activation_json(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    _write_note(
        atlas_root / "projects" / "alpha.md",
        {
            "id": "alpha",
            "title": "Alpha",
            "type": "project",
            "created": "2026-04-21",
            "modified": "2026-04-21",
        },
        (
            "# Alpha\n\n"
            '<!-- cart:wire target="beta" predicate="supports" emotional_valence="positive" -->\n'
        ),
    )
    _write_note(
        atlas_root / "projects" / "beta.md",
        {
            "id": "beta",
            "title": "Beta",
            "type": "project",
            "created": "2026-04-21",
            "modified": "2026-04-21",
        },
        (
            "# Beta\n\n"
            '<!-- cart:wire target="gamma" predicate="supports" emotional_valence="negative" -->\n'
        ),
    )
    _write_note(
        atlas_root / "projects" / "gamma.md",
        {
            "id": "gamma",
            "title": "Gamma",
            "type": "project",
            "created": "2026-04-21",
            "modified": "2026-04-21",
        },
        "# Gamma\n",
    )
    Atlas(root=atlas_root).refresh_index()

    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))
    runner = CliRunner()
    result = runner.invoke(main, ["think", "alpha", "--depth", "2", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["surface"] == "think"
    assert payload["results"][0]["note_id"] == "beta"
    assert payload["results"][1]["note_id"] == "gamma"
    assert payload["results"][0]["activation"] > payload["results"][1]["activation"]


def test_walk_command_filters_by_avoidance_and_growth_edges(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    _write_note(
        atlas_root / "entities" / "alpha.md",
        {
            "id": "alpha",
            "title": "Alpha",
            "type": "entity",
            "created": "2026-04-21",
            "modified": "2026-04-21",
        },
        (
            "# Alpha\n\n"
            '<!-- cart:wire target="beta" predicate="relates_to" avoidance_risk="high" growth_edge="true" -->\n'
        ),
    )
    _write_note(
        atlas_root / "entities" / "beta.md",
        {
            "id": "beta",
            "title": "Beta",
            "type": "entity",
            "created": "2026-04-21",
            "modified": "2026-04-21",
        },
        (
            "# Beta\n\n"
            '<!-- cart:wire target="gamma" predicate="relates_to" avoidance_risk="low" -->\n'
        ),
    )
    _write_note(
        atlas_root / "entities" / "gamma.md",
        {
            "id": "gamma",
            "title": "Gamma",
            "type": "entity",
            "created": "2026-04-21",
            "modified": "2026-04-21",
        },
        "# Gamma\n",
    )
    Atlas(root=atlas_root).refresh_index()

    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["walk", "alpha", "--depth", "2", "--avoidance-only", "medium", "--growth-edges", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    traversals = payload["traversals"]
    assert any(item["to_note"] == "beta" for item in traversals)
    assert all(item["to_note"] != "gamma" for item in traversals)
    assert all(item["avoidance_risk"] == "high" for item in traversals)
    assert all(item["growth_edge"] is True for item in traversals)


def test_discover_command_proposes_and_accepts_bridges(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    _write_note(
        atlas_root / "projects" / "alpha.md",
        {
            "id": "alpha",
            "title": "Alpha",
            "type": "project",
            "tags": ["bridge", "memory"],
            "links": ["maps"],
            "created": "2026-04-21",
            "modified": "2026-04-21",
        },
        "# Alpha\n\nA bridge memory map for support patterns.\n",
    )
    _write_note(
        atlas_root / "projects" / "beta.md",
        {
            "id": "beta",
            "title": "Beta",
            "type": "project",
            "tags": ["bridge", "memory"],
            "links": ["maps"],
            "created": "2026-04-21",
            "modified": "2026-04-21",
        },
        "# Beta\n\nA support memory bridge for pattern discovery.\n",
    )
    Atlas(root=atlas_root).refresh_index()

    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))
    runner = CliRunner()
    result = runner.invoke(main, ["discover", "--threshold", "0.4", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["surface"] == "discover"
    matching = [
        proposal
        for proposal in payload["proposals"]
        if {proposal["left_id"], proposal["right_id"]} == {"alpha", "beta"}
    ]
    assert matching

    wire_count_before = Index(atlas_root).status()["wires"]

    accept_result = runner.invoke(main, ["discover", "--threshold", "0.4", "--accept"])
    assert accept_result.exit_code == 0

    alpha_text = (atlas_root / "projects" / "alpha.md").read_text(encoding="utf-8")
    assert 'predicate="relates_to"' in alpha_text
    assert 'bidirectional="true"' in alpha_text
    assert Index(atlas_root).status()["wires"] >= wire_count_before + 1
