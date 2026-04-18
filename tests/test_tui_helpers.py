from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cartographer.tasks import append_task
from cartographer.tui import (
    NoteRecord,
    build_section_submenu_markdown,
    build_graph_sections,
    build_graph_rows,
    build_state_strip_lines,
    build_wire_neighborhood_markdown,
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
        self.assertEqual(sections[0].note_ids, ["hopeagent"])
        self.assertEqual(sections[1].total_count, 1)

    def test_build_section_submenu_markdown_lists_hidden_notes(self) -> None:
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
                status=None,
                tags=[],
                modified=9,
            ),
        }
        section = build_graph_sections(
            records,
            set(),
            collapsed_groups={"PROJECTS"},
        )[0]

        text = build_section_submenu_markdown(records, section)

        self.assertIn("# PROJECTS", text)
        self.assertIn("2 notes hidden", text)
        self.assertIn("[[hopeagent]]", text)
        self.assertIn("[[cartographer]]", text)

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

    def test_build_wire_neighborhood_markdown_formats_directional_links(self) -> None:
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
        text = build_wire_neighborhood_markdown(
            records,
            wire_summary={
                "outgoing": [{"note_id": "beta", "predicate": "supports", "bidirectional": False}],
                "incoming": [{"note_id": "gamma", "predicate": "grounds", "bidirectional": False}],
            },
            backlinks=[("beta", 2)],
            show_backlinks=True,
        )

        self.assertIn("## Wire Neighborhood", text)
        self.assertIn("### Outgoing", text)
        self.assertIn("### Incoming", text)
        self.assertIn("### Backlinks", text)
        self.assertIn("supports", text)
        self.assertIn("grounds", text)
        self.assertIn("[beta](note://beta)", text)
        self.assertIn("[gamma](note://gamma)", text)
        self.assertIn("(2 refs)", text)


if __name__ == "__main__":
    unittest.main()
