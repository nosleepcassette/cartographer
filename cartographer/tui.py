# maps · cassette.help · MIT
"""Textual atlas TUI for cartographer."""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from rich.columns import Columns
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Key
from textual.widgets import Input, Markdown, Static

from .atlas import Atlas
from .index import Index
from .notes import Note, parse_link_target
from .tasks import query_tasks, sort_tasks
from .wires import VALID_WIRE_PREDICATES


BACKGROUND = "#0d0d0d"
PRIMARY = "#c8a96e"
DIM = "#5a4a2a"
HIGHLIGHT = "#e8c87e"
MUTED_BLUE = "#7b9eb5"
BORDER = "#3a3a3a"

TYPE_COLORS = {
    "project": "#c47c7c",
    "entity": "#7ab87e",
    "agent-log": "#7b9eb5",
    "session": "#7b9eb5",
    "daily": "#9e6ba8",
    "learning": "#c4a87c",
}

TYPE_SYMBOLS = {
    "project": "●",
    "entity": "●",
    "agent-log": "○",
    "session": "○",
    "daily": "○",
    "learning": "◆",
}

TRANSCLUSION_PATTERN = re.compile(r"!\[\[([^\]]+)\]\]")
SESSION_TYPES = {"agent-log", "session", "daily"}
GROUP_ORDER = ["PROJECTS", "ENTITIES", "LEARNINGS", "SESSIONS", "OTHER"]


@dataclass(slots=True)
class NoteRecord:
    note_id: str
    path: Path
    title: str
    note_type: str
    status: str | None
    tags: list[str]
    modified: float

    @property
    def label(self) -> str:
        return self.title or self.note_id


@dataclass(slots=True)
class GraphRow:
    group: str
    note_id: str
    line: Text


@dataclass(slots=True)
class GraphSection:
    group: str
    rows: list[GraphRow]
    total_count: int
    collapsed: bool


class HeaderBar(Static):
    pass


class GraphPane(Vertical):
    pass


class NotePane(Vertical):
    pass


class StateStrip(Static):
    pass


class FooterStrip(Static):
    pass


class TasksOverlay(VerticalScroll):
    pass


def _sqlite_connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def _decode_json_list(raw: Any) -> list[str]:
    if raw in (None, ""):
        return []
    try:
        decoded = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(decoded, list):
        return []
    return [str(item) for item in decoded if isinstance(item, (str, int, float))]


def _group_for_type(note_type: str) -> str:
    normalized = note_type.lower()
    if normalized == "project":
        return "PROJECTS"
    if normalized == "entity":
        return "ENTITIES"
    if normalized == "learning":
        return "LEARNINGS"
    if normalized in SESSION_TYPES:
        return "SESSIONS"
    return "OTHER"


def _color_for_type(note_type: str) -> str:
    normalized = note_type.lower()
    if normalized in SESSION_TYPES:
        return TYPE_COLORS["agent-log"] if normalized != "daily" else TYPE_COLORS["daily"]
    return TYPE_COLORS.get(normalized, PRIMARY)


def _symbol_for_type(note_type: str) -> str:
    normalized = note_type.lower()
    if normalized in SESSION_TYPES:
        return TYPE_SYMBOLS["daily"] if normalized == "daily" else TYPE_SYMBOLS["agent-log"]
    return TYPE_SYMBOLS.get(normalized, "●")


def load_note_records(db_path: Path) -> dict[str, NoteRecord]:
    with _sqlite_connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, path, title, type, status, tags, modified
            FROM notes
            ORDER BY type ASC, modified DESC
            """
        ).fetchall()
    records: dict[str, NoteRecord] = {}
    for row in rows:
        note_id = str(row["id"])
        records[note_id] = NoteRecord(
            note_id=note_id,
            path=Path(str(row["path"])),
            title=str(row["title"] or note_id),
            note_type=str(row["type"] or "note"),
            status=None if row["status"] is None else str(row["status"]),
            tags=_decode_json_list(row["tags"]),
            modified=float(row["modified"] or 0.0),
        )
    return records


def load_edges(db_path: Path) -> set[tuple[str, str]]:
    with _sqlite_connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT DISTINCT from_note, to_note
            FROM block_refs
            WHERE from_note != to_note
            """
        ).fetchall()
    return {
        (str(row["from_note"]), str(row["to_note"]))
        for row in rows
        if row["from_note"] and row["to_note"]
    }


def build_neighbor_map(
    edges: set[tuple[str, str]],
) -> dict[str, set[str]]:
    neighbors: dict[str, set[str]] = {}
    for from_note, to_note in edges:
        neighbors.setdefault(from_note, set()).add(to_note)
        neighbors.setdefault(to_note, set()).add(from_note)
    return neighbors


def visible_note_ids(
    records: dict[str, NoteRecord],
    neighbor_map: dict[str, set[str]],
    filter_text: str,
) -> set[str]:
    if not filter_text.strip():
        return set(records)
    needle = filter_text.strip().lower()
    matches = {
        note_id
        for note_id, record in records.items()
        if needle in note_id.lower() or needle in record.title.lower()
    }
    visible = set(matches)
    for note_id in matches:
        visible.update(neighbor_map.get(note_id, set()))
    return visible


def build_graph_rows(
    records: dict[str, NoteRecord],
    edges: set[tuple[str, str]],
    *,
    filter_text: str = "",
) -> list[GraphRow]:
    return flatten_graph_rows(
        build_graph_sections(
            records,
            edges,
            filter_text=filter_text,
        )
    )


def build_graph_sections(
    records: dict[str, NoteRecord],
    edges: set[tuple[str, str]],
    *,
    filter_text: str = "",
    collapsed_groups: set[str] | None = None,
) -> list[GraphSection]:
    neighbor_map = build_neighbor_map(edges)
    visible_ids = visible_note_ids(records, neighbor_map, filter_text)
    collapsed_lookup = collapsed_groups or set()
    grouped: dict[str, list[NoteRecord]] = {group: [] for group in GROUP_ORDER}
    for record in records.values():
        if visible_ids and record.note_id not in visible_ids:
            continue
        grouped.setdefault(_group_for_type(record.note_type), []).append(record)

    for group, items in grouped.items():
        items.sort(
            key=lambda item: (
                0 if group == "SESSIONS" else 1,
                -item.modified,
                item.label.lower(),
            )
        )
        if group == "SESSIONS":
            grouped[group] = items[:8]

    sections: list[GraphSection] = []
    for group in GROUP_ORDER:
        items = grouped.get(group, [])
        if not items:
            continue
        if group in collapsed_lookup:
            sections.append(
                GraphSection(
                    group=group,
                    rows=[],
                    total_count=len(items),
                    collapsed=True,
                )
            )
            continue
        rows: list[GraphRow] = []
        for record in items:
            line = Text()
            line.append("  ")
            line.append(
                f"{_symbol_for_type(record.note_type)} {record.label}",
                style=_color_for_type(record.note_type),
            )
            neighbors = [
                records[neighbor_id]
                for neighbor_id in sorted(
                    {
                        neighbor_id
                        for neighbor_id in neighbor_map.get(record.note_id, set())
                        if neighbor_id in records
                    },
                    key=lambda candidate: (
                        _group_for_type(records[candidate].note_type),
                        records[candidate].label.lower(),
                    ),
                )
                if neighbor_id in visible_ids
            ]
            if neighbors:
                line.append(" ──── ", style=DIM)
                for index, neighbor in enumerate(neighbors[:3]):
                    if index:
                        line.append(" · ", style=DIM)
                    line.append(
                        f"{_symbol_for_type(neighbor.note_type)} {neighbor.label}",
                        style=_color_for_type(neighbor.note_type),
                    )
            rows.append(GraphRow(group=group, note_id=record.note_id, line=line))
        sections.append(
            GraphSection(
                group=group,
                rows=rows,
                total_count=len(items),
                collapsed=False,
            )
        )
    return sections


def flatten_graph_rows(sections: list[GraphSection]) -> list[GraphRow]:
    rows: list[GraphRow] = []
    for section in sections:
        rows.extend(section.rows)
    return rows


def _truncate_label(label: str, *, limit: int) -> str:
    if len(label) <= limit:
        return label
    if limit <= 1:
        return label[:limit]
    return label[: limit - 1] + "…"


def _append_node_label(text: Text, record: NoteRecord, *, limit: int = 20) -> int:
    plain = f"{_symbol_for_type(record.note_type)} {_truncate_label(record.label, limit=limit)}"
    text.append(plain, style=_color_for_type(record.note_type))
    return len(plain)


def build_visual_graph_text(
    records: dict[str, NoteRecord],
    neighbor_map: dict[str, set[str]],
    selected_note_id: str | None,
    *,
    visible_count: int,
    filter_text: str = "",
    wire_summary: dict[str, list[dict[str, Any]]] | None = None,
) -> Text:
    if selected_note_id is None or selected_note_id not in records:
        return Text("select a note to inspect the graph focus", style=DIM)

    focus = records[selected_note_id]
    neighbors = [
        records[neighbor_id]
        for neighbor_id in sorted(
            {
                neighbor_id
                for neighbor_id in neighbor_map.get(selected_note_id, set())
                if neighbor_id in records
            },
            key=lambda candidate: (
                -len(neighbor_map.get(candidate, set())),
                _group_for_type(records[candidate].note_type),
                records[candidate].label.lower(),
            ),
        )
    ]
    direct_count = len(neighbors)
    neighbor_ids = {neighbor.note_id for neighbor in neighbors}
    second_hop_count = len(
        {
            candidate
            for neighbor in neighbors
            for candidate in neighbor_map.get(neighbor.note_id, set())
            if candidate in records and candidate != selected_note_id and candidate not in neighbor_ids
        }
    )
    display_neighbors = neighbors[:6]
    left = display_neighbors[:3]
    right = display_neighbors[3:6]

    content = Text()
    content.append("GRAPH FOCUS\n", style=f"bold {HIGHLIGHT}")

    for neighbor in left:
        _append_node_label(content, neighbor, limit=19)
        content.append(" ─┤\n", style=DIM)

    focus_plain = f"{_symbol_for_type(focus.note_type)} {_truncate_label(focus.label, limit=24)}"
    content.append(focus_plain, style=f"bold {_color_for_type(focus.note_type)}")
    if right:
        content.append(" ─┼─ ", style=DIM)
        _append_node_label(content, right[0], limit=19)
        content.append("\n")
        focus_indent = " " * len(focus_plain)
        for index, neighbor in enumerate(right[1:]):
            connector = " ├─ " if index < len(right[1:]) - 1 else " └─ "
            content.append(focus_indent, style=DIM)
            content.append(connector, style=DIM)
            _append_node_label(content, neighbor, limit=19)
            content.append("\n")
    else:
        content.append("\n")

    if direct_count > len(display_neighbors):
        content.append(
            f"+{direct_count - len(display_neighbors)} more direct links\n",
            style=DIM,
        )

    meta = f"{direct_count} direct · {second_hop_count} second-hop · {visible_count} visible"
    if filter_text.strip():
        meta += f" · filter: {filter_text.strip()}"
    content.append(meta, style=DIM)
    wire_summary = wire_summary or {"outgoing": [], "incoming": []}
    semantic_lines: list[tuple[str, dict[str, Any]]] = []
    for item in wire_summary.get("outgoing", [])[:2]:
        semantic_lines.append(("out", item))
    for item in wire_summary.get("incoming", [])[:2]:
        semantic_lines.append(("in", item))
    if semantic_lines:
        content.append("\n\nSEMANTIC WIRES\n", style=f"bold {HIGHLIGHT}")
        for direction, item in semantic_lines:
            note_id = str(item.get("note_id") or "")
            predicate = str(item.get("predicate") or "")
            bidirectional = bool(item.get("bidirectional"))
            label = records[note_id].label if note_id in records else note_id
            marker = "->" if direction == "out" else "<-"
            content.append(f"{direction:3} {predicate} {marker} ", style=DIM)
            if note_id in records:
                _append_node_label(content, records[note_id], limit=18)
            else:
                content.append(label, style=MUTED_BLUE)
            if bidirectional:
                content.append(" [bi]", style=DIM)
            content.append("\n")
    return content


def resolve_transclusions(
    body: str,
    records: dict[str, NoteRecord],
    *,
    depth: int = 0,
    visited: set[tuple[str, str | None]] | None = None,
) -> str:
    if depth >= 3:
        return body
    seen = visited or set()

    def replace(match: re.Match[str]) -> str:
        target = match.group(1).strip()
        note_id, block_id = parse_link_target(target)
        key = (note_id, block_id)
        if not note_id or note_id not in records or key in seen:
            return match.group(0)
        seen.add(key)
        try:
            note = Note.from_file(records[note_id].path)
        except Exception:
            return match.group(0)
        if block_id:
            content = next(
                (block.content.strip() for block in note.blocks if block.id == block_id),
                "",
            )
        else:
            content = note.body.strip()
        if not content:
            return match.group(0)
        resolved = resolve_transclusions(
            content,
            records,
            depth=depth + 1,
            visited=seen,
        ).strip("\n")
        prefixed = "\n".join(
            f"┊ {line}" if line else "┊"
            for line in resolved.splitlines()
        )
        source_line = f"┊ ↩ [[{note_id}]]"
        return f"{prefixed}\n{source_line}"

    return TRANSCLUSION_PATTERN.sub(replace, body)


def load_backlinks(db_path: Path, note_id: str) -> list[tuple[str, int]]:
    with _sqlite_connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT from_note, COUNT(*) AS ref_count
            FROM block_refs
            WHERE to_note = ?
            GROUP BY from_note
            ORDER BY ref_count DESC, from_note ASC
            """,
            (note_id,),
        ).fetchall()
    return [(str(row["from_note"]), int(row["ref_count"])) for row in rows]


def load_wire_summary(db_path: Path, note_id: str) -> dict[str, list[dict[str, Any]]]:
    valid_predicates = tuple(VALID_WIRE_PREDICATES)
    placeholders = ", ".join("?" for _ in valid_predicates)
    with _sqlite_connect(db_path) as connection:
        outgoing_rows = connection.execute(
            f"""
            SELECT target_note, target_block, predicate, bidirectional
            FROM wires
            WHERE source_note = ? AND predicate IN ({placeholders})
            ORDER BY path ASC, line ASC
            LIMIT 6
            """,
            (note_id, *valid_predicates),
        ).fetchall()
        incoming_rows = connection.execute(
            f"""
            SELECT source_note, source_block, predicate, bidirectional
            FROM wires
            WHERE target_note = ? AND predicate IN ({placeholders})
            ORDER BY path ASC, line ASC
            LIMIT 6
            """,
            (note_id, *valid_predicates),
        ).fetchall()
    return {
        "outgoing": [
            {
                "note_id": str(row["target_note"]),
                "block_id": None if row["target_block"] is None else str(row["target_block"]),
                "predicate": str(row["predicate"]),
                "bidirectional": bool(row["bidirectional"]),
            }
            for row in outgoing_rows
        ],
        "incoming": [
            {
                "note_id": str(row["source_note"]),
                "block_id": None if row["source_block"] is None else str(row["source_block"]),
                "predicate": str(row["predicate"]),
                "bidirectional": bool(row["bidirectional"]),
            }
            for row in incoming_rows
        ],
    }


def read_mapsos_state() -> dict[str, Any]:
    export_dir = Path.home() / ".mapsOS" / "exports"
    if not export_dir.exists():
        return {}
    files = sorted(export_dir.glob("*.json"))
    if not files:
        return {}
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _normalize_arc_labels(value: Any) -> list[str]:
    labels: list[str] = []
    if isinstance(value, list):
        items = value
    elif value is None:
        items = []
    else:
        items = [value]
    for item in items:
        if isinstance(item, str) and item.strip():
            labels.append(item.strip())
        elif isinstance(item, dict):
            for key in ("label", "name", "title", "id", "arc"):
                maybe = item.get(key)
                if isinstance(maybe, str) and maybe.strip():
                    labels.append(maybe.strip())
                    break
    return labels


def build_state_strip_lines(
    atlas_root: Path,
    records: dict[str, NoteRecord],
    mapsos_state: dict[str, Any],
) -> tuple[str, str]:
    session_count = sum(
        1
        for record in records.values()
        if _group_for_type(record.note_type) == "SESSIONS"
    )
    note_count = len(records)
    if not mapsos_state:
        return (
            "mapsOS  ○ not connected  (run: maps)",
            f"cart {note_count} notes  ·  {session_count} sessions",
        )

    state_tag = str(mapsos_state.get("state") or "unknown")
    body = mapsos_state.get("body")
    body_bits: list[str] = []
    if isinstance(body, dict):
        for key in ("energy", "sleep", "pain"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                body_bits.append(f"{key}:{value.strip()}")
    body_summary = "  ·  ".join(body_bits[:2]) if body_bits else "metrics pending"
    arcs = _normalize_arc_labels(mapsos_state.get("arcs"))
    arc_text = " ".join(f"[{label}]" for label in arcs[:4]) if arcs else "none"
    p0_open = len(query_tasks(atlas_root, "status:open priority:P0"))
    last_session = str(
        mapsos_state.get("date")
        or mapsos_state.get("session_date")
        or mapsos_state.get("day")
        or "unknown"
    )
    return (
        f"mapsOS  ● {state_tag}  ·  BODY {body_summary}  ·  arcs: {arc_text}  ·  P0: {p0_open} open",
        f"last session: {last_session}  ·  cart {note_count} notes  ·  {session_count} sessions",
    )


class CartTUI(App[None]):
    TITLE = "atlas"
    CSS_PATH = None
    CSS = f"""
    Screen {{
        background: {BACKGROUND};
        color: {PRIMARY};
    }}
    HeaderBar {{
        height: 1;
        background: #141414;
        color: {HIGHLIGHT};
        padding: 0 1;
    }}
    #main-row {{
        height: 1fr;
    }}
    GraphPane {{
        width: 44%;
        border-right: solid {BORDER};
        padding: 0 1;
    }}
    NotePane {{
        width: 56%;
        padding: 0 1;
    }}
    #graph-filter {{
        display: none;
        margin: 0 0 1 0;
        border: solid {BORDER};
        background: #111111;
        color: {HIGHLIGHT};
    }}
    #graph-visual {{
        height: 9;
        margin: 0 0 1 0;
        padding: 0 0 1 0;
        border-bottom: solid {BORDER};
        color: {PRIMARY};
    }}
    #graph-scroll, #note-scroll {{
        height: 1fr;
    }}
    #note-header {{
        height: 2;
        color: {HIGHLIGHT};
        padding: 0 0 1 0;
    }}
    #note-backlinks {{
        padding: 1 0 0 0;
        color: {DIM};
    }}
    StateStrip {{
        height: 3;
        background: #1a1a1a;
        border-top: solid {BORDER};
        color: {PRIMARY};
        padding: 0 1;
    }}
    FooterStrip {{
        height: 1;
        background: #101010;
        color: {DIM};
        padding: 0 1;
    }}
    #new-note-input {{
        display: none;
        dock: bottom;
        height: 3;
        border-top: solid {BORDER};
        background: #111111;
        color: {HIGHLIGHT};
        padding: 0 1;
    }}
    #tasks-overlay {{
        display: none;
        layer: overlay;
        width: 72%;
        height: 60%;
        align: center middle;
        border: solid {HIGHLIGHT};
        background: #111111;
        padding: 1 2;
    }}
    #tasks-body {{
        height: auto;
    }}
    .focused-pane {{
        background: #101010;
    }}
    """

    def __init__(self, atlas_root: str | None = None) -> None:
        super().__init__()
        self.atlas = Atlas(root=atlas_root)
        self.records: dict[str, NoteRecord] = {}
        self.edges: set[tuple[str, str]] = set()
        self.neighbor_map: dict[str, set[str]] = {}
        self.graph_sections: list[GraphSection] = []
        self.selected_note_id: str | None = None
        self.filter_text = ""
        self.focus_target = "graph"
        self.show_backlinks = False
        self.show_help = False
        self.show_visual_graph = True
        self.collapsed_groups: set[str] = set()
        self.note_body_cache: dict[str, tuple[float, str]] = {}
        self.backlinks_cache: dict[str, list[tuple[str, int]]] = {}
        self.wire_cache: dict[str, dict[str, list[dict[str, Any]]]] = {}
        self.tasks_cache: list[Any] = []
        self.mapsos_state: dict[str, Any] = {}

    def compose(self) -> ComposeResult:
        yield HeaderBar(id="header-bar")
        with Horizontal(id="main-row"):
            with GraphPane(id="graph-pane"):
                yield Input(placeholder="filter atlas...", id="graph-filter")
                yield Static(id="graph-visual")
                with VerticalScroll(id="graph-scroll"):
                    yield Static(id="graph-body")
            with NotePane(id="note-pane"):
                yield Static(id="note-header")
                with VerticalScroll(id="note-scroll"):
                    yield Markdown(id="note-body")
                    yield Static(id="note-backlinks")
        yield StateStrip(id="state-strip")
        yield FooterStrip(id="footer-strip")
        yield Input(placeholder="new note title", id="new-note-input")
        with TasksOverlay(id="tasks-overlay"):
            yield Static("[bold]open tasks[/bold]\n", id="tasks-title")
            yield Static(id="tasks-body")

    def on_mount(self) -> None:
        if not self.atlas.is_initialized():
            raise RuntimeError(
                f"atlas not initialized at {self.atlas.root}. run: cart init"
            )
        index = Index(self.atlas.root)
        if not self.atlas.index_db_path.exists() or index.needs_rebuild():
            index.rebuild()
        self.refresh_from_source()

    def refresh_from_source(self, *, select_note_id: str | None = None) -> None:
        previous_modified = {note_id: record.modified for note_id, record in self.records.items()}
        self.records = load_note_records(self.atlas.index_db_path)
        self.edges = load_edges(self.atlas.index_db_path)
        self.neighbor_map = build_neighbor_map(self.edges)
        self.mapsos_state = read_mapsos_state()
        self.tasks_cache = sort_tasks(query_tasks(self.atlas.root, "status:open"))
        self._prune_render_caches(previous_modified)
        self.rebuild_graph_view(select_note_id=select_note_id)
        self.render_header()
        self.render_graph()
        self.render_graph_visual()
        self.render_note()
        self.render_state_strip()
        self.render_footer()
        self.render_tasks()
        self.render_focus()

    def _prune_render_caches(self, previous_modified: dict[str, float]) -> None:
        current_ids = set(self.records)
        for note_id in list(self.note_body_cache):
            if note_id not in current_ids:
                self.note_body_cache.pop(note_id, None)
                continue
            if previous_modified.get(note_id) != self.records[note_id].modified:
                self.note_body_cache.pop(note_id, None)
        for note_id in list(self.backlinks_cache):
            if note_id not in current_ids:
                self.backlinks_cache.pop(note_id, None)
                continue
            if previous_modified.get(note_id) != self.records[note_id].modified:
                self.backlinks_cache.pop(note_id, None)
        for note_id in list(self.wire_cache):
            if note_id not in current_ids:
                self.wire_cache.pop(note_id, None)
                continue
            if previous_modified.get(note_id) != self.records[note_id].modified:
                self.wire_cache.pop(note_id, None)

    def _visible_graph_rows(self) -> list[GraphRow]:
        return flatten_graph_rows(self.graph_sections)

    def rebuild_graph_view(self, *, select_note_id: str | None = None) -> None:
        self.graph_sections = build_graph_sections(
            self.records,
            self.edges,
            filter_text=self.filter_text,
            collapsed_groups=self.collapsed_groups,
        )
        visible_rows = self._visible_graph_rows()
        visible_ids = {row.note_id for row in visible_rows}
        if select_note_id and select_note_id in visible_ids:
            self.selected_note_id = select_note_id
        elif self.selected_note_id not in visible_ids:
            self.selected_note_id = visible_rows[0].note_id if visible_rows else None

    def render_header(self) -> None:
        left = Text("ATLAS", style=f"bold {HIGHLIGHT}")
        right = Text(
            f"{len(self.records)} notes  ·  {date.today().isoformat()}",
            style=f"bold {PRIMARY}",
        )
        self.query_one("#header-bar", HeaderBar).update(Columns([left, right], expand=True))

    def render_graph(self) -> None:
        body = self.query_one("#graph-body", Static)
        if not self.graph_sections:
            body.update(Text("no matching notes", style=DIM))
            return

        text = Text()
        selected_group = None
        if self.selected_note_id and self.selected_note_id in self.records:
            selected_group = _group_for_type(self.records[self.selected_note_id].note_type)
        for index, section in enumerate(self.graph_sections):
            if index:
                text.append("\n")
            marker = "▶" if section.collapsed else "▼"
            header_style = f"bold {PRIMARY if section.group == selected_group else HIGHLIGHT}"
            text.append(
                f"{marker} {section.group} ({section.total_count})\n",
                style=header_style,
            )
            for row in section.rows:
                line = row.line.copy()
                if row.note_id == self.selected_note_id:
                    line.stylize("reverse")
                text.append_text(line)
                text.append("\n")
        body.update(text)

    def render_graph_visual(self) -> None:
        visual = self.query_one("#graph-visual", Static)
        visual.display = self.show_visual_graph
        if not self.show_visual_graph:
            return
        visual.update(
            build_visual_graph_text(
                self.records,
                self.neighbor_map,
                self.selected_note_id,
                visible_count=len(self._visible_graph_rows()),
                filter_text=self.filter_text,
                wire_summary=self._load_wires(self.selected_note_id) if self.selected_note_id else None,
            )
        )

    def _load_note_body(self, note_id: str) -> str:
        record = self.records[note_id]
        cached = self.note_body_cache.get(note_id)
        if cached and cached[0] == record.modified:
            return cached[1]
        try:
            note = Note.from_file(record.path)
            rendered = resolve_transclusions(note.body, self.records)
        except Exception as exc:
            rendered = f"failed to load note: {exc}"
        self.note_body_cache[note_id] = (record.modified, rendered)
        return rendered

    def _load_backlinks(self, note_id: str) -> list[tuple[str, int]]:
        if note_id not in self.backlinks_cache:
            self.backlinks_cache[note_id] = load_backlinks(self.atlas.index_db_path, note_id)
        return self.backlinks_cache[note_id]

    def _load_wires(self, note_id: str) -> dict[str, list[dict[str, Any]]]:
        if note_id not in self.wire_cache:
            self.wire_cache[note_id] = load_wire_summary(self.atlas.index_db_path, note_id)
        return self.wire_cache[note_id]

    def render_note(self) -> None:
        header = self.query_one("#note-header", Static)
        body = self.query_one("#note-body", Markdown)
        backlinks = self.query_one("#note-backlinks", Static)

        if self.selected_note_id is None or self.selected_note_id not in self.records:
            header.update(Text("no note selected", style=DIM))
            body.update("Select a note from the graph.")
            backlinks.display = False
            return

        record = self.records[self.selected_note_id]
        title = Text()
        title.append("# ", style=f"bold {HIGHLIGHT}")
        title.append(record.label, style=f"bold {HIGHLIGHT}")
        title.append(f"   [{record.note_type}]", style=_color_for_type(record.note_type))
        if record.status:
            title.append(f"   [{record.status}]", style=MUTED_BLUE)
        header.update(title)

        rendered = self._load_note_body(record.note_id)
        body.update(rendered)
        self.query_one("#note-scroll", VerticalScroll).scroll_home(animate=False)

        backlink_rows = self._load_backlinks(record.note_id)
        if self.show_backlinks and backlink_rows:
            backlink_text = Text()
            backlink_text.append("backlinks\n", style=f"bold {PRIMARY}")
            for ref_note, count in backlink_rows:
                backlink_text.append(
                    f"← [[{ref_note}]] ({count} refs)\n",
                    style=DIM,
                )
            backlinks.update(backlink_text)
            backlinks.display = True
        else:
            backlinks.update("")
            backlinks.display = False

    def render_state_strip(self) -> None:
        strip = self.query_one("#state-strip", StateStrip)
        line_one, line_two = build_state_strip_lines(
            self.atlas.root,
            self.records,
            self.mapsos_state,
        )
        content = Text()
        style = DIM if "not connected" in line_one else PRIMARY
        content.append(line_one + "\n", style=style)
        content.append(line_two, style=f"dim {PRIMARY}")
        strip.update(content)

    def render_footer(self) -> None:
        footer = self.query_one("#footer-strip", FooterStrip)
        if self.query_one("#new-note-input", Input).display:
            left = Text("new note title  [enter] create  [escape] cancel", style=DIM)
            right = Text("", style=DIM)
        elif self.query_one("#graph-filter", Input).display and self.query_one(
            "#graph-filter", Input
        ).has_focus:
            left = Text("filter graph  [esc] clear  [enter] keep filter", style=DIM)
            right = Text("", style=DIM)
        elif self.query_one("#tasks-overlay", TasksOverlay).display:
            left = Text("[j/k] scroll  [t] close  [escape] close  [q] quit", style=DIM)
            right = Text("", style=DIM)
        elif self.show_help:
            left = Text(
                "[h/l] panes  [tab] cycle  [j/k] move or scroll  [/] filter  "
                "[c] collapse  [g] graph  [enter] edit  [n] new  [m] mapsOS  [r] rebuild  [b] backlinks  [t] tasks  [q] quit",
                style=DIM,
            )
            right = Text("", style=DIM)
        elif self.focus_target == "note":
            left = Text(
                "[h/l] panes  [j/k] scroll  [b] backlinks  [c] collapse  [g] graph  [enter] edit  [m] mapsOS  [q] quit",
                style=DIM,
            )
            right = Text("[?] for all keys", style=DIM)
        else:
            left = Text(
                "[h/l] panes  [j/k] move  [/] filter  [c] collapse  [g] graph  [enter] edit  [m] mapsOS  [q] quit",
                style=DIM,
            )
            right = Text("[?] for all keys", style=DIM)
        footer.update(Columns([left, right], expand=True))

    def render_tasks(self) -> None:
        overlay = self.query_one("#tasks-overlay", TasksOverlay)
        body = self.query_one("#tasks-body", Static)
        if not self.tasks_cache:
            body.update(Text("no open tasks", style=DIM))
            overlay.scroll_home(animate=False)
            return
        content = Text()
        for task in self.tasks_cache[:50]:
            line = f"{task.priority}  {task.text}"
            if task.project:
                line += f"  ·  {task.project}"
            if task.due:
                line += f"  ·  due {task.due}"
            content.append(line + "\n", style=PRIMARY if task.priority == "P0" else DIM)
        body.update(content)
        overlay.scroll_home(animate=False)

    def render_focus(self) -> None:
        graph_pane = self.query_one("#graph-pane", GraphPane)
        note_pane = self.query_one("#note-pane", NotePane)
        graph_pane.remove_class("focused-pane")
        note_pane.remove_class("focused-pane")
        if self.focus_target == "note":
            note_pane.add_class("focused-pane")
        else:
            graph_pane.add_class("focused-pane")

    def move_graph_selection(self, delta: int) -> None:
        visible_rows = self._visible_graph_rows()
        if not visible_rows:
            return
        visible_ids = [row.note_id for row in visible_rows]
        if self.selected_note_id not in visible_ids:
            self.selected_note_id = visible_ids[0]
        current_index = visible_ids.index(self.selected_note_id)
        next_index = min(max(current_index + delta, 0), len(visible_ids) - 1)
        self.selected_note_id = visible_ids[next_index]
        self.render_graph()
        self.render_graph_visual()
        self.render_note()

    def move_note_scroll(self, delta: int) -> None:
        self.query_one("#note-scroll", VerticalScroll).scroll_relative(y=delta * 3)

    def move_tasks_scroll(self, delta: int) -> None:
        self.query_one("#tasks-overlay", TasksOverlay).scroll_relative(y=delta * 3)

    def toggle_filter(self) -> None:
        filter_input = self.query_one("#graph-filter", Input)
        filter_input.display = True
        self.set_focus(filter_input)
        self.render_footer()

    def close_filter(self, *, clear: bool = False) -> None:
        filter_input = self.query_one("#graph-filter", Input)
        if clear:
            filter_input.value = ""
            self.filter_text = ""
            self.rebuild_graph_view(select_note_id=self.selected_note_id)
            self.render_graph()
            self.render_graph_visual()
            self.render_note()
        filter_input.display = False
        self.set_focus(None)
        self.render_footer()

    def toggle_new_note_prompt(self) -> None:
        prompt = self.query_one("#new-note-input", Input)
        prompt.value = ""
        prompt.display = True
        self.set_focus(prompt)
        self.render_footer()

    def close_new_note_prompt(self) -> None:
        prompt = self.query_one("#new-note-input", Input)
        prompt.display = False
        prompt.value = ""
        self.set_focus(None)
        self.render_footer()

    def toggle_tasks_overlay(self) -> None:
        overlay = self.query_one("#tasks-overlay", TasksOverlay)
        overlay.display = not overlay.display
        self.focus_target = "tasks" if overlay.display else "graph"
        self.render_footer()
        self.render_focus()
        if overlay.display:
            self.render_tasks()

    def toggle_visual_graph(self) -> None:
        self.show_visual_graph = not self.show_visual_graph
        self.render_graph_visual()
        self.render_footer()

    def toggle_current_group(self) -> None:
        if self.selected_note_id is None or self.selected_note_id not in self.records:
            return
        group = _group_for_type(self.records[self.selected_note_id].note_type)
        if group in self.collapsed_groups:
            self.collapsed_groups.remove(group)
        else:
            self.collapsed_groups.add(group)
        self.rebuild_graph_view(select_note_id=self.selected_note_id)
        self.render_graph()
        self.render_graph_visual()
        self.render_note()
        self.render_footer()

    def action_open_selected_note(self) -> None:
        if self.selected_note_id is None:
            return
        record = self.records.get(self.selected_note_id)
        if record is None:
            return
        with self.suspend():
            self.atlas.open_in_editor(record.path)
            self.atlas.finalize_note(record.path)
            self.atlas.refresh_index()
        self.refresh_from_source(select_note_id=self.selected_note_id)

    def action_new_note(self, title: str) -> None:
        if not title.strip():
            return
        with self.suspend():
            path = self.atlas.create_note("note", title.strip())
            self.atlas.open_in_editor(path)
            self.atlas.finalize_note(path)
            self.atlas.refresh_index()
        self.refresh_from_source(select_note_id=path.stem)

    def action_launch_mapsos(self) -> None:
        maps_command: list[str] | None = None
        if shutil.which("maps"):
            maps_command = ["maps"]
        else:
            fallback = Path.home() / "dev" / "mapsOS" / "bin" / "maps"
            if fallback.exists():
                maps_command = [str(fallback)]
        if maps_command is None:
            return
        with self.suspend():
            subprocess.run(maps_command, check=False)
        self.refresh_from_source(select_note_id=self.selected_note_id)

    def action_rebuild(self) -> None:
        self.atlas.refresh_index()
        self.refresh_from_source(select_note_id=self.selected_note_id)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "graph-filter":
            return
        self.filter_text = event.value
        self.rebuild_graph_view(select_note_id=self.selected_note_id)
        self.render_graph()
        self.render_graph_visual()
        self.render_note()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "graph-filter":
            self.close_filter(clear=False)
            return
        if event.input.id == "new-note-input":
            value = event.value
            self.close_new_note_prompt()
            self.action_new_note(value)

    def on_key(self, event: Key) -> None:
        key = event.key
        filter_input = self.query_one("#graph-filter", Input)
        prompt = self.query_one("#new-note-input", Input)
        tasks_overlay = self.query_one("#tasks-overlay", TasksOverlay)

        if key == "escape":
            if prompt.display:
                self.close_new_note_prompt()
                event.stop()
                return
            if filter_input.display:
                self.close_filter(clear=True)
                event.stop()
                return
            if tasks_overlay.display:
                tasks_overlay.display = False
                self.focus_target = "graph"
                self.render_footer()
                self.render_focus()
                event.stop()
                return

        if prompt.display and prompt.has_focus:
            self.render_footer()
            return
        if filter_input.display and filter_input.has_focus:
            self.render_footer()
            return

        if key in {"ctrl+c"}:
            self.exit()
            event.stop()
            return
        if key == "q":
            self.exit()
            event.stop()
            return
        if key in {"down", "j"}:
            if tasks_overlay.display:
                self.move_tasks_scroll(1)
            elif self.focus_target == "note":
                self.move_note_scroll(1)
            else:
                self.move_graph_selection(1)
            event.stop()
            return
        if key in {"up", "k"}:
            if tasks_overlay.display:
                self.move_tasks_scroll(-1)
            elif self.focus_target == "note":
                self.move_note_scroll(-1)
            else:
                self.move_graph_selection(-1)
            event.stop()
            return
        if key in {"left", "h"}:
            if not tasks_overlay.display:
                self.focus_target = "graph"
                self.render_footer()
                self.render_focus()
            event.stop()
            return
        if key in {"right", "l"}:
            if not tasks_overlay.display:
                self.focus_target = "note"
                self.render_footer()
                self.render_focus()
            event.stop()
            return
        if key == "tab":
            if not tasks_overlay.display:
                self.focus_target = "note" if self.focus_target == "graph" else "graph"
                self.render_footer()
                self.render_focus()
            event.stop()
            return
        if key == "/":
            self.focus_target = "graph"
            self.render_focus()
            self.toggle_filter()
            event.stop()
            return
        if key == "enter":
            self.action_open_selected_note()
            event.stop()
            return
        if key == "n":
            self.toggle_new_note_prompt()
            event.stop()
            return
        if key == "m":
            self.action_launch_mapsos()
            event.stop()
            return
        if key == "r":
            self.action_rebuild()
            event.stop()
            return
        if key == "c":
            self.toggle_current_group()
            event.stop()
            return
        if key == "g":
            self.toggle_visual_graph()
            event.stop()
            return
        if key == "b":
            self.show_backlinks = not self.show_backlinks
            self.render_note()
            self.render_footer()
            event.stop()
            return
        if key == "t":
            self.toggle_tasks_overlay()
            event.stop()
            return
        if key == "?":
            self.show_help = not self.show_help
            self.render_footer()
            event.stop()
