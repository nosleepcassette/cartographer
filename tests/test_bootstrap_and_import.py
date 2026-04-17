from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from cartographer.atlas import Atlas
from cartographer.index import Index
from cartographer.notes import Note
from cartographer.session_import import clean_entity_imports
from cartographer.session_import import import_sessions


class BootstrapAndImportTests(unittest.TestCase):
    def _init_atlas(self, atlas_root: Path) -> dict[str, object]:
        previous_skip = os.environ.get("CARTOGRAPHER_SKIP_VIMWIKI_PATCH")
        os.environ["CARTOGRAPHER_SKIP_VIMWIKI_PATCH"] = "1"
        try:
            return Atlas(root=atlas_root).init()
        finally:
            if previous_skip is None:
                os.environ.pop("CARTOGRAPHER_SKIP_VIMWIKI_PATCH", None)
            else:
                os.environ["CARTOGRAPHER_SKIP_VIMWIKI_PATCH"] = previous_skip

    def test_init_bootstraps_obsidian_and_vimwiki_indexes(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            atlas_root = Path(tempdir) / "atlas"

            result = self._init_atlas(atlas_root)

            self.assertEqual(result["obsidian"], "bootstrapped")
            self.assertEqual(result["vimwiki"], "skipped by env")
            self.assertTrue((atlas_root / ".obsidian" / "app.json").exists())
            self.assertTrue((atlas_root / ".obsidian" / "daily-notes.json").exists())
            self.assertTrue((atlas_root / "daily" / "index.md").exists())
            self.assertTrue((atlas_root / "projects" / "index.md").exists())

            index_note = (atlas_root / "index.md").read_text(encoding="utf-8")
            self.assertIn("[[daily/index]]", index_note)
            self.assertIn("[[projects/index]]", index_note)
            self.assertIn("[[agents/MASTER_SUMMARY]]", index_note)

    def test_import_claude_session_updates_session_daily_project_entity_and_summary_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            atlas_root = Path(tempdir) / "atlas"
            self._init_atlas(atlas_root)

            session_path = Path(tempdir) / "2026-04-16-maps-session.tmp"
            session_path.write_text(
                "# Session: 2026-04-16\n"
                "**Date:** 2026-04-16\n"
                "**Started:** 10:55\n"
                "**Last Updated:** 20:35\n"
                "\n---\n"
                "<!-- ECC:SUMMARY:START -->\n"
                "## Session Summary\n\n"
                "### Tasks\n"
                "- finish cartographer session import plumbing\n"
                "- call Chris back after the HopeAgent review\n"
                "- write mapsOS feedback for Irene\n\n"
                "### Files Modified\n"
                "- /Users/maps/dev/cartographer/cartographer/cli.py\n"
                "- /Users/maps/voicetape/server.py\n"
                "<!-- ECC:SUMMARY:END -->\n",
                encoding="utf-8",
            )

            result = import_sessions(atlas_root, "claude", [session_path])

            self.assertEqual(result["count"], 1)
            self.assertTrue((atlas_root / "agents" / "claude" / "sessions" / "2026-04-16-maps-session.md").exists())
            self.assertTrue((atlas_root / "agents" / "claude" / "SUMMARY.md").exists())
            self.assertTrue((atlas_root / "daily" / "2026-04-16.md").exists())
            self.assertTrue((atlas_root / "projects" / "cartographer.md").exists())
            self.assertTrue((atlas_root / "projects" / "mapsos.md").exists())
            self.assertTrue((atlas_root / "entities" / "chris.md").exists())
            self.assertTrue((atlas_root / "tasks" / "session-imports.md").exists())

            daily_text = (atlas_root / "daily" / "2026-04-16.md").read_text(encoding="utf-8")
            self.assertIn("Imported Session 2026-04-16-maps-session", daily_text)
            self.assertIn("[[cartographer]]", daily_text)
            self.assertIn("call Chris back after the HopeAgent review", daily_text)

            task_surface = (atlas_root / "tasks" / "session-imports.md").read_text(encoding="utf-8")
            self.assertIn("imported session requests are captured here", task_surface)

            index = Index(atlas_root)
            index.rebuild()
            self.assertEqual(index.find_note_path("claude-summary"), atlas_root / "agents" / "claude" / "SUMMARY.md")

    def test_import_hermes_session_updates_session_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            atlas_root = Path(tempdir) / "atlas"
            self._init_atlas(atlas_root)

            session_path = Path(tempdir) / "session_20260416_214759_5b702d.json"
            session_path.write_text(
                json.dumps(
                    {
                        "session_id": "20260416_214759_5b702d",
                        "session_start": "2026-04-16T21:51:51",
                        "last_updated": "2026-04-16T23:20:03",
                        "model": "z-ai/glm5",
                        "messages": [
                            {
                                "role": "user",
                                "content": "summarize MASTER_SUMMARY.md and scaffold cartographer feedback for mapsOS and Irene",
                            },
                            {
                                "role": "user",
                                "content": "read the cartographer initial population prompt and begin with Chris and mapsOS context",
                            },
                            {
                                "role": "assistant",
                                "content": "I summarized the mapsOS learning layer and wrote the scaffold back into cartographer notes.",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = import_sessions(atlas_root, "hermes", [session_path])

            self.assertEqual(result["count"], 1)
            self.assertTrue((atlas_root / "agents" / "hermes" / "sessions" / "session-20260416-214759-5b702d.md").exists())
            self.assertTrue((atlas_root / "agents" / "hermes" / "SUMMARY.md").exists())
            self.assertTrue((atlas_root / "projects" / "cartographer.md").exists())
            self.assertTrue((atlas_root / "projects" / "mapsos.md").exists())
            self.assertTrue((atlas_root / "entities" / "chris.md").exists())

            summary_note = Note.from_file(atlas_root / "agents" / "hermes" / "SUMMARY.md")
            self.assertEqual(summary_note.frontmatter.get("id"), "hermes-summary")
            self.assertEqual(summary_note.frontmatter.get("type"), "agent-summary")

    def test_entity_surfaces_use_session_backlinks_and_cleanup_migrates_old_import_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            atlas_root = Path(tempdir) / "atlas"
            self._init_atlas(atlas_root)

            session_path = Path(tempdir) / "session_20260416_214759_5b702d.json"
            session_path.write_text(
                json.dumps(
                    {
                        "session_id": "20260416_214759_5b702d",
                        "session_start": "2026-04-16T21:51:51",
                        "last_updated": "2026-04-16T23:20:03",
                        "model": "z-ai/glm5",
                        "messages": [
                            {
                                "role": "user",
                                "content": "summarize MASTER_SUMMARY.md and scaffold cartographer feedback for mapsOS and Irene",
                            },
                            {
                                "role": "assistant",
                                "content": "I summarized the mapsOS learning layer and wrote the scaffold back into cartographer notes.",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            import_sessions(atlas_root, "hermes", [session_path])

            entity_path = atlas_root / "entities" / "irene.md"
            entity_text = entity_path.read_text(encoding="utf-8")
            self.assertIn("## Sessions", entity_text)
            self.assertIn("[[session-20260416-214759-5b702d]] (2026-04-16)", entity_text)
            self.assertNotIn("## Imported Session", entity_text)
            self.assertNotIn("cart:session-import", entity_text)

            legacy_entity = atlas_root / "entities" / "chris.md"
            legacy_entity.write_text(
                "---\n"
                "id: chris\n"
                "title: Chris\n"
                "type: entity\n"
                "created: 2026-04-16\n"
                "modified: 2026-04-16\n"
                "links: []\n"
                "---\n\n"
                "# Chris\n\n"
                "Founder.\n\n"
                "<!-- cart:session-import-session-20260416-200632-9f9122 start -->\n"
                "## Imported Session session_20260416_200632_9f9122\n\n"
                "- session: [[session-20260416-200632-9f9122]]\n"
                "- date: 2026-04-16\n"
                "- summary: generated master summary\n"
                "<!-- cart:session-import-session-20260416-200632-9f9122 end -->\n",
                encoding="utf-8",
            )

            result = clean_entity_imports(atlas_root)

            self.assertGreaterEqual(result["updated"], 1)
            self.assertIn(str(legacy_entity), result["paths"])
            cleaned_text = legacy_entity.read_text(encoding="utf-8")
            self.assertIn("## Sessions", cleaned_text)
            self.assertIn("[[session-20260416-200632-9f9122]] (2026-04-16)", cleaned_text)
            self.assertNotIn("## Imported Session", cleaned_text)
            self.assertNotIn("cart:session-import", cleaned_text)


if __name__ == "__main__":
    unittest.main()
