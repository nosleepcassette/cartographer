from __future__ import annotations

import json
import os
import time
from pathlib import Path

import yaml
from click.testing import CliRunner

from cartographer.atlas import Atlas
from cartographer.cli import main
from cartographer.daily_brief import build_daily_brief
from cartographer.index import Index
from cartographer.mapsos import ingest_mapsos_exports
from cartographer.notes import Note
from cartographer.operating_truth import list_operating_truth


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


def test_operating_truth_daily_brief_and_mapsos_extraction(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))
    runner = CliRunner()

    assert runner.invoke(
        main, ["operating-truth", "set", "active_work", "shipping v0.3"]
    ).exit_code == 0
    assert runner.invoke(
        main, ["operating-truth", "add", "open_decision", "fastembed or something else"]
    ).exit_code == 0
    assert runner.invoke(
        main, ["operating-truth", "add", "commitment", "ship by May 15"]
    ).exit_code == 0
    assert runner.invoke(
        main, ["operating-truth", "add", "next_step", "write the spec"]
    ).exit_code == 0

    list_result = runner.invoke(main, ["operating-truth", "--json"])
    assert list_result.exit_code == 0
    payload = json.loads(list_result.output)
    assert {item["type"] for item in payload["entries"]} >= {
        "active_work",
        "open_decision",
        "current_commitment",
        "next_step",
    }

    brief = build_daily_brief(atlas_root)
    assert "## operating truth" in brief
    assert "active: shipping v0.3" in brief
    assert "commitments: ship by May 15" in brief

    export_path = tmp_path / "mapsos-export.json"
    export_path.write_text(
        json.dumps(
            {
                "date": "2026-04-21",
                "goals": ["ship v0.3"],
                "intentions": ["write tests"],
                "vent": "should I use fastembed or sentence-transformers?",
            }
        ),
        encoding="utf-8",
    )
    ingest_mapsos_exports(atlas_root, [export_path])
    truth_items = list_operating_truth(atlas_root)
    assert any(item["type"] == "current_commitment" and item["content"] == "ship v0.3" for item in truth_items)
    assert any(item["type"] == "next_step" and item["content"] == "write tests" for item in truth_items)
    assert any(item["type"] == "open_decision" and "fastembed" in item["content"] for item in truth_items)


def test_temporal_truth_supersede_history_conflicts_and_stale(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    _write_note(
        atlas_root / "entities" / "sarah-old.md",
        {
            "id": "sarah-old",
            "title": "Sarah",
            "type": "entity",
            "status": "inactive",
            "created": "2026-02-01",
            "modified": "2026-02-01",
            "is_current": True,
        },
        "# Sarah old\n",
    )
    _write_note(
        atlas_root / "entities" / "sarah-new.md",
        {
            "id": "sarah-new",
            "title": "Sarah",
            "type": "entity",
            "status": "active",
            "created": "2026-04-01",
            "modified": "2026-04-01",
            "is_current": True,
        },
        "# Sarah new\n",
    )
    old_epoch = time.time() - (90 * 86400)
    os.utime(atlas_root / "entities" / "sarah-old.md", (old_epoch, old_epoch))
    _write_note(
        atlas_root / "entities" / "legacy.md",
        {
            "id": "legacy",
            "title": "Legacy Fact",
            "type": "entity",
            "status": "active",
            "created": "2025-12-01",
            "modified": "2025-12-01",
            "is_current": True,
        },
        "# Legacy\n",
    )
    os.utime(atlas_root / "entities" / "legacy.md", (old_epoch, old_epoch))
    Atlas(root=atlas_root).refresh_index()

    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))
    runner = CliRunner()
    result = runner.invoke(main, ["supersede", "sarah-old", "sarah-new"])
    assert result.exit_code == 0

    history_result = runner.invoke(main, ["history", "sarah-old", "--json"])
    assert history_result.exit_code == 0
    history_payload = json.loads(history_result.output)
    assert [item["id"] for item in history_payload["history"]] == ["sarah-old", "sarah-new"]
    assert history_payload["history"][0]["is_current"] is False
    assert history_payload["history"][1]["is_current"] is True

    conflict_note = atlas_root / "entities" / "sarah-conflict.md"
    _write_note(
        conflict_note,
        {
            "id": "sarah-conflict",
            "title": "Sarah",
            "type": "entity",
            "status": "blocked",
            "created": "2026-04-10",
            "modified": "2026-04-10",
            "is_current": True,
        },
        "# Sarah conflicting\n",
    )
    Atlas(root=atlas_root).refresh_index()

    conflicts_result = runner.invoke(main, ["conflicts", "--json"])
    assert conflicts_result.exit_code == 0
    conflicts_payload = json.loads(conflicts_result.output)
    assert any(item["type"] == "status_conflict" for item in conflicts_payload["conflicts"])

    stale_result = runner.invoke(main, ["stale", "--days", "60", "--json"])
    assert stale_result.exit_code == 0
    stale_payload = json.loads(stale_result.output)
    assert any(item["id"] == "legacy" for item in stale_payload["notes"])


def test_query_route_delete_archive_and_guardrails(tmp_path, monkeypatch) -> None:
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
        "# Alpha\n",
    )
    _write_note(
        atlas_root / "projects" / "beta.md",
        {
            "id": "beta",
            "title": "Beta",
            "type": "project",
            "created": "2026-04-21",
            "modified": "2026-04-21",
            "links": ["alpha"],
        },
        "# Beta\n\n[[alpha]]\n",
    )
    Atlas(root=atlas_root).refresh_index()

    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))
    runner = CliRunner()
    assert runner.invoke(
        main, ["operating-truth", "set", "active_work", "building routed queries"]
    ).exit_code == 0

    routed = runner.invoke(main, ["query", "what am I working on", "--route", "--json"])
    assert routed.exit_code == 0
    routed_payload = json.loads(routed.output)
    assert "operating-truth" in routed_payload["routes"]
    assert any(item["shelf"] == "operating-truth" for item in routed_payload["results"])

    preview = runner.invoke(main, ["delete", "alpha", "--json"])
    assert preview.exit_code == 0
    preview_payload = json.loads(preview.output)
    assert preview_payload["surface"] == "delete.preview"
    assert preview_payload["impact"]["frontmatter_links"] >= 1

    deleted = runner.invoke(main, ["delete", "alpha", "--archive", "--force", "--json"])
    assert deleted.exit_code == 0
    delete_payload = json.loads(deleted.output)
    assert delete_payload["archived"] is True
    assert not (atlas_root / "projects" / "alpha.md").exists()
    assert (atlas_root / ".cartographer" / "archive").exists()

    beta_note = Note.from_file(atlas_root / "projects" / "beta.md")
    assert beta_note.frontmatter["links"] == []

    rejected = runner.invoke(
        main,
        ["new", "entity", "secret-test", "--from-stdin"],
        input="api_key=sk-1234567890abcdefghijklmnop\n",
    )
    assert rejected.exit_code != 0
    assert "rejected by guardrails" in rejected.output.lower()
    assert not (atlas_root / "entities" / "secret-test.md").exists()
