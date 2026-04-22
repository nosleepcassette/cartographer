from __future__ import annotations

import json
import os
from pathlib import Path

import yaml
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


class FakeBackend:
    def __init__(self, model_name: str = "fake-model") -> None:
        self.model_name = model_name

    def _vector_for(self, text: str) -> list[float]:
        lowered = text.lower()
        if "alpha" in lowered:
            return [1.0, 0.0]
        if "beta" in lowered:
            return [0.0, 1.0]
        return [0.5, 0.5]

    def embed(self, text: str) -> list[float]:
        return self._vector_for(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._vector_for(text) for text in texts]


def test_embed_command_and_query_use_semantic_rankings(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    _write_note(
        atlas_root / "notes" / "alpha.md",
        {
            "id": "alpha",
            "title": "Alpha",
            "type": "note",
            "created": "2026-04-21",
            "modified": "2026-04-21",
        },
        "# Alpha\n\nalpha memory resonance\n",
    )
    _write_note(
        atlas_root / "notes" / "beta.md",
        {
            "id": "beta",
            "title": "Beta",
            "type": "note",
            "created": "2026-04-21",
            "modified": "2026-04-21",
        },
        "# Beta\n\nbeta archive drift\n",
    )
    Atlas(root=atlas_root).refresh_index()

    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))
    monkeypatch.setattr("cartographer.embed.is_fastembed_available", lambda: True)
    monkeypatch.setattr(
        "cartographer.embed.configured_backend",
        lambda atlas_root_arg, model_name=None: FakeBackend(model_name or "fake-model"),
    )

    runner = CliRunner()
    embed_result = runner.invoke(main, ["embed"])
    assert embed_result.exit_code == 0
    assert "embeddings updated:" in embed_result.output

    query_result = runner.invoke(main, ["query", "alpha resonance", "--json"])
    assert query_result.exit_code == 0
    payload = json.loads(query_result.output)
    assert payload["surface"] == "query"
    assert payload["results"][0].endswith("/alpha.md")


def test_refresh_index_auto_embeds_when_enabled(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    _write_note(
        atlas_root / "notes" / "alpha.md",
        {
            "id": "alpha",
            "title": "Alpha",
            "type": "note",
            "created": "2026-04-21",
            "modified": "2026-04-21",
        },
        "# Alpha\n",
    )

    calls: list[Path] = []
    monkeypatch.setenv("CARTOGRAPHER_SKIP_AUTO_EMBED", "0")
    monkeypatch.setattr("cartographer.embed.embed_all_notes", lambda root: calls.append(Path(root)) or 1)

    atlas = Atlas(root=atlas_root)
    atlas.refresh_index()

    assert calls == [atlas_root]


def test_stats_command_reports_health_and_connectivity(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    _write_note(
        atlas_root / "entities" / "maps.md",
        {
            "id": "maps",
            "title": "maps",
            "type": "entity",
            "created": "2026-04-18",
            "modified": "2026-04-21",
        },
        (
            "# maps\n\n"
            '<!-- cart:wire target="alpha" predicate="supports" emotional_valence="positive" avoidance_risk="high" growth_edge="true" since="2026-04-20" -->\n'
        ),
    )
    _write_note(
        atlas_root / "projects" / "alpha.md",
        {
            "id": "alpha",
            "title": "Alpha",
            "type": "project",
            "created": "2026-04-21",
            "modified": "2026-04-21",
        },
        "# Alpha\n",
    )
    Atlas(root=atlas_root).refresh_index()

    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))
    runner = CliRunner()
    result = runner.invoke(main, ["stats", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["surface"] == "stats"
    assert payload["summary"]["total_notes"] >= 2
    assert payload["summary"]["total_wires"] == 1
    assert payload["connectivity"]["most_connected"][0]["note_id"] in {"maps", "alpha"}
    assert payload["emotional_topology"]["high_avoidance_risk_count"] == 1
    assert payload["temporal_patterns"]["enabled"] is True
    assert "note" in payload["temporal_patterns"]
