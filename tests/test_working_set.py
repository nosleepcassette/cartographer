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


def test_working_set_add_and_list_json(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)

    runner = CliRunner()
    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))

    add_result = runner.invoke(
        main,
        [
            "working-set",
            "add",
            "RSD counter-evidence candidate",
            "--role",
            "intake",
            "--scope",
            "therapy",
            "--body",
            "Need to verify recent Maggie evidence",
            "--provenance",
            "entities/maggie.md",
            "--verification-needed",
            "--json",
        ],
    )

    assert add_result.exit_code == 0
    add_payload = json.loads(add_result.output)
    assert add_payload["schema_version"] == "2026-04-17"
    assert add_payload["surface"] == "working-set.add"
    assert add_payload["entry"]["role"] == "intake"
    assert add_payload["entry"]["scope"] == "therapy"
    assert add_payload["entry"]["verification_needed"] is True

    list_result = runner.invoke(
        main,
        ["working-set", "list", "--role", "intake", "--scope", "therapy", "--json"],
    )

    assert list_result.exit_code == 0
    list_payload = json.loads(list_result.output)
    assert list_payload["schema_version"] == "2026-04-17"
    assert list_payload["surface"] == "working-set.list"
    assert list_payload["count"] == 1
    assert list_payload["entries"][0]["title"] == "RSD counter-evidence candidate"


def test_working_set_gc_and_doctor_surface_expired_entries(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)

    add_working_set_entry(
        atlas_root,
        title="expired note",
        role="librarian",
        scope="ops",
        ttl_hours=-1,
    )

    runner = CliRunner()
    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))

    doctor_result = runner.invoke(main, ["doctor", "--json"])

    assert doctor_result.exit_code == 0
    doctor_payload = json.loads(doctor_result.output)
    assert doctor_payload["working_set"]["count"] == 1
    assert doctor_payload["working_set"]["expired_count"] == 1
    assert any("working set has 1 expired entries" in warning for warning in doctor_payload["warnings"])

    gc_result = runner.invoke(main, ["working-set", "gc", "--json"])

    assert gc_result.exit_code == 0
    gc_payload = json.loads(gc_result.output)
    assert gc_payload["schema_version"] == "2026-04-17"
    assert gc_payload["surface"] == "working-set.gc"
    assert gc_payload["removed_count"] == 1
