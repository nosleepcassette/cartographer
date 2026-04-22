from __future__ import annotations

import json
import os
from pathlib import Path

import yaml
from click.testing import CliRunner

from cartographer.atlas import Atlas
from cartographer.cli import main
from cartographer.temporal_patterns import (
    CorrelationResult,
    PatternReport,
    TemporalPatternDetector,
    pearson_correlation,
)
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


def _write_fake_therapy_plugin(plugin_dir: Path) -> None:
    scripts_dir = plugin_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "SKILL.md").write_text("# therapy plugin\n", encoding="utf-8")
    (plugin_dir / "patterns.yaml").write_text("patterns: {}\n", encoding="utf-8")
    (plugin_dir / "interventions.yaml").write_text("{}\n", encoding="utf-8")
    (scripts_dir / "pattern-detect.py").write_text(
        "import json, sys\njson.dump({'patterns': []}, sys.stdout)\n",
        encoding="utf-8",
    )
    (scripts_dir / "counter-evidence.py").write_text(
        "import json, sys\njson.dump({'counter_queries': []}, sys.stdout)\n",
        encoding="utf-8",
    )


def _sample_pattern() -> PatternReport:
    correlation = CorrelationResult(
        signal_a="state_transition",
        signal_b="wire_activity",
        lead_hours=24,
        correlation=0.82,
        n_buckets=6,
        p_value=0.01,
        significant=True,
        description="Wire activity in the 24h before state transitions",
        buckets=[],
    )
    return PatternReport(
        title="Wire activity in the 24h before state transitions",
        correlations=[correlation],
        summary="Wire activity in the 24h before state transitions (r=0.82, p=0.010, N=6)",
        counter_evidence=["2026-04-20: wire activity rose without a state shift"],
        recommendation="This is a pattern report, not an intervention.",
    )


def test_pearson_correlation_has_expected_extremes() -> None:
    assert pearson_correlation([1.0, 2.0, 3.0], [2.0, 4.0, 6.0]) == 1.0
    assert pearson_correlation([1.0, 2.0, 3.0], [6.0, 4.0, 2.0]) == -1.0


def test_temporal_patterns_cli_records_accesses_and_emits_summary(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    _write_note(
        atlas_root / "projects" / "alpha.md",
        {
            "id": "alpha",
            "title": "Alpha",
            "type": "project",
            "created": "2026-04-18",
            "modified": "2026-04-21",
        },
        "# Alpha\n",
    )
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
            '<!-- cart:wire target="alpha" predicate="supports" emotional_valence="positive" since="2026-04-19" -->\n'
        ),
    )
    _write_note(
        atlas_root / "agents" / "mapsOS" / "2026-04-18.md",
        {
            "id": "mapsos-2026-04-18",
            "title": "mapsOS 2026-04-18",
            "type": "mapsos-snapshot",
            "created": "2026-04-18",
            "modified": "2026-04-18",
            "state": "stable",
        },
        "- state: stable\n",
    )
    _write_note(
        atlas_root / "agents" / "mapsOS" / "2026-04-19.md",
        {
            "id": "mapsos-2026-04-19",
            "title": "mapsOS 2026-04-19",
            "type": "mapsos-snapshot",
            "created": "2026-04-19",
            "modified": "2026-04-19",
            "state": "depleted",
        },
        "- state: depleted\n",
    )
    _write_note(
        atlas_root / "daily" / "daily-2026-04-19.md",
        {
            "id": "daily-2026-04-19",
            "title": "Daily 2026-04-19",
            "type": "daily",
            "created": "2026-04-19",
            "modified": "2026-04-19",
        },
        "- [ ] follow up\n- [x] ship tests\nlonely but hopeful\n",
    )
    _write_note(
        atlas_root / "agents" / "hermes" / "sessions" / "session-20260419-010101-test.md",
        {
            "id": "hermes-session-1",
            "title": "Hermes Session",
            "type": "agent-log",
            "agent": "hermes",
            "date": "2026-04-19",
            "created": "2026-04-19",
            "modified": "2026-04-19",
        },
        "# Session\n",
    )
    Atlas(root=atlas_root).refresh_index()

    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))
    runner = CliRunner()

    query_result = runner.invoke(main, ["query", "Alpha", "--json"])
    assert query_result.exit_code == 0

    detector = TemporalPatternDetector(atlas_root)
    access_events = detector.load_access_patterns()
    assert access_events
    assert access_events[0].note_id == "alpha"

    result = runner.invoke(main, ["temporal-patterns", "--json", "--min-n", "1", "--lead", "24"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["surface"] == "temporal-patterns"
    assert payload["summary"]["enabled"] is True
    assert payload["summary"]["state_transitions"] >= 1
    assert payload["summary"]["wire_events"] >= 1


def test_daily_brief_temporal_flag_includes_section(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))
    monkeypatch.setattr(
        "cartographer.temporal_patterns.TemporalPatternDetector.detect_all_patterns",
        lambda self, **kwargs: [_sample_pattern()],
    )

    runner = CliRunner()
    result = runner.invoke(main, ["daily-brief", "--temporal"])

    assert result.exit_code == 0
    assert "## temporal patterns" in result.output
    assert "Wire activity in the 24h before state transitions" in result.output


def test_therapy_review_temporal_flag_adds_pattern_payload(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    plugin_dir = tmp_path / "therapy-plugin"
    _init_atlas(atlas_root)
    _write_fake_therapy_plugin(plugin_dir)
    add_working_set_entry(
        atlas_root,
        title="Therapy working set",
        role="intake",
        scope="therapy",
        body="Need context on the last state shift.",
    )
    Atlas(root=atlas_root).refresh_index()

    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))
    monkeypatch.setenv("CART_THERAPY_PLUGIN_DIR", str(plugin_dir))
    monkeypatch.setattr(
        "cartographer.temporal_patterns.TemporalPatternDetector.detect_all_patterns",
        lambda self, **kwargs: [_sample_pattern()],
    )

    runner = CliRunner()
    result = runner.invoke(main, ["therapy", "review", "--json", "--temporal"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["surface"] == "therapy.review"
    assert payload["temporal_patterns"]["pattern_count"] == 1
    assert payload["temporal_patterns"]["patterns"][0]["title"] == _sample_pattern().title
    assert "TEMPORAL PATTERN" in payload["context"]["content"]


def test_plugin_list_includes_manifest_backed_plugins(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))

    runner = CliRunner()
    result = runner.invoke(main, ["plugin", "list"])

    assert result.exit_code == 0
    names = set(result.output.splitlines())
    assert {"therapy", "lovelife", "avoidance", "temporal-patterns"} <= names
