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


def _write_fake_therapy_plugin(plugin_dir: Path) -> None:
    scripts_dir = plugin_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "SKILL.md").write_text("# therapy plugin\n", encoding="utf-8")
    (plugin_dir / "patterns.yaml").write_text(
        "patterns:\n  RSD-spiral:\n    evidence_query: test\n",
        encoding="utf-8",
    )
    (plugin_dir / "interventions.yaml").write_text(
        (
            "RSD-spiral:\n"
            "  interventions:\n"
            "    - name: counter-evidence-query\n"
            "      type: evidence-based\n"
            "      description: Pull facts that contradict the spiral narrative\n"
        ),
        encoding="utf-8",
    )
    (scripts_dir / "pattern-detect.py").write_text(
        (
            "import json, sys\n"
            "payload = json.load(sys.stdin)\n"
            "content = payload.get('content', '')\n"
            "patterns = []\n"
            "if \"didn't respond\" in content.lower():\n"
            "    patterns.append({\n"
            "        'pattern': 'RSD-spiral',\n"
            "        'keyword_found': \"didn't respond\",\n"
            "        'counter_query': \"What's their actual response pattern?\",\n"
            "    })\n"
            "json.dump({'patterns': patterns}, sys.stdout)\n"
        ),
        encoding="utf-8",
    )
    (scripts_dir / "counter-evidence.py").write_text(
        (
            "import json, sys\n"
            "payload = json.load(sys.stdin)\n"
            "claim = payload.get('claim', '')\n"
            "json.dump({\n"
            "  'pattern_detected': 'RSD-spiral',\n"
            "  'original_claim': claim,\n"
            "  'counter_queries': [\n"
            "    \"What's their actual response pattern?\",\n"
            "    \"What did they actually say?\",\n"
            "  ],\n"
            "}, sys.stdout)\n"
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


def test_therapy_review_json_payload_uses_plugin_mvp(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    plugin_dir = tmp_path / "therapy-plugin"
    _init_atlas(atlas_root)
    _write_fake_therapy_plugin(plugin_dir)

    add_working_set_entry(
        atlas_root,
        title="Maggie spiral",
        role="intake",
        scope="therapy",
        body="She didn't respond and I wasn't giving them what they needed.",
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
    monkeypatch.setenv("CART_THERAPY_PLUGIN_DIR", str(plugin_dir))

    result = runner.invoke(main, ["therapy", "review", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["surface"] == "therapy.review"
    assert payload["plugin"]["available"] is True
    assert payload["pattern_count"] == 1
    assert payload["patterns"][0]["pattern"] == "RSD-spiral"
    assert payload["patterns"][0]["counter_evidence"]["pattern_detected"] == "RSD-spiral"
    assert payload["patterns"][0]["matches"][0]["label"] == "Maggie spiral"


def test_therapy_counter_evidence_json_payload(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    plugin_dir = tmp_path / "therapy-plugin"
    _init_atlas(atlas_root)
    _write_fake_therapy_plugin(plugin_dir)

    runner = CliRunner()
    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))
    monkeypatch.setenv("CART_THERAPY_PLUGIN_DIR", str(plugin_dir))

    result = runner.invoke(
        main,
        ["therapy", "counter-evidence", "they", "didn't", "respond", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["surface"] == "therapy.counter-evidence"
    assert payload["pattern_detected"] == "RSD-spiral"
    assert "What's their actual response pattern?" in payload["counter_queries"]
