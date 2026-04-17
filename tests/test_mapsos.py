from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from cartographer.atlas import Atlas
from cartographer.mapsos import normalize_mapsos_tasks, sync_mapsos_payload
from cartographer.tasks import parse_tasks_in_file


class MapsOSBridgeTests(unittest.TestCase):
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
            previous_skip = os.environ.get("CARTOGRAPHER_SKIP_VIMWIKI_PATCH")
            os.environ["CARTOGRAPHER_SKIP_VIMWIKI_PATCH"] = "1"
            try:
                Atlas(root=atlas_root).init()
            finally:
                if previous_skip is None:
                    os.environ.pop("CARTOGRAPHER_SKIP_VIMWIKI_PATCH", None)
                else:
                    os.environ["CARTOGRAPHER_SKIP_VIMWIKI_PATCH"] = previous_skip

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
            self.assertEqual(len(first["paths"]), 3)
            self.assertEqual(second["task_count"], 2)

            daily_path = atlas_root / "daily" / "2026-04-16.md"
            tasks_path = atlas_root / "tasks" / "mapsos.md"
            snapshot_path = atlas_root / "agents" / "mapsOS" / "2026-04-16.md"

            self.assertTrue(daily_path.exists())
            self.assertTrue(tasks_path.exists())
            self.assertTrue(snapshot_path.exists())

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


if __name__ == "__main__":
    unittest.main()
