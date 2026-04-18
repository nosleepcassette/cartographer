from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cartographer.tasks import append_task
from cartographer.tui import (
    NoteRecord,
    build_graph_sections,
    build_graph_rows,
    build_state_strip_lines,
    build_visual_graph_text,
    resolve_transclusions,
)


class TUIHelperTests(unittest.TestCase):
    def test_build_graph_rows_filter_keeps_direct_neighbors(self) -> None:
        records = {
            "hopeagent": NoteRecord(
                note_id="hopeagent",
                path=Path("/tmp/hopeagent.md"),
                title="hopeagent",
                note_type="project",
                status="active",
                tags=[],
                modified=10,
            ),
            "cartographer": NoteRecord(
                note_id="cartographer",
                path=Path("/tmp/cartographer.md"),
                title="cartographer",
                note_type="project",
                status="active",
                tags=[],
                modified=9,
            ),
            "maggie": NoteRecord(
                note_id="maggie",
                path=Path("/tmp/maggie.md"),
                title="maggie",
                note_type="entity",
                status=None,
                tags=[],
                modified=8,
            ),
        }
        edges = {("hopeagent", "cartographer")}

        rows = build_graph_rows(records, edges, filter_text="hope")
        visible_ids = {row.note_id for row in rows}

        self.assertEqual(visible_ids, {"hopeagent", "cartographer"})

    def test_build_graph_sections_supports_collapsed_groups(self) -> None:
        records = {
            "hopeagent": NoteRecord(
                note_id="hopeagent",
                path=Path("/tmp/hopeagent.md"),
                title="hopeagent",
                note_type="project",
                status="active",
                tags=[],
                modified=10,
            ),
            "maggie": NoteRecord(
                note_id="maggie",
                path=Path("/tmp/maggie.md"),
                title="maggie",
                note_type="entity",
                status=None,
                tags=[],
                modified=8,
            ),
        }

        sections = build_graph_sections(
            records,
            set(),
            collapsed_groups={"PROJECTS"},
        )

        self.assertEqual([section.group for section in sections], ["PROJECTS", "ENTITIES"])
        self.assertTrue(sections[0].collapsed)
        self.assertEqual(sections[0].rows, [])
        self.assertEqual(sections[1].total_count, 1)

    def test_resolve_transclusions_formats_note_and_block_content(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            source = root / "source-note.md"
            source.write_text(
                "---\n"
                "id: source-note\n"
                "title: Source Note\n"
                "type: note\n"
                "---\n\n"
                "line one\n\n"
                "line two\n",
                encoding="utf-8",
            )
            blocks = root / "block-note.md"
            blocks.write_text(
                "---\n"
                "id: block-note\n"
                "title: Block Note\n"
                "type: note\n"
                "---\n\n"
                '<!-- cart:block id="b001" -->\n'
                "block body\n"
                "<!-- /cart:block -->\n",
                encoding="utf-8",
            )
            records = {
                "source-note": NoteRecord(
                    note_id="source-note",
                    path=source,
                    title="Source Note",
                    note_type="note",
                    status=None,
                    tags=[],
                    modified=1,
                ),
                "block-note": NoteRecord(
                    note_id="block-note",
                    path=blocks,
                    title="Block Note",
                    note_type="note",
                    status=None,
                    tags=[],
                    modified=1,
                ),
            }

            rendered = resolve_transclusions(
                "before\n\n![[source-note]]\n\n![[block-note#b001]]\n\nafter",
                records,
            )

            self.assertIn("┊ line one", rendered)
            self.assertIn("┊ line two", rendered)
            self.assertIn("┊ block body", rendered)
            self.assertIn("┊ ↩ [[source-note]]", rendered)
            self.assertIn("┊ ↩ [[block-note]]", rendered)

    def test_build_state_strip_lines_surfaces_mapsos_state_and_p0_count(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            atlas_root = Path(tempdir) / "atlas"
            append_task(atlas_root, "ship atlas tui", priority="P0")

            line_one, line_two = build_state_strip_lines(
                atlas_root,
                {},
                {
                    "date": "2026-04-17",
                    "state": "grounded",
                    "body": {"energy": "steady", "sleep": "ok"},
                    "arcs": ["deep-focus"],
                },
            )

            self.assertIn("mapsOS  ● grounded", line_one)
            self.assertIn("BODY energy:steady", line_one)
            self.assertIn("[deep-focus]", line_one)
            self.assertIn("P0: 1 open", line_one)
            self.assertIn("last session: 2026-04-17", line_two)

    def test_build_visual_graph_text_surfaces_focus_and_neighbor_counts(self) -> None:
        records = {
            "alpha": NoteRecord(
                note_id="alpha",
                path=Path("/tmp/alpha.md"),
                title="Alpha",
                note_type="project",
                status="active",
                tags=[],
                modified=10,
            ),
            "beta": NoteRecord(
                note_id="beta",
                path=Path("/tmp/beta.md"),
                title="Beta",
                note_type="entity",
                status=None,
                tags=[],
                modified=9,
            ),
            "gamma": NoteRecord(
                note_id="gamma",
                path=Path("/tmp/gamma.md"),
                title="Gamma",
                note_type="learning",
                status=None,
                tags=[],
                modified=8,
            ),
        }
        neighbor_map = {
            "alpha": {"beta", "gamma"},
            "beta": {"alpha"},
            "gamma": {"alpha"},
        }

        text = build_visual_graph_text(
            records,
            neighbor_map,
            "alpha",
            visible_count=3,
            filter_text="alp",
        ).plain

        self.assertIn("GRAPH FOCUS", text)
        self.assertIn("Alpha", text)
        self.assertIn("Beta", text)
        self.assertIn("Gamma", text)
        self.assertIn("2 direct", text)
        self.assertIn("filter: alp", text)


if __name__ == "__main__":
    unittest.main()
