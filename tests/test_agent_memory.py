from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from cartographer.agent_memory import build_agent_ingest_result
from cartographer.atlas import Atlas
from cartographer.index import Index
from cartographer.notes import Note


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


if __name__ == "__main__":
    unittest.main()
