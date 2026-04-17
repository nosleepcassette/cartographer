from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from cartographer.atlas import Atlas
from cartographer.daily_brief import build_daily_brief
from cartographer.mapsos import ingest_mapsos_exports, ingest_mapsos_intake, normalize_mapsos_tasks, sync_mapsos_payload
from cartographer.patterns import load_state_log, summarize_patterns
from cartographer.tasks import parse_tasks_in_file


class MapsOSBridgeTests(unittest.TestCase):
    def _init_atlas(self, atlas_root: Path) -> None:
        previous_skip = os.environ.get("CARTOGRAPHER_SKIP_VIMWIKI_PATCH")
        os.environ["CARTOGRAPHER_SKIP_VIMWIKI_PATCH"] = "1"
        try:
            Atlas(root=atlas_root).init()
        finally:
            if previous_skip is None:
                os.environ.pop("CARTOGRAPHER_SKIP_VIMWIKI_PATCH", None)
            else:
                os.environ["CARTOGRAPHER_SKIP_VIMWIKI_PATCH"] = previous_skip

    def test_normalize_mapsos_tasks_collects_arc_embedded_tasks(self) -> None:
        payload = {
            "date": "2026-04-16",
            "arcs": [
                {
                    "name": "housing",
                    "tasks": [
                        {"id": "arc-1", "title": "Call landlord", "priority": "high"},
                        "Collect lease paperwork",
                    ],
                },
                {
                    "label": "health",
                    "todo": [
                        {"id": "arc-2", "title": "Stretch", "status": "done", "priority": "low"},
                    ],
                },
            ],
        }

        tasks = normalize_mapsos_tasks(payload)

        self.assertEqual(len(tasks), 3)
        self.assertEqual(tasks[0].arc, "housing")
        self.assertEqual(tasks[0].priority, "P1")
        self.assertEqual(tasks[1].arc, "housing")
        self.assertEqual(tasks[2].arc, "health")
        self.assertTrue(tasks[2].done)

    def test_ingest_writes_daily_tasks_and_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            atlas_root = Path(tempdir) / "atlas"
            self._init_atlas(atlas_root)

            payload = {
                "date": "2026-04-16",
                "state": "grounded",
                "summary": "Solid session with a narrow focus on shipping.",
                "arcs": ["housing", {"label": "voice"}],
                "intentions": ["water", "movement"],
                "tasks": [
                    {
                        "id": "arc-1",
                        "title": "Call landlord",
                        "priority": "high",
                        "arc": "housing",
                        "due": "2026-04-17",
                    },
                    {
                        "id": "arc-2",
                        "title": "Stretch",
                        "status": "done",
                        "priority": "low",
                    },
                ],
            }

            first = sync_mapsos_payload(atlas_root, payload)
            second = sync_mapsos_payload(atlas_root, payload)

            self.assertEqual(first["task_count"], 2)
            self.assertEqual(first["open_task_count"], 1)
            self.assertEqual(len(first["paths"]), 4)
            self.assertEqual(second["task_count"], 2)

            daily_path = atlas_root / "daily" / "2026-04-16.md"
            tasks_path = atlas_root / "tasks" / "mapsos.md"
            snapshot_path = atlas_root / "agents" / "mapsOS" / "2026-04-16.md"
            state_log_path = atlas_root / "agents" / "mapsOS" / "state-log.md"

            self.assertTrue(daily_path.exists())
            self.assertTrue(tasks_path.exists())
            self.assertTrue(snapshot_path.exists())
            self.assertTrue(state_log_path.exists())

            daily_text = daily_path.read_text(encoding="utf-8")
            self.assertEqual(daily_text.count("## mapsOS"), 1)
            self.assertIn("state: grounded", daily_text)
            self.assertIn("Call landlord", daily_text)

            tasks = parse_tasks_in_file(tasks_path)
            self.assertEqual(len(tasks), 2)
            self.assertEqual(tasks[0].priority, "P1")
            self.assertEqual(tasks[0].project, "housing")
            self.assertTrue(any(task.done for task in tasks))

            snapshot_text = snapshot_path.read_text(encoding="utf-8")
            self.assertIn("mapsOS snapshot 2026-04-16", snapshot_text)
            self.assertIn('"state": "grounded"', snapshot_text)

            state_entries = load_state_log(atlas_root)
            self.assertEqual(len(state_entries), 1)
            self.assertEqual(state_entries[0].state, "grounded")
            self.assertIn("housing", state_entries[0].arcs_active)

    def test_ingest_markdown_intake_creates_index_learnings_and_brief_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            atlas_root = Path(tempdir) / "atlas"
            self._init_atlas(atlas_root)

            intake_path = Path(tempdir) / "2026-04-13_full_intake.md"
            intake_path.write_text(
                "# mapsOS Intake — April 13, 2026\n\n"
                "## Chronological Log\n\n"
                "### April 13 (Monday) — Today\n"
                "- **STATE:** stable -> grieving\n"
                "- **BODY:** sleep: deep, energy: low\n"
                "- Phone cuts off tomorrow.\n"
                "- Follow up with Glide.\n\n"
                "## Active Goals\n\n"
                "1. Call therapist list from Friday\n"
                "2. Follow up with Glide\n\n"
                "## Nota Tasks Added\n\n"
                "- [27] call therapist list from Friday @health\n"
                "- [28] follow up with Glide @income\n\n"
                "## Self-Doubt Protocol\n\n"
                "- Never present observations as conclusions\n"
                "- Always name alternative explanations\n\n"
                "## Pattern Watching (for therapist)\n\n"
                "- Sleep patterns preceding elevated periods\n"
                "- Crash duration after spikes\n\n"
                "## People in Orbit\n\n"
                "| Name | Role | Notes |\n"
                "|------|------|-------|\n"
                "| maggie | ex | still close |\n",
                encoding="utf-8",
            )

            result = ingest_mapsos_intake(atlas_root, intake_path)

            self.assertEqual(result["count"], 1)
            self.assertGreaterEqual(result["learning_count"], 4)
            self.assertTrue((atlas_root / "agents" / "mapsOS" / "intake-index.md").exists())
            self.assertTrue((atlas_root / "agents" / "mapsOS" / "learnings" / "self-doubt-protocol.md").exists())
            self.assertTrue((atlas_root / "agents" / "mapsOS" / "learnings" / "pattern-watching.md").exists())

            state_entries = load_state_log(atlas_root)
            self.assertEqual(len(state_entries), 1)
            self.assertEqual(state_entries[0].sleep, "deep")
            self.assertIn("health", state_entries[0].arcs_active)
            self.assertIn("income", state_entries[0].arcs_active)

            patterns_output = summarize_patterns(state_entries)
            self.assertIn("state log: 1 sessions", patterns_output)

            brief = build_daily_brief(atlas_root)
            self.assertIn("atlas brief", brief)
            self.assertIn("call therapist list from Friday", brief)
            self.assertIn("stable -> grieving", brief)

    def test_ingest_exports_aggregates_latest_json_exports(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            atlas_root = Path(tempdir) / "atlas"
            exports_dir = Path(tempdir) / "exports"
            exports_dir.mkdir(parents=True)
            self._init_atlas(atlas_root)

            first_export = exports_dir / "session_20260417_101500.json"
            second_export = exports_dir / "session_20260417_111500.json"
            first_export.write_text(
                '{"date":"2026-04-17","state":"stable","body":{"sleep":"ok"},"tasks":[{"title":"ship phase 3","priority":"high"}]}',
                encoding="utf-8",
            )
            second_export.write_text(
                '{"date":"2026-04-18","state":"depleted","body":{"sleep":"none"},"arcs":["income"],"tasks":[{"title":"send invoice","priority":"urgent"}]}',
                encoding="utf-8",
            )

            result = ingest_mapsos_exports(atlas_root, [first_export, second_export])

            self.assertEqual(result["count"], 2)
            self.assertEqual(result["task_count"], 2)
            state_entries = load_state_log(atlas_root)
            self.assertEqual(len(state_entries), 2)
            self.assertEqual(state_entries[-1].state, "depleted")
            self.assertIn("income", state_entries[-1].arcs_active)


if __name__ == "__main__":
    unittest.main()
