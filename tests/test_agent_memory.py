from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from cartographer.agent_memory import (
    append_learning,
    build_agent_ingest_result,
    confirm_learnings,
    pending_learning_blocks,
    reject_learnings,
)
from cartographer.atlas import Atlas
from cartographer.index import Index
from cartographer.notes import Note
from cartographer.plugins import apply_writes


class AgentMemorySummaryTests(unittest.TestCase):
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

    def test_init_creates_master_summary_with_canonical_id(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            atlas_root = Path(tempdir) / "atlas"
            self._init_atlas(atlas_root)

            master_path = atlas_root / "agents" / "MASTER_SUMMARY.md"
            self.assertTrue(master_path.exists())

            master_note = Note.from_file(master_path)
            self.assertEqual(master_note.frontmatter.get("id"), "master-summary")
            self.assertEqual(master_note.frontmatter.get("type"), "master-summary")

            index = Index(atlas_root)
            index.rebuild()
            self.assertEqual(index.find_note_path("master-summary"), master_path)
            self.assertIn(str(master_path), index.query("type:master-summary"))

    def test_agent_ingest_updates_master_summary_and_indexes_unique_summary_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            atlas_root = Path(tempdir) / "atlas"
            self._init_atlas(atlas_root)

            master_path = atlas_root / "agents" / "MASTER_SUMMARY.md"
            master_path.write_text(
                "---\n"
                "type: master-summary\n"
                "updated: 2026-04-16\n"
                "version: 3\n"
                "contributing_agents: [hermes]\n"
                "---\n\n"
                "# maps — master context\n\n"
                "## current situation\n\n"
                "Existing context.\n",
                encoding="utf-8",
            )

            result = build_agent_ingest_result(
                atlas_root,
                "hermes",
                "session.json",
                {
                    "summary": "Shipped the bridge and fixed summary parsing.",
                    "learnings": ["Keep summary ids stable."],
                },
            )

            for write in result["writes"]:
                path = atlas_root / str(write["path"])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(str(write["content"]), encoding="utf-8")

            index = Index(atlas_root)
            index.rebuild()

            hermes_summary_path = atlas_root / "agents" / "hermes" / "SUMMARY.md"
            self.assertEqual(index.find_note_path("hermes-summary"), hermes_summary_path)
            self.assertEqual(index.find_note_path("master-summary"), master_path)

            master_note = Note.from_file(master_path)
            self.assertEqual(master_note.frontmatter.get("id"), "master-summary")
            self.assertIn("hermes", master_note.frontmatter.get("contributing_agents", []))
            self.assertIn("hermes-summary", master_note.frontmatter.get("links", []))

            hermes_note = Note.from_file(hermes_summary_path)
            self.assertEqual(hermes_note.frontmatter.get("id"), "hermes-summary")
            self.assertEqual(hermes_note.frontmatter.get("type"), "agent-summary")

    def test_learning_provenance_and_confirm_reject_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            atlas_root = Path(tempdir) / "atlas"
            self._init_atlas(atlas_root)

            result = append_learning(
                atlas_root,
                agent="hermes",
                topic="mapsos-patterns",
                text="Sleep disruption precedes depleted states.",
                confidence=0.72,
                source="mapsos-intake",
                source_session="session_20260416_214759",
                source_agent="hermes",
                learned_on="2026-04-16",
            )
            apply_writes(atlas_root, result["writes"], plugin_name="learn")

            pending = pending_learning_blocks(atlas_root)
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0].attrs.get("source_session"), "session_20260416_214759")
            self.assertEqual(pending[0].attrs.get("source_agent"), "hermes")

            confirmed = confirm_learnings(atlas_root, topic="mapsos-patterns")
            apply_writes(atlas_root, confirmed["writes"], plugin_name="learn-confirm")

            pending_after_confirm = pending_learning_blocks(atlas_root)
            self.assertEqual(len(pending_after_confirm), 0)

            learning_text = (atlas_root / "agents" / "hermes" / "learnings" / "mapsos-patterns.md").read_text(encoding="utf-8")
            self.assertIn('confirmed="1"', learning_text)
            self.assertIn('confidence="1.00"', learning_text)
            self.assertIn('confidence_label="confirmed"', learning_text)

            second = append_learning(
                atlas_root,
                agent="hermes",
                topic="mapsos-patterns",
                text="Invoice pressure is clustering with depleted states.",
                confidence=0.60,
                source="mapsos-intake",
                source_session="session_20260417_090000",
                source_agent="hermes",
                learned_on="2026-04-17",
            )
            apply_writes(atlas_root, second["writes"], plugin_name="learn")
            pending = pending_learning_blocks(atlas_root)
            self.assertEqual(len(pending), 1)

            rejected = reject_learnings(atlas_root, block_id=pending[0].block_id)
            apply_writes(atlas_root, rejected["writes"], plugin_name="learn-reject")

            rejected_text = (atlas_root / "agents" / "hermes" / "learnings" / "mapsos-patterns.md").read_text(encoding="utf-8")
            self.assertIn('rejected="1"', rejected_text)
            self.assertIn('confidence_label="rejected"', rejected_text)


if __name__ == "__main__":
    unittest.main()
