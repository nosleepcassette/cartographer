from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from .notes import parse_frontmatter
from .wires import VALID_WIRE_PREDICATES


TYPE_COLORS = {
    "person": "#8ec1ff",
    "project": "#d97757",
    "goal": "#e6c15d",
    "entity": "#6cb88f",
    "agent-log": "#7aa6d9",
    "session": "#7aa6d9",
    "daily": "#d08bd7",
    "learning": "#d5b06b",
    "note": "#b6c2cf",
}

EMOTIONAL_NODE_COLORS = {
    "positive": "#67d98b",
    "negative": "#f06a74",
    "mixed": "#b988ff",
    "neutral": "#a7b3c3",
}

AVOIDANCE_RISK_SCALE = {
    "high": 1.58,
    "medium": 1.28,
    "low": 1.06,
    "none": 0.9,
}

SESSION_NOTE_TYPES = {"agent-log", "session", "daily"}


def _wire_metadata_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "relationship": None if row["relationship"] is None else str(row["relationship"]),
        "emotional_valence": None
        if row["emotional_valence"] is None
        else str(row["emotional_valence"]),
        "energy_impact": None if row["energy_impact"] is None else str(row["energy_impact"]),
        "avoidance_risk": None if row["avoidance_risk"] is None else str(row["avoidance_risk"]),
        "growth_edge": None if row["growth_edge"] is None else bool(row["growth_edge"]),
        "current_state": None if row["current_state"] is None else str(row["current_state"]),
        "since": None if row["since"] is None else str(row["since"]),
        "until": None if row["until"] is None else str(row["until"]),
        "valence_note": None if row["valence_note"] is None else str(row["valence_note"]),
    }


def _primary_emotional_summary(
    *,
    node_id: str,
    note_type: str,
    incident_wires: list[dict[str, Any]],
) -> dict[str, Any]:
    if note_type not in {"person", "project", "goal"}:
        return {}
    if not incident_wires:
        return {}
    primary = next(
        (
            wire
            for wire in incident_wires
            if {str(wire["source"]), str(wire["target"])} == {node_id, "maps"}
            and any(
                wire.get(field) is not None
                for field in (
                    "emotional_valence",
                    "energy_impact",
                    "avoidance_risk",
                    "growth_edge",
                    "current_state",
                    "valence_note",
                )
            )
        ),
        None,
    )
    if primary is None:
        primary = next(
            (
                wire
                for wire in incident_wires
                if any(
                    wire.get(field) is not None
                    for field in (
                        "emotional_valence",
                        "energy_impact",
                        "avoidance_risk",
                        "growth_edge",
                        "current_state",
                        "valence_note",
                    )
                )
            ),
            None,
        )
    if primary is None:
        return {}
    return {
        "emotional_valence": primary.get("emotional_valence"),
        "energy_impact": primary.get("energy_impact"),
        "avoidance_risk": primary.get("avoidance_risk"),
        "growth_edge": primary.get("growth_edge"),
        "current_state": primary.get("current_state"),
        "since": primary.get("since"),
        "until": primary.get("until"),
        "valence_note": primary.get("valence_note"),
    }


def _extract_folder(path_str: str, atlas_root: Path) -> str | None:
    """Extract top-level folder from note path for grouping."""
    if not path_str:
        return None
    try:
        path = Path(path_str).resolve()
        relative = path.relative_to(atlas_root.resolve())
        parts = relative.parts
        # Return first meaningful folder (skip root)
        if len(parts) > 1:
            return parts[0]
    except (ValueError, IndexError):
        pass
    return None


def _display_type_for_note(atlas_root: Path, raw_path: str, raw_type: str) -> str:
    normalized = raw_type.strip().lower() or "note"
    if normalized == "person":
        return "person"
    if normalized != "entity":
        return normalized

    path = Path(raw_path)
    try:
        relative = path.resolve().relative_to(atlas_root.resolve())
    except ValueError:
        relative = path

    try:
        frontmatter, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
    except OSError:
        frontmatter = {}

    entity_type = str(frontmatter.get("entity_type") or "").strip().lower()
    if entity_type:
        return entity_type
    if relative.parts and relative.parts[0] == "entities":
        return "person"
    return normalized


def _alias_map(atlas_root: Path, note_rows: list[sqlite3.Row]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for row in note_rows:
        note_id = str(row["id"])
        aliases[note_id] = note_id
        raw_path = str(row["path"] or "").strip()
        if not raw_path:
            continue
        try:
            relative = Path(raw_path).resolve().relative_to(atlas_root.resolve())
        except ValueError:
            continue
        aliases[relative.with_suffix("").as_posix()] = note_id
    return aliases


def _note_preview(path: Path, *, limit: int = 900) -> str:
    try:
        _, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    except OSError:
        return ""
    cleaned = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)
    cleaned = cleaned.replace("\r\n", "\n")
    lines = [re.sub(r"[ \t]+$", "", line) for line in cleaned.split("\n")]

    collapsed: list[str] = []
    blank_run = 0
    for line in lines:
        if not line.strip():
            blank_run += 1
            if blank_run > 1:
                continue
            collapsed.append("")
            continue
        blank_run = 0
        collapsed.append(line)

    cleaned = "\n".join(collapsed).strip()
    if len(cleaned) <= limit:
        return cleaned
    cutoff = cleaned.rfind("\n", 0, limit)
    if cutoff < int(limit * 0.6):
        cutoff = cleaned.rfind(" ", 0, limit)
    if cutoff < int(limit * 0.6):
        cutoff = limit - 1
    return cleaned[:cutoff].rstrip() + "\n…"


def _vendor_script_text(filename: str) -> str:
    path = Path(__file__).resolve().parent / "vendor" / filename
    return (
        path.read_text(encoding="utf-8")
        .replace("</", "<\\/")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def load_graph_payload(atlas_root: Path | str) -> dict[str, Any]:
    atlas_root = Path(atlas_root)
    db_path = atlas_root / ".cartographer" / "index.db"
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    try:
        note_rows = connection.execute(
            """
            SELECT id, path, title, type, status, tags, links, modified
            FROM notes
            ORDER BY type ASC, id ASC
            """
        ).fetchall()
        ref_rows = connection.execute(
            """
            SELECT DISTINCT from_note, to_note
            FROM block_refs
            WHERE from_note != to_note
            ORDER BY from_note ASC, to_note ASC
            """
        ).fetchall()
        wire_rows = connection.execute(
            """
            SELECT
                source_note,
                target_note,
                predicate,
                relationship,
                bidirectional,
                emotional_valence,
                energy_impact,
                avoidance_risk,
                growth_edge,
                current_state,
                since,
                until,
                valence_note
            FROM wires
            ORDER BY source_note ASC, target_note ASC, predicate ASC
            """
        ).fetchall()
    finally:
        connection.close()

    aliases = _alias_map(atlas_root, note_rows)
    edge_pairs: dict[tuple[str, str, str, str | None], dict[str, Any]] = {}
    unresolved_edge_count = 0

    for row in note_rows:
        source = aliases.get(str(row["id"]))
        if source is None:
            continue
        try:
            links = json.loads(row["links"]) if row["links"] else []
        except Exception:
            links = []
        if not isinstance(links, list):
            continue
        for target in links:
            target_id = aliases.get(str(target).strip())
            if target_id is None or target_id == source:
                if target_id is None:
                    unresolved_edge_count += 1
                continue
            edge_pairs[(source, target_id, "wikilink", None)] = {
                "source": source,
                "target": target_id,
                "kind": "wikilink",
            }

    for row in ref_rows:
        source = aliases.get(str(row["from_note"]).strip())
        target = aliases.get(str(row["to_note"]).strip())
        if source is None or target is None:
            unresolved_edge_count += 1
            continue
        if source == target:
            continue
        edge_pairs[(source, target, "wikilink", None)] = {
            "source": source,
            "target": target,
            "kind": "wikilink",
        }

    valid_predicates = set(VALID_WIRE_PREDICATES)
    wire_count = 0
    incident_wires: dict[str, list[dict[str, Any]]] = {}
    for row in wire_rows:
        predicate = str(row["predicate"] or "").strip()
        if predicate not in valid_predicates:
            continue
        source = aliases.get(str(row["source_note"]).strip())
        target = aliases.get(str(row["target_note"]).strip())
        if source is None or target is None:
            unresolved_edge_count += 1
            continue
        if source == target:
            continue
        edge_pairs[(source, target, "wire", predicate)] = {
            "source": source,
            "target": target,
            "kind": "wire",
            "predicate": predicate,
            **_wire_metadata_payload(row),
            "bidirectional": bool(row["bidirectional"]),
        }
        incident_payload = {
            "source": source,
            "target": target,
            "predicate": predicate,
            **_wire_metadata_payload(row),
            "bidirectional": bool(row["bidirectional"]),
        }
        incident_wires.setdefault(source, []).append(incident_payload)
        incident_wires.setdefault(target, []).append(incident_payload)
        wire_count += 1

    edges = [edge_pairs[key] for key in sorted(edge_pairs)]
    degree_counts: Counter[str] = Counter()
    for edge in edges:
        degree_counts.update((str(edge["source"]), str(edge["target"])))

    nodes: list[dict[str, Any]] = []
    type_counts: Counter[str] = Counter()
    for row in note_rows:
        raw_path = str(row["path"] or "")
        raw_type = str(row["type"] or "note")
        note_type = _display_type_for_note(atlas_root, raw_path, raw_type)
        type_counts[note_type] += 1
        try:
            tags = json.loads(row["tags"]) if row["tags"] else []
        except Exception:
            tags = []
        node_id = str(row["id"])
        type_color = TYPE_COLORS.get(note_type, TYPE_COLORS["note"])
        emotional_summary = _primary_emotional_summary(
            node_id=node_id,
            note_type=note_type,
            incident_wires=incident_wires.get(node_id, []),
        )
        emotional_valence = emotional_summary.get("emotional_valence")
        avoidance_risk = emotional_summary.get("avoidance_risk")
        folder = _extract_folder(raw_path, atlas_root)
        nodes.append(
            {
                "id": node_id,
                "title": str(row["title"] or node_id),
                "type": note_type,
                "raw_type": raw_type,
                "status": None if row["status"] is None else str(row["status"]),
                "path": raw_path,
                "folder": folder,
                "tags": tags if isinstance(tags, list) else [],
                "modified": float(row["modified"] or 0.0),
                "degree": degree_counts.get(node_id, 0),
                "type_color": type_color,
                "color": EMOTIONAL_NODE_COLORS.get(str(emotional_valence), type_color),
                "emotional_valence": emotional_valence,
                "energy_impact": emotional_summary.get("energy_impact"),
                "avoidance_risk": avoidance_risk,
                "growth_edge": emotional_summary.get("growth_edge"),
                "current_state": emotional_summary.get("current_state"),
                "since": emotional_summary.get("since"),
                "until": emotional_summary.get("until"),
                "valence_note": emotional_summary.get("valence_note"),
                "base_radius": round(
                    (4.8 + min(degree_counts.get(node_id, 0), 14) * 0.55)
                    * AVOIDANCE_RISK_SCALE.get(str(avoidance_risk), 1.0),
                    3,
                ),
                "preview": _note_preview(Path(raw_path)) if raw_path else "",
                "is_session": note_type in SESSION_NOTE_TYPES,
            }
        )

    return {
        "generated": date.today().isoformat(),
        "atlas_root": str(atlas_root),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "wire_count": wire_count,
        "unresolved_edge_count": unresolved_edge_count,
        "type_counts": dict(sorted(type_counts.items())),
        "nodes": nodes,
        "edges": edges,
    }


def render_graph_html(payload: dict[str, Any]) -> str:
    payload_json = (
        json.dumps(payload, ensure_ascii=False)
        .replace("</", "<\\/")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    vendor_three = _vendor_script_text("three.module.js")
    template = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>atlas graph</title>
  <style>
    :root {
      --bg: #06070b;
      --panel: rgba(14, 17, 27, 0.94);
      --panel-border: rgba(237, 203, 128, 0.2);
      --text: #f6efe1;
      --muted: #b7ab99;
      --accent: #edcb80;
      --surface: rgba(255, 255, 255, 0.05);
      --shadow: 0 28px 90px rgba(0, 0, 0, 0.45);
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; }
    body {
      background:
        radial-gradient(circle at top left, rgba(237, 203, 128, 0.13), transparent 28rem),
        radial-gradient(circle at bottom right, rgba(110, 180, 255, 0.12), transparent 30rem),
        linear-gradient(180deg, #05060a 0%, #0b0f17 52%, #101522 100%);
      color: var(--text);
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      overflow: hidden;
    }
    .app {
      display: grid;
      grid-template-columns: 19rem 1fr 20rem;
      gap: 0.65rem;
      height: 100vh;
      padding: 0.65rem;
    }
    .panel {
      min-height: 0;
      background: var(--panel);
      border: 1px solid var(--panel-border);
      border-radius: 1.15rem;
      box-shadow: var(--shadow);
      backdrop-filter: blur(16px);
    }
    .sidebar, .detail {
      display: flex;
      flex-direction: column;
      gap: 0.65rem;
      padding: 0.7rem;
      overflow: hidden;
    }
    .canvas-panel {
      position: relative;
      overflow: hidden;
      background:
        radial-gradient(circle at top, rgba(255, 244, 214, 0.08), transparent 44%),
        radial-gradient(circle at 18% 24%, rgba(92, 156, 255, 0.1), transparent 30%),
        linear-gradient(180deg, rgba(8, 10, 16, 0.98), rgba(9, 12, 18, 0.9));
    }
    #graph-canvas { position: absolute; inset: 0; }
    #graph-canvas canvas { display: block; width: 100%; height: 100%; }
    #label-layer {
      position: absolute;
      inset: 0;
      overflow: hidden;
      pointer-events: none;
    }
    .node-label {
      position: absolute;
      transform: translate(-50%, -50%);
      color: var(--text);
      font-size: 0.74rem;
      letter-spacing: 0.03em;
      white-space: nowrap;
      text-shadow: 0 0 12px rgba(0, 0, 0, 0.9);
    }
    .node-label.active { color: var(--accent); font-weight: 700; }
    .eyebrow {
      color: var(--muted);
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.18em;
    }
    h1, h2, p { margin: 0; }
    h1 {
      font-family: "Baskerville", "Iowan Old Style", serif;
      font-size: 1.55rem;
      line-height: 1;
      color: var(--accent);
    }
    h2 { font-size: 1.08rem; line-height: 1.1; }
    .subtle { color: var(--muted); font-size: 0.8rem; line-height: 1.35; }
    .stat-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 0.7rem;
    }
    .stat, .card {
      padding: 0.6rem;
      border-radius: 0.8rem;
      background: var(--surface);
      border: 1px solid rgba(255, 255, 255, 0.06);
    }
    .stat strong {
      display: block;
      color: var(--accent);
      font-size: 1.1rem;
    }
    .label { color: var(--muted); font-size: 0.8rem; }
    .search-wrap { display: grid; gap: 0.45rem; }
    input[type="search"] {
      width: 100%;
      border: 1px solid rgba(255, 255, 255, 0.08);
      background: rgba(0, 0, 0, 0.28);
      color: var(--text);
      border-radius: 0.85rem;
      padding: 0.8rem 0.9rem;
      outline: none;
    }
    input[type="search"]:focus {
      border-color: rgba(237, 203, 128, 0.42);
      box-shadow: 0 0 0 4px rgba(237, 203, 128, 0.08);
    }
    select {
      width: 100%;
      border: 1px solid rgba(255, 255, 255, 0.08);
      background: rgba(0, 0, 0, 0.28);
      color: var(--text);
      border-radius: 0.85rem;
      padding: 0.8rem 0.9rem;
      outline: none;
      font: inherit;
    }
    select:focus {
      border-color: rgba(237, 203, 128, 0.42);
      box-shadow: 0 0 0 4px rgba(237, 203, 128, 0.08);
    }
    select option {
      background: #1a1f2e;
      color: var(--text);
    }
    .controls, .toggle-grid {
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
    }
    .toggle-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 0.5rem;
    }
    button, .button-link {
      border: 0;
      border-radius: 999px;
      padding: 0.58rem 0.92rem;
      background: linear-gradient(135deg, rgba(237, 203, 128, 0.32), rgba(255, 159, 90, 0.28));
      color: var(--text);
      cursor: pointer;
      text-decoration: none;
      font: inherit;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.08);
    }
    button:hover, .button-link:hover { filter: brightness(1.08); }
    label.toggle {
      display: inline-flex;
      align-items: center;
      gap: 0.45rem;
      padding: 0.55rem 0.7rem;
      border-radius: 0.85rem;
      background: rgba(255, 255, 255, 0.03);
      color: var(--muted);
      font-size: 0.84rem;
      border: 1px solid rgba(255, 255, 255, 0.05);
    }
    label.toggle input { accent-color: var(--accent); }
    .legend {
      display: grid;
      gap: 0.45rem;
      max-height: 15rem;
      overflow: auto;
      padding-right: 0.2rem;
    }
    .legend-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 0.55rem;
      align-items: center;
      padding: 0.48rem 0.55rem;
      border-radius: 0.8rem;
      background: rgba(255, 255, 255, 0.03);
    }
    .legend-row.active {
      outline: 1px solid rgba(237, 203, 128, 0.36);
      background: rgba(237, 203, 128, 0.08);
    }
    .legend-main {
      border: 0;
      padding: 0;
      background: transparent;
      text-align: left;
      color: var(--text);
      display: inline-flex;
      align-items: center;
      gap: 0.55rem;
      justify-content: flex-start;
    }
    .legend-actions {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
    }
    .legend-toggle {
      padding: 0.28rem 0.62rem;
      font-size: 0.76rem;
      background: rgba(255, 255, 255, 0.05);
    }
    .swatch {
      width: 0.85rem;
      height: 0.85rem;
      border-radius: 999px;
      display: inline-block;
      box-shadow: 0 0 12px currentColor;
    }
    .mono {
      font-family: "SFMono-Regular", "Menlo", monospace;
      font-size: 0.82rem;
    }
    .chips {
      display: flex;
      flex-wrap: wrap;
      gap: 0.42rem;
    }
    .chip {
      padding: 0.26rem 0.55rem;
      border-radius: 999px;
      background: rgba(237, 203, 128, 0.12);
      font-size: 0.77rem;
    }
    .list {
      list-style: none;
      margin: 0;
      padding: 0;
      display: grid;
      gap: 0.45rem;
    }
    .list li {
      padding: 0.4rem 0.5rem;
      border-radius: 0.7rem;
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid rgba(255, 255, 255, 0.04);
      cursor: pointer;
      font-size: 0.78rem;
    }
    .list li.empty {
      cursor: default;
      color: var(--muted);
    }
    .list strong { display: block; line-height: 1.3; }
    .detail-scroll {
      overflow: auto;
      padding-right: 0.2rem;
      display: grid;
      gap: 0.55rem;
    }
    .preview {
      color: #f3ead9;
    }
    .preview > :first-child { margin-top: 0; }
    .preview > :last-child { margin-bottom: 0; }
    .preview h1,
    .preview h2,
    .preview h3,
    .preview h4 {
      margin: 0 0 0.5rem;
      font-family: "Baskerville", "Iowan Old Style", serif;
      line-height: 1.05;
      color: #fff0c9;
    }
    .preview h1 { font-size: 1.2rem; }
    .preview h2 { font-size: 1rem; }
    .preview h3 { font-size: 0.92rem; }
    .preview h4 { font-size: 0.86rem; }
    .preview p,
    .preview ul,
    .preview ol,
    .preview blockquote,
    .preview pre,
    .preview table,
    .preview hr {
      margin: 0 0 0.5rem;
    }
    .preview p,
    .preview li {
      line-height: 1.45;
      color: #f0e5d0;
      font-size: 0.85rem;
    }
    .preview ul,
    .preview ol {
      padding-left: 1.1rem;
    }
    .preview li + li {
      margin-top: 0.15rem;
    }
    .preview strong {
      color: #fff7e1;
      font-weight: 700;
    }
    .preview em {
      color: #ffe7b7;
    }
    .preview s {
      color: #bcae9b;
    }
    .preview blockquote {
      padding: 0.75rem 0.9rem;
      border-left: 3px solid rgba(237, 203, 128, 0.45);
      border-radius: 0.85rem;
      background: linear-gradient(135deg, rgba(237, 203, 128, 0.08), rgba(255, 255, 255, 0.03));
      color: #f7ecd8;
    }
    .preview code {
      font-family: "SFMono-Regular", "Menlo", monospace;
      font-size: 0.82rem;
      color: #ffe5ab;
      background: rgba(255, 255, 255, 0.07);
      padding: 0.12rem 0.36rem;
      border-radius: 0.45rem;
    }
    .preview pre {
      overflow: auto;
      padding: 0.9rem 1rem;
      border-radius: 0.95rem;
      border: 1px solid rgba(146, 183, 255, 0.18);
      background:
        linear-gradient(180deg, rgba(14, 18, 27, 0.96), rgba(8, 11, 18, 0.92)),
        radial-gradient(circle at top right, rgba(110, 180, 255, 0.12), transparent 45%);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
    }
    .preview pre code {
      display: block;
      padding: 0;
      background: transparent;
      color: #d4e6ff;
      line-height: 1.6;
    }
    .preview table {
      width: 100%;
      border-collapse: collapse;
      border-spacing: 0;
      border: 1px solid rgba(237, 203, 128, 0.14);
      border-radius: 0.95rem;
      overflow: hidden;
      background: rgba(255, 255, 255, 0.03);
    }
    .preview th,
    .preview td {
      padding: 0.55rem 0.65rem;
      text-align: left;
      vertical-align: top;
      border-bottom: 1px solid rgba(255, 255, 255, 0.07);
    }
    .preview th {
      color: #fff7de;
      font-weight: 700;
      background: rgba(237, 203, 128, 0.08);
    }
    .preview tr:last-child td {
      border-bottom: 0;
    }
    .preview a {
      color: #a8d3ff;
      text-decoration: none;
      border-bottom: 1px solid rgba(168, 211, 255, 0.35);
    }
    .preview a:hover {
      color: #d5ecff;
      border-bottom-color: rgba(213, 236, 255, 0.72);
    }
    .preview hr {
      border: 0;
      border-top: 1px solid rgba(255, 255, 255, 0.1);
    }
    .preview .wiki-link {
      color: var(--accent);
      font-family: "SFMono-Regular", "Menlo", monospace;
      font-size: 0.84rem;
    }
    .detail-meta {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.7rem;
      flex-wrap: wrap;
    }
    .stage-toolbar {
      position: absolute;
      top: 0.9rem;
      left: 0.9rem;
      right: 0.9rem;
      z-index: 2;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      padding: 0.75rem 0.9rem;
      border-radius: 999px;
      background: rgba(8, 10, 16, 0.8);
      border: 1px solid rgba(255, 255, 255, 0.09);
      backdrop-filter: blur(12px);
    }
    .stage-toolbar .keys {
      display: inline-flex;
      flex-wrap: wrap;
      gap: 0.75rem;
      color: var(--muted);
      font-size: 0.8rem;
    }
    .stage-toolbar .status { color: var(--accent); font-size: 0.82rem; }
    #help-overlay {
      position: absolute;
      right: 1rem;
      top: 4.7rem;
      width: min(22rem, calc(100% - 2rem));
      z-index: 3;
      background: rgba(10, 12, 18, 0.9);
      border: 1px solid rgba(237, 203, 128, 0.18);
      border-radius: 1rem;
      padding: 1rem;
      box-shadow: var(--shadow);
      backdrop-filter: blur(14px);
    }
    #help-overlay[hidden] { display: none; }
    #help-overlay ul {
      list-style: none;
      margin: 0;
      padding: 0;
      display: grid;
      gap: 0.5rem;
      color: var(--muted);
      font-size: 0.88rem;
    }
    #help-overlay code {
      color: var(--accent);
      font-family: "SFMono-Regular", "Menlo", monospace;
    }
    @media (max-width: 1040px) {
      body { overflow: auto; }
      .app {
        grid-template-columns: 1fr;
        grid-template-rows: auto minmax(26rem, 52vh) auto;
        height: auto;
        min-height: 100vh;
      }
      .canvas-panel { min-height: 26rem; }
      .stage-toolbar {
        border-radius: 1rem;
        align-items: flex-start;
        flex-direction: column;
      }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside class="panel sidebar">
      <div>
        <div class="eyebrow">atlas visual graph</div>
        <h1>Atlas Constellation 3D</h1>
        <p class="subtle">Deterministic clusters, semantic wires, and camera-state links you can share.</p>
      </div>

      <div class="stat-grid">
        <div class="stat"><strong id="node-count"></strong><span class="label">nodes</span></div>
        <div class="stat"><strong id="edge-count"></strong><span class="label">edges</span></div>
        <div class="stat"><strong id="type-count"></strong><span class="label">types</span></div>
        <div class="stat"><strong id="match-count"></strong><span class="label">matches</span></div>
      </div>

      <div class="search-wrap">
        <label class="eyebrow" for="search">Search</label>
        <input id="search" type="search" placeholder="project, person, tag, note title">
      </div>

      <div class="search-wrap">
        <label class="eyebrow" for="folder-filter">Folder</label>
        <select id="folder-filter">
          <option value="">all folders</option>
        </select>
      </div>

      <div class="controls">
        <button id="reset-layout" type="button">re-layout</button>
        <button id="fit-view" type="button">fit view</button>
        <button id="show-all-types" type="button">show all types</button>
      </div>

      <div class="controls">
        <button id="export-png" type="button">export PNG</button>
        <button id="export-json" type="button">export JSON</button>
        <button id="copy-link" type="button">copy link</button>
      </div>

      <div class="toggle-grid">
        <label class="toggle"><input id="demo-mode" type="checkbox" checked> demo view</label>
        <label class="toggle"><input id="show-labels" type="checkbox"> force labels</label>
        <label class="toggle"><input id="hide-names" type="checkbox"> anonymize labels</label>
        <label class="toggle"><input id="show-sessions" type="checkbox"> show sessions</label>
        <label class="toggle"><input id="show-wires" type="checkbox" checked> show semantic wires</label>
      </div>

      <div class="card">
        <div class="eyebrow">Type Legend</div>
        <div class="legend" id="legend"></div>
      </div>

      <div class="card">
        <div class="eyebrow">Type Browser</div>
        <div class="mono" id="type-browser-title">Click a type to browse its nodes.</div>
        <ul class="list" id="type-node-list"></ul>
      </div>

      <div class="card">
        <div class="eyebrow">Atlas Root</div>
        <div class="mono" id="atlas-root"></div>
      </div>
    </aside>

    <main class="panel canvas-panel">
      <div class="stage-toolbar">
        <div class="keys">
          <span>drag orbit</span>
          <span>wheel zoom</span>
          <span>arrows traverse</span>
          <span>j/k cycle</span>
          <span>/ search</span>
          <span>s sessions</span>
          <span>w wires</span>
          <span>h help</span>
        </div>
        <div class="status" id="selection-status">awaiting selection</div>
      </div>

      <div id="help-overlay" hidden>
        <div class="eyebrow">Keybindings</div>
        <ul>
          <li><code>/</code> focus search.</li>
          <li><code>Arrow keys</code> move to the nearest visible node in that direction.</li>
          <li><code>j</code> / <code>k</code> cycle visible nodes.</li>
          <li><code>s</code> hide or reveal session notes. Preference is remembered locally.</li>
          <li><code>w</code> toggle semantic wires while keeping wikilinks visible.</li>
          <li><code>r</code> reset camera, <code>0</code> clear hidden types, <code>x</code> anonymize labels.</li>
          <li><code>Enter</code> or <code>Space</code> re-center on the selected node.</li>
        </ul>
      </div>

      <div id="graph-canvas"></div>
      <div id="label-layer" aria-hidden="true"></div>
    </main>

    <aside class="panel detail">
      <div>
        <div class="eyebrow">Selected Note</div>
        <h2 id="detail-title">Nothing selected</h2>
        <p class="subtle" id="detail-subtitle">Click a node to inspect it.</p>
      </div>

      <div class="detail-scroll">
        <div class="card">
          <div class="detail-meta">
            <div class="eyebrow">Preview</div>
            <a class="button-link" id="open-note" href="#" target="_blank" rel="noopener noreferrer">jump to note</a>
          </div>
          <div class="preview" id="detail-preview">Select a node to show its note preview.</div>
        </div>

        <div class="card">
          <div class="eyebrow">Metadata</div>
          <div class="mono" id="detail-path">—</div>
          <div class="chips" id="detail-tags"></div>
        </div>

        <div class="card">
          <div class="eyebrow">Emotional Topology</div>
          <div class="mono" id="detail-emotional">No emotional topology on this node yet.</div>
          <div class="subtle" id="detail-emotional-note"></div>
        </div>

        <div class="card">
          <div class="eyebrow">Linked Context</div>
          <ul class="list" id="neighbor-list"></ul>
        </div>

        <div class="card">
          <div class="eyebrow">Incoming Wires</div>
          <ul class="list" id="incoming-wire-list"></ul>
        </div>

        <div class="card">
          <div class="eyebrow">Outgoing Wires</div>
          <ul class="list" id="outgoing-wire-list"></ul>
        </div>

        <div class="card">
          <div class="eyebrow">Recent Sessions</div>
          <ul class="list" id="session-mentions"></ul>
        </div>
      </div>
    </aside>
  </div>

  <script type="module">
    __THREE_VENDOR__

    const THREE = {
      AmbientLight,
      Box3,
      BufferAttribute,
      BufferGeometry,
      Color,
      DirectionalLight,
      FogExp2,
      IcosahedronGeometry,
      Line,
      LineBasicMaterial,
      Mesh,
      MeshStandardMaterial,
      PerspectiveCamera,
      Points,
      PointsMaterial,
      Raycaster,
      Scene,
      Sphere,
      Vector2,
      Vector3,
      WebGLRenderer,
    };

    (() => {
    const atlasGraphPayload = __PAYLOAD__;
    const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
    const predicateColors = {
      supports: '#68d39b',
      qualifies: '#d7c86e',
      contradicts: '#ff7c72',
      precedes: '#5aa7ff',
      follows: '#7cc0ff',
      part_of: '#8a9cff',
      depends_on: '#ffaf5c',
      grounds: '#7ed3c2',
      intensifies_with: '#d680ff',
      co_occurs_with: '#eabf7e',
      triggered_by: '#ff93b7',
      relates_to_goal: '#9ef061',
      relates_to_person: '#8ec1ff',
      intention_outcome: '#f5d16f',
      resistance_against: '#ff6a8c',
      'active-project': '#ffd36a',
      'core-infrastructure': '#7ec8ff',
      relates_to: '#c2c9d6',
    };
    const emotionalColors = {
      positive: '#67d98b',
      negative: '#f06a74',
      mixed: '#b988ff',
      neutral: '#a7b3c3',
    };
    const typeColors = Object.fromEntries(atlasGraphPayload.nodes.map((node) => [node.type, node.type_color || node.color]));
    const SESSION_STORAGE_KEY = 'atlas.graph.showSessions';
    const LABEL_STORAGE_KEY = 'atlas.graph.showLabels';
    const ANON_STORAGE_KEY = 'atlas.graph.hideNames';
    const WIRES_STORAGE_KEY = 'atlas.graph.showWires';
    const DEMO_MODE_KEY = 'atlas.graph.demoMode';

    const searchInput = document.getElementById('search');
    const folderFilterSelect = document.getElementById('folder-filter');
    const demoModeToggle = document.getElementById('demo-mode');
    const showLabelsToggle = document.getElementById('show-labels');
    const hideNamesToggle = document.getElementById('hide-names');
    const showSessionsToggle = document.getElementById('show-sessions');
    const showWiresToggle = document.getElementById('show-wires');
    const nodeCountEl = document.getElementById('node-count');
    const edgeCountEl = document.getElementById('edge-count');
    const typeCountEl = document.getElementById('type-count');
    const matchCountEl = document.getElementById('match-count');
    const legendEl = document.getElementById('legend');
    const typeBrowserTitleEl = document.getElementById('type-browser-title');
    const typeNodeListEl = document.getElementById('type-node-list');
    const atlasRootEl = document.getElementById('atlas-root');
    const selectionStatusEl = document.getElementById('selection-status');
    const detailTitleEl = document.getElementById('detail-title');
    const detailSubtitleEl = document.getElementById('detail-subtitle');
    const detailPreviewEl = document.getElementById('detail-preview');
    const detailPathEl = document.getElementById('detail-path');
    const detailTagsEl = document.getElementById('detail-tags');
    const detailEmotionalEl = document.getElementById('detail-emotional');
    const detailEmotionalNoteEl = document.getElementById('detail-emotional-note');
    const neighborListEl = document.getElementById('neighbor-list');
    const incomingWireListEl = document.getElementById('incoming-wire-list');
    const outgoingWireListEl = document.getElementById('outgoing-wire-list');
    const sessionMentionsEl = document.getElementById('session-mentions');
    const openNoteEl = document.getElementById('open-note');
    const canvasHost = document.getElementById('graph-canvas');
    const labelLayer = document.getElementById('label-layer');
    const helpOverlay = document.getElementById('help-overlay');

    nodeCountEl.textContent = String(atlasGraphPayload.node_count);
    edgeCountEl.textContent = String(atlasGraphPayload.edge_count);
    typeCountEl.textContent = String(Object.keys(atlasGraphPayload.type_counts).length);
    atlasRootEl.textContent = atlasGraphPayload.atlas_root;

    function storageBool(key, fallback) {
      const value = window.localStorage.getItem(key);
      if (value === null) {
        return fallback;
      }
      return value === '1';
    }

    function readHashState() {
      if (!location.hash.startsWith('#state=')) {
        return null;
      }
      try {
        return JSON.parse(atob(decodeURIComponent(location.hash.slice(7))));
      } catch (error) {
        console.warn('failed to decode graph state', error);
        return null;
      }
    }

    const state = {
      search: '',
      folderFilter: '',
      hiddenTypes: new Set(),
      browserType: null,
      showSessions: storageBool(SESSION_STORAGE_KEY, false),
      showLabels: storageBool(LABEL_STORAGE_KEY, false),
      hideNames: storageBool(ANON_STORAGE_KEY, false),
      showWires: storageBool(WIRES_STORAGE_KEY, true),
      demoMode: storageBool(DEMO_MODE_KEY, true), // Default to true for safe demo view
    };

    const initialHashState = readHashState();
    if (initialHashState) {
      state.search = typeof initialHashState.search === 'string' ? initialHashState.search : '';
      state.browserType = typeof initialHashState.browserType === 'string' ? initialHashState.browserType : null;
      state.showSessions = initialHashState.showSessions ?? state.showSessions;
      state.showLabels = initialHashState.showLabels ?? state.showLabels;
      state.hideNames = initialHashState.hideNames ?? state.hideNames;
      state.showWires = initialHashState.showWires ?? state.showWires;
      for (const typeName of initialHashState.hiddenTypes || []) {
        state.hiddenTypes.add(typeName);
      }
    }

    searchInput.value = state.search;
    demoModeToggle.checked = state.demoMode;
    showLabelsToggle.checked = state.showLabels;
    hideNamesToggle.checked = state.hideNames;
    showSessionsToggle.checked = state.showSessions;
    showWiresToggle.checked = state.showWires;

    function sortNodes(items) {
      return [...items].sort((a, b) => {
        if (a.type !== b.type) {
          return a.type.localeCompare(b.type);
        }
        if (b.degree !== a.degree) {
          return b.degree - a.degree;
        }
        return a.title.localeCompare(b.title);
      });
    }

    const nodes = atlasGraphPayload.nodes.map((node, index) => ({
      ...node,
      index,
      haystack: [node.id, node.title, node.type, ...(node.tags || [])].join(' ').toLowerCase(),
      position: new THREE.Vector3(),
      matched: false,
      visibleByToggle: true,
      typeOrdinal: 0,
      baseColor: new THREE.Color(node.color),
      displayColor: new THREE.Color(node.color).lerp(new THREE.Color('#fff4d4'), 0.18),
      glowColor: new THREE.Color(node.color).lerp(new THREE.Color('#ffc987'), 0.12),
      baseRadius: node.base_radius || (4.8 + Math.min(node.degree, 14) * 0.55),
      radius: 0,
      mesh: null,
      material: null,
      labelEl: document.createElement('div'),
    }));

    const typeOrdinals = new Map();
    for (const node of sortNodes(nodes)) {
      const current = (typeOrdinals.get(node.type) || 0) + 1;
      typeOrdinals.set(node.type, current);
      node.typeOrdinal = current;
      node.labelEl.className = 'node-label';
      labelLayer.appendChild(node.labelEl);
    }

    const nodeById = new Map(nodes.map((node) => [node.id, node]));
    const typeNames = Object.keys(atlasGraphPayload.type_counts).sort(
      (a, b) => atlasGraphPayload.type_counts[b] - atlasGraphPayload.type_counts[a]
    );
    const edges = atlasGraphPayload.edges
      .map((edge) => ({
        ...edge,
        source: nodeById.get(edge.source),
        target: nodeById.get(edge.target),
        isWire: edge.kind === 'wire',
        baseColor: new THREE.Color(
          edge.kind === 'wire'
            ? emotionalColors[edge.emotional_valence] || predicateColors[edge.predicate] || '#f0b35f'
            : '#6e7b96'
        ),
        line: null,
        material: null,
      }))
      .filter((edge) => edge.source && edge.target);

    const neighbors = new Map(nodes.map((node) => [node.id, new Set()]));
    const outgoingWires = new Map(nodes.map((node) => [node.id, []]));
    const incomingWires = new Map(nodes.map((node) => [node.id, []]));
    for (const edge of edges) {
      neighbors.get(edge.source.id).add(edge.target.id);
      neighbors.get(edge.target.id).add(edge.source.id);
      if (edge.isWire) {
        outgoingWires.get(edge.source.id).push(edge);
        incomingWires.get(edge.target.id).push(edge);
      }
    }

    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      preserveDrawingBuffer: true,
      powerPreference: 'high-performance',
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    canvasHost.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x07090f, 0.00074);

    const camera = new THREE.PerspectiveCamera(48, 1, 0.1, 5000);
    camera.position.set(0, 120, 520);
    const cameraTarget = new THREE.Vector3(0, 0, 0);
    const cameraState = {
      target: cameraTarget.clone(),
      azimuth: 0,
      polar: 1.22,
      distance: 534,
    };
    const WORLD_UP = new THREE.Vector3(0, 1, 0);

    function clamp(value, min, max) {
      return Math.min(max, Math.max(min, value));
    }

    function orbitalPosition(
      target,
      distance,
      azimuth = cameraState.azimuth,
      polar = cameraState.polar,
    ) {
      const sinPolar = Math.sin(polar);
      return new THREE.Vector3(
        target.x + distance * sinPolar * Math.sin(azimuth),
        target.y + distance * Math.cos(polar),
        target.z + distance * sinPolar * Math.cos(azimuth),
      );
    }

    function syncCameraStateFromActual() {
      const offset = camera.position.clone().sub(cameraTarget);
      const distance = Math.max(0.001, offset.length());
      cameraState.distance = clamp(distance, 55, 2400);
      cameraState.azimuth = Math.atan2(offset.x, offset.z);
      cameraState.polar = clamp(Math.acos(offset.y / distance), 0.08, Math.PI - 0.08);
      cameraState.target.copy(cameraTarget);
    }

    function desiredCameraPosition() {
      return orbitalPosition(cameraState.target, cameraState.distance);
    }

    function applyCameraState(alpha = 0.18) {
      cameraTarget.lerp(cameraState.target, alpha);
      camera.position.lerp(desiredCameraPosition(), alpha);
      camera.lookAt(cameraTarget);
    }

    syncCameraStateFromActual();

    const ambient = new THREE.AmbientLight(0xfaf0dd, 1.02);
    scene.add(ambient);
    const rim = new THREE.DirectionalLight(0x7aa8ff, 0.72);
    rim.position.set(240, 180, 220);
    scene.add(rim);
    const warm = new THREE.DirectionalLight(0xffd19d, 0.46);
    warm.position.set(-180, 120, -140);
    scene.add(warm);

    const starsGeometry = new THREE.BufferGeometry();
    const starPositions = new Float32Array(900 * 3);
    for (let index = 0; index < 900; index += 1) {
      const radius = 900 + Math.random() * 1200;
      const phi = Math.random() * Math.PI * 2;
      const costheta = Math.random() * 2 - 1;
      const sintheta = Math.sqrt(1 - costheta * costheta);
      starPositions[index * 3] = Math.cos(phi) * sintheta * radius;
      starPositions[index * 3 + 1] = costheta * radius;
      starPositions[index * 3 + 2] = Math.sin(phi) * sintheta * radius;
    }
    starsGeometry.setAttribute('position', new THREE.BufferAttribute(starPositions, 3));
    const stars = new THREE.Points(
      starsGeometry,
      new THREE.PointsMaterial({
        color: 0xb7c9ff,
        transparent: true,
        opacity: 0.34,
        size: 3.7,
        sizeAttenuation: true,
      })
    );
    scene.add(stars);

    const sphereGeometry = new THREE.IcosahedronGeometry(1, 3);
    for (const node of nodes) {
      const material = new THREE.MeshStandardMaterial({
        color: node.displayColor.clone(),
        emissive: node.glowColor.clone().multiplyScalar(0.18),
        roughness: 0.26,
        metalness: 0.12,
        transparent: true,
        opacity: 0.95,
      });
      const mesh = new THREE.Mesh(sphereGeometry, material);
      mesh.userData.node = node;
      mesh.scale.setScalar(node.radius);
      scene.add(mesh);
      node.mesh = mesh;
      node.material = material;
    }

    for (const edge of edges) {
      const geometry = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(),
        new THREE.Vector3(),
      ]);
      const material = new THREE.LineBasicMaterial({
        color: edge.baseColor,
        transparent: true,
        opacity: edge.isWire ? 0.62 : 0.2,
      });
      const line = new THREE.Line(geometry, material);
      line.userData.edge = edge;
      scene.add(line);
      edge.line = line;
      edge.material = material;
    }

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    let selectedNode = null;
    let cameraGoal = null;
    let homeTarget = new THREE.Vector3();
    let homePosition = new THREE.Vector3(0, 120, 520);
    let pointerDown = null;
    let moved = false;
    let dragMode = null;

    function fileHref(path) {
      if (!path) {
        return '#';
      }
      return 'file://' + encodeURI(path);
    }

    function displayNodeName(node) {
      if (!node) {
        return 'Nothing selected';
      }
      return state.hideNames ? `${node.type} ${node.typeOrdinal}` : node.title;
    }

    function detailTypeLabel(node) {
      const bits = [node.type, `degree ${node.degree}`];
      if (node.status) {
        bits.push(node.status);
      }
      if (node.emotional_valence) {
        bits.push(`valence ${node.emotional_valence}`);
      }
      if (node.avoidance_risk) {
        bits.push(`avoidance ${node.avoidance_risk}`);
      }
      if (node.current_state) {
        bits.push(`state ${node.current_state}`);
      }
      if (node.raw_type && node.raw_type !== node.type) {
        bits.push(`raw ${node.raw_type}`);
      }
      return bits.join(' · ');
    }

    function edgeMetaLine(edge) {
      const bits = [];
      if (edge.relationship && edge.relationship !== edge.predicate) {
        bits.push(edge.relationship);
      }
      if (edge.emotional_valence) {
        bits.push(`valence ${edge.emotional_valence}`);
      }
      if (edge.energy_impact) {
        bits.push(`energy ${edge.energy_impact}`);
      }
      if (edge.avoidance_risk) {
        bits.push(`avoidance ${edge.avoidance_risk}`);
      }
      if (edge.growth_edge) {
        bits.push('growth-edge');
      }
      if (edge.current_state) {
        bits.push(`state ${edge.current_state}`);
      }
      return bits.join(' · ') || 'wire';
    }

    function nodeEmotionalSummary(node) {
      const bits = [];
      if (node.emotional_valence) {
        bits.push(`valence ${node.emotional_valence}`);
      }
      if (node.energy_impact) {
        bits.push(`energy ${node.energy_impact}`);
      }
      if (node.avoidance_risk) {
        bits.push(`avoidance ${node.avoidance_risk}`);
      }
      if (node.growth_edge) {
        bits.push('growth-edge');
      }
      if (node.current_state) {
        bits.push(`state ${node.current_state}`);
      }
      if (node.since) {
        bits.push(`since ${node.since}`);
      }
      if (node.until) {
        bits.push(`until ${node.until}`);
      }
      return bits;
    }

    function activeNodes() {
      return nodes.filter((node) => {
        if (state.hiddenTypes.has(node.type)) {
          return false;
        }
        if (!state.showSessions && node.is_session) {
          return false;
        }
        return true;
      });
    }

    function fitNodesForType(typeName) {
      if (!typeName || state.hiddenTypes.has(typeName)) {
        return [];
      }
      return sortNodes(
        nodes.filter((node) => node.visibleByToggle && node.type === typeName)
      );
    }

    function matchedNodes() {
      return sortNodes(nodes.filter((node) => node.visibleByToggle && node.matched));
    }

    function selectedNeighborhood(node) {
      if (!node || !node.visibleByToggle) {
        return [];
      }
      const linked = Array.from(neighbors.get(node.id) || [])
        .map((id) => nodeById.get(id))
        .filter((candidate) => candidate && candidate.visibleByToggle);
      return sortNodes([node, ...linked]);
    }

    function fibonacciVector(index, count) {
      if (count <= 1) {
        return new THREE.Vector3(0, 0, 0);
      }
      const offset = 2 / count;
      const y = index * offset - 1 + offset / 2;
      const radius = Math.sqrt(Math.max(0, 1 - y * y));
      const phi = index * GOLDEN_ANGLE;
      return new THREE.Vector3(Math.cos(phi) * radius, y, Math.sin(phi) * radius);
    }

    function layoutProfile(activeTypes) {
      const visibleCount = Math.max(activeNodes().length, 1);
      const typeCount = Math.max(activeTypes.length, 1);
      const avgBucket = visibleCount / typeCount;
      const nodeScale = clamp(26 / Math.sqrt(visibleCount), 0.92, 1.9);
      const anchorRadius = clamp(
        64 + typeCount * 4.8 + Math.sqrt(visibleCount) * 3.25 + avgBucket * 4.4,
        92,
        390,
      );
      const clusterBase = 14 + nodeScale * 10 + avgBucket * 1.15;
      const clusterStep = 9 + nodeScale * 6 + Math.min(avgBucket, 16) * 0.8;
      const verticalCompression = clamp(0.55 + avgBucket * 0.035, 0.56, 0.82);
      const depthCompression = clamp(0.74 + avgBucket * 0.015, 0.74, 0.92);
      return {
        nodeScale,
        anchorRadius,
        clusterBase,
        clusterStep,
        verticalCompression,
        depthCompression,
      };
    }

    function updateHomeCamera() {
      const visible = activeNodes();
      if (!visible.length) {
        homeTarget = new THREE.Vector3();
        homePosition = new THREE.Vector3(0, 120, 520);
        return;
      }
      const frame = cameraFrameForNodes(
        visible,
        {
          padding: clamp(1.22 + visible.length / 1800, 1.22, 1.48),
          minDistance: 220,
          lift: 0.16,
        }
      );
      if (!frame) {
        homeTarget = new THREE.Vector3();
        homePosition = new THREE.Vector3(0, 120, 520);
        return;
      }
      homeTarget = frame.target;
      homePosition = frame.position;
    }

    function layoutNodes() {
      const activeTypes = typeNames.filter((typeName) =>
        nodes.some((node) =>
          node.type === typeName
          && !state.hiddenTypes.has(node.type)
            && (state.showSessions || !node.is_session)
        )
      );
      const profile = layoutProfile(activeTypes);
      const anchors = new Map();
      activeTypes.forEach((typeName, index) => {
        anchors.set(
          typeName,
          fibonacciVector(index, activeTypes.length).multiplyScalar(profile.anchorRadius)
        );
      });

      for (const typeName of typeNames) {
        const bucket = sortNodes(
          nodes.filter((node) =>
            node.type === typeName
            && !state.hiddenTypes.has(node.type)
            && (state.showSessions || !node.is_session)
          )
        );
        const anchor = anchors.get(typeName) || new THREE.Vector3();
        bucket.forEach((node, index) => {
          const local = index === 0
            ? new THREE.Vector3()
            : fibonacciVector(index - 1, Math.max(bucket.length - 1, 1)).multiplyScalar(
                profile.clusterBase + Math.sqrt(index) * profile.clusterStep
              );
          local.y *= profile.verticalCompression;
          local.z *= profile.depthCompression;
          node.radius = node.baseRadius * profile.nodeScale;
          node.position.copy(anchor).add(local);
          node.mesh.position.copy(node.position);
          node.mesh.scale.setScalar(node.radius);
        });
      }

      for (const edge of edges) {
        const positions = edge.line.geometry.attributes.position.array;
        positions[0] = edge.source.position.x;
        positions[1] = edge.source.position.y;
        positions[2] = edge.source.position.z;
        positions[3] = edge.target.position.x;
        positions[4] = edge.target.position.y;
        positions[5] = edge.target.position.z;
        edge.line.geometry.attributes.position.needsUpdate = true;
        edge.line.geometry.computeBoundingSphere();
      }
      updateHomeCamera();
    }

    function saveToggles() {
      window.localStorage.setItem(SESSION_STORAGE_KEY, state.showSessions ? '1' : '0');
      window.localStorage.setItem(LABEL_STORAGE_KEY, state.showLabels ? '1' : '0');
      window.localStorage.setItem(ANON_STORAGE_KEY, state.hideNames ? '1' : '0');
      window.localStorage.setItem(WIRES_STORAGE_KEY, state.showWires ? '1' : '0');
      window.localStorage.setItem(DEMO_MODE_KEY, state.demoMode ? '1' : '0');
    }

    function writeHashState() {
      const payload = {
        search: state.search,
        hiddenTypes: [...state.hiddenTypes],
        browserType: state.browserType,
        showSessions: state.showSessions,
        showLabels: state.showLabels,
        hideNames: state.hideNames,
        showWires: state.showWires,
        selected: selectedNode ? selectedNode.id : null,
        cameraPosition: camera.position.toArray().map((value) => Number(value.toFixed(3))),
        cameraTarget: cameraTarget.toArray().map((value) => Number(value.toFixed(3))),
      };
      history.replaceState(
        null,
        '',
        `${location.pathname}${location.search}#state=${encodeURIComponent(btoa(JSON.stringify(payload)))}`
      );
    }

    function queueCamera(position, target) {
      cameraGoal = { position: position.clone(), target: target.clone() };
      writeHashState();
    }

    function cameraFrameForNodes(
      fitNodes,
      {
        padding = 1.28,
        minDistance = 160,
        lift = 0.12,
        targetBias = null,
      } = {},
    ) {
      const candidates = fitNodes.filter((node) => node && node.visibleByToggle);
      if (!candidates.length) {
        return null;
      }
      const box = new THREE.Box3();
      for (const node of candidates) {
        const pad = Math.max(node.radius * 1.5, 8);
        box.expandByPoint(node.position.clone().add(new THREE.Vector3(pad, pad, pad)));
        box.expandByPoint(node.position.clone().add(new THREE.Vector3(-pad, -pad, -pad)));
      }
      const sphere = box.getBoundingSphere(new THREE.Sphere());
      const radius = Math.max(sphere.radius, 18);
      const verticalFov = camera.fov * Math.PI / 180;
      const horizontalFov = 2 * Math.atan(Math.tan(verticalFov / 2) * Math.max(camera.aspect, 0.6));
      const fitDistance = Math.max(
        radius / Math.tan(verticalFov / 2),
        radius / Math.tan(horizontalFov / 2),
      );
      const distance = clamp(
        Math.max(fitDistance * padding, radius * 2.32, minDistance),
        110,
        2800,
      );
      const target = sphere.center.clone();
      if (targetBias) {
        target.lerp(targetBias, 0.24);
      }
      target.y += radius * lift;
      return {
        position: orbitalPosition(target, distance),
        target,
      };
    }

    function resolveFitContext({ preferSelection = false } = {}) {
      const matches = matchedNodes();
      if (matches.length) {
        return { mode: 'search', nodes: matches };
      }
      const typed = fitNodesForType(state.browserType);
      if (typed.length) {
        return { mode: 'browser', nodes: typed };
      }
      if (preferSelection) {
        const neighborhood = selectedNeighborhood(selectedNode);
        if (neighborhood.length > 1) {
          return { mode: 'selection', nodes: neighborhood };
        }
      }
      return { mode: 'visible', nodes: sortNodes(activeNodes()) };
    }

    function smartFitCamera({ preferSelection = false } = {}) {
      const context = resolveFitContext({ preferSelection });
      const frame = cameraFrameForNodes(
        context.nodes,
        {
          padding:
            context.mode === 'selection'
              ? 1.5
              : context.mode === 'search'
                ? 1.38
                : context.mode === 'browser'
                  ? 1.26
                  : 1.24,
          minDistance: context.mode === 'selection' ? 130 : 180,
          lift: context.mode === 'selection' ? 0.08 : 0.14,
          targetBias: context.mode === 'selection' && selectedNode ? selectedNode.position : null,
        }
      );
      if (!frame) {
        resetCamera();
        return;
      }
      queueCamera(frame.position, frame.target);
    }

    function resetCamera() {
      queueCamera(homePosition, homeTarget);
    }

    function focusNode(node) {
      if (!node) {
        return;
      }
      const offset = camera.position.clone().sub(cameraTarget);
      if (offset.lengthSq() < 0.001) {
        offset.set(0, 100, 320);
      }
      queueCamera(node.position.clone().add(offset), node.position);
    }

    function navigationCandidates() {
      const visible = activeNodes();
      const matched = visible.filter((node) => node.matched);
      return matched.length ? sortNodes(matched) : sortNodes(visible);
    }

    function makeListItem(primary, secondary, onClick) {
      const item = document.createElement('li');
      item.innerHTML = `<strong>${primary}</strong><div class="mono subtle">${secondary}</div>`;
      if (onClick) {
        item.addEventListener('click', onClick);
      } else {
        item.classList.add('empty');
      }
      return item;
    }

    function escapeHtml(value) {
      return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
    }

    function escapeAttribute(value) {
      return escapeHtml(value).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function sanitizeHref(value) {
      const trimmed = String(value || '').trim();
      if (/^(https?:|mailto:|file:|#)/i.test(trimmed)) {
        return trimmed;
      }
      return '#';
    }

    function renderInlineMarkdown(text) {
      const codeSpans = [];
      const wikiLinks = [];
      const markdownLinks = [];
      let html = String(text || '').replace(/`([^`\\n]+)`/g, (_, code) => {
        const token = `@@CODE${codeSpans.length}@@`;
        codeSpans.push(escapeHtml(code));
        return token;
      });
      html = html.replace(/\\[\\[([^\\[\\]]+)\\]\\]/g, (_, label) => {
        const token = `@@WIKI${wikiLinks.length}@@`;
        wikiLinks.push(escapeHtml(label));
        return token;
      });
      html = html.replace(/\\[([^\\]]+)\\]\\(([^)]+)\\)/g, (_, label, href) => {
        const token = `@@LINK${markdownLinks.length}@@`;
        markdownLinks.push({
          label: escapeHtml(label),
          href: escapeAttribute(sanitizeHref(href)),
        });
        return token;
      });
      html = escapeHtml(html);
      html = html.replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>');
      html = html.replace(/~~([^~]+)~~/g, '<s>$1</s>');
      html = html.replace(/\\*([^*\\n]+)\\*/g, '<em>$1</em>');
      html = html.replace(/_([^_\\n]+)_/g, '<em>$1</em>');
      html = html.replace(/@@WIKI(\\d+)@@/g, (_, index) => `<span class="wiki-link">[[${wikiLinks[Number(index)]}]]</span>`);
      html = html.replace(/@@LINK(\\d+)@@/g, (_, index) => {
        const link = markdownLinks[Number(index)];
        return `<a href="${link.href}" target="_blank" rel="noopener noreferrer">${link.label}</a>`;
      });
      html = html.replace(/@@CODE(\\d+)@@/g, (_, index) => `<code>${codeSpans[Number(index)]}</code>`);
      return html;
    }

    function renderPreviewMarkdown(source) {
      const text = String(source || '').replace(/\\r\\n/g, '\\n').trim();
      if (!text) {
        return '<p>No preview available.</p>';
      }

      const lines = text.split('\\n');
      const blocks = [];
      let paragraph = [];
      let listType = null;
      let listItems = [];
      let quoteLines = [];

      function flushParagraph() {
        if (!paragraph.length) {
          return;
        }
        blocks.push(
          `<p>${renderInlineMarkdown(paragraph.join('\\n')).replace(/\\n+/g, '<br>')}</p>`
        );
        paragraph = [];
      }

      function flushList() {
        if (!listItems.length || !listType) {
          listType = null;
          listItems = [];
          return;
        }
        const items = listItems
          .map((item) => `<li>${renderInlineMarkdown(item)}</li>`)
          .join('');
        blocks.push(`<${listType}>${items}</${listType}>`);
        listType = null;
        listItems = [];
      }

      function flushQuote() {
        if (!quoteLines.length) {
          return;
        }
        const rendered = quoteLines
          .map((line) => `<p>${renderInlineMarkdown(line)}</p>`)
          .join('');
        blocks.push(`<blockquote>${rendered}</blockquote>`);
        quoteLines = [];
      }

      function splitMarkdownTableRow(line) {
        return line
          .trim()
          .replace(/^\\|/, '')
          .replace(/\\|$/, '')
          .split('|')
          .map((cell) => cell.trim());
      }

      function isMarkdownTableDivider(line) {
        return /^\\|?\\s*:?-{3,}:?(\\s*\\|\\s*:?-{3,}:?)*\\|?$/.test(line.trim());
      }

      function renderMarkdownTable(headers, rows) {
        const headHtml = headers
          .map((cell) => `<th>${renderInlineMarkdown(cell)}</th>`)
          .join('');
        const bodyHtml = rows
          .map((row) => {
            const cells = headers.map((_, index) => row[index] || '');
            return `<tr>${cells.map((cell) => `<td>${renderInlineMarkdown(cell)}</td>`).join('')}</tr>`;
          })
          .join('');
        return `<table><thead><tr>${headHtml}</tr></thead><tbody>${bodyHtml}</tbody></table>`;
      }

      for (let index = 0; index < lines.length; index += 1) {
        const line = lines[index];
        const trimmed = line.trim();

        if (/^```/.test(trimmed)) {
          flushParagraph();
          flushList();
          flushQuote();
          const lang = trimmed.slice(3).trim();
          const code = [];
          while (index + 1 < lines.length && !/^```/.test(lines[index + 1].trim())) {
            index += 1;
            code.push(lines[index]);
          }
          if (index + 1 < lines.length && /^```/.test(lines[index + 1].trim())) {
            index += 1;
          }
          blocks.push(
            `<pre><code${lang ? ` data-lang="${escapeAttribute(lang)}"` : ''}>${escapeHtml(code.join('\\n'))}</code></pre>`
          );
          continue;
        }

        if (line.includes('|') && index + 1 < lines.length && isMarkdownTableDivider(lines[index + 1])) {
          flushParagraph();
          flushList();
          flushQuote();
          const headers = splitMarkdownTableRow(line);
          const rows = [];
          index += 1;
          while (index + 1 < lines.length) {
            const next = lines[index + 1];
            if (!next.trim() || !next.includes('|')) {
              break;
            }
            index += 1;
            rows.push(splitMarkdownTableRow(next));
          }
          blocks.push(renderMarkdownTable(headers, rows));
          continue;
        }

        const headingMatch = trimmed.match(/^(#{1,4})\\s+(.*)$/);
        if (headingMatch) {
          flushParagraph();
          flushList();
          flushQuote();
          const level = headingMatch[1].length;
          blocks.push(`<h${level}>${renderInlineMarkdown(headingMatch[2])}</h${level}>`);
          continue;
        }

        if (/^(-{3,}|\\*{3,}|_{3,})$/.test(trimmed)) {
          flushParagraph();
          flushList();
          flushQuote();
          blocks.push('<hr>');
          continue;
        }

        const quoteMatch = line.match(/^>\\s?(.*)$/);
        if (quoteMatch) {
          flushParagraph();
          flushList();
          quoteLines.push(quoteMatch[1]);
          continue;
        }
        flushQuote();

        const unorderedMatch = line.match(/^[-*+]\\s+(.*)$/);
        const orderedMatch = line.match(/^\\d+\\.\\s+(.*)$/);
        if (unorderedMatch || orderedMatch) {
          flushParagraph();
          const nextType = unorderedMatch ? 'ul' : 'ol';
          if (listType && listType !== nextType) {
            flushList();
          }
          listType = nextType;
          listItems.push((unorderedMatch || orderedMatch)[1]);
          continue;
        }
        flushList();

        if (!trimmed) {
          flushParagraph();
          continue;
        }
        paragraph.push(line);
      }

      flushParagraph();
      flushList();
      flushQuote();
      return blocks.join('');
    }

    function renderList(element, items, emptyText) {
      element.innerHTML = '';
      if (!items.length) {
        element.appendChild(makeListItem(emptyText, '', null));
        return;
      }
      items.forEach((item) => element.appendChild(item));
    }

    function updateDetail(node) {
      if (!node) {
        detailTitleEl.textContent = 'Nothing selected';
        detailSubtitleEl.textContent = 'Click a node to inspect it.';
        detailPreviewEl.innerHTML = renderPreviewMarkdown('Select a node to show its note preview.');
        detailPathEl.textContent = '—';
        openNoteEl.href = '#';
        detailTagsEl.innerHTML = '';
        detailEmotionalEl.textContent = 'No emotional topology on this node yet.';
        detailEmotionalNoteEl.textContent = '';
        selectionStatusEl.textContent = 'awaiting selection';
        renderList(neighborListEl, [], 'No linked context.');
        renderList(incomingWireListEl, [], 'No incoming wires.');
        renderList(outgoingWireListEl, [], 'No outgoing wires.');
        renderList(sessionMentionsEl, [], 'No recent session mentions.');
        return;
      }

      detailTitleEl.textContent = displayNodeName(node);
      detailSubtitleEl.textContent = detailTypeLabel(node);
      detailPreviewEl.innerHTML = renderPreviewMarkdown(node.preview || 'No preview available.');
      detailPathEl.textContent = node.path || '—';
      openNoteEl.href = fileHref(node.path);
      selectionStatusEl.textContent = `${displayNodeName(node)} · ${node.type}`;

      detailTagsEl.innerHTML = '';
      for (const value of [
        node.type,
        node.emotional_valence,
        node.energy_impact,
        node.avoidance_risk ? `avoidance:${node.avoidance_risk}` : null,
        node.growth_edge ? 'growth-edge' : null,
        node.current_state ? `state:${node.current_state}` : null,
        ...(node.tags || []).slice(0, 8),
      ]) {
        if (!value) {
          continue;
        }
        const chip = document.createElement('span');
        chip.className = 'chip';
        chip.textContent = value;
        detailTagsEl.appendChild(chip);
      }
      const emotionalBits = nodeEmotionalSummary(node);
      detailEmotionalEl.textContent = emotionalBits.length
        ? emotionalBits.join(' · ')
        : 'No emotional topology on this node yet.';
      detailEmotionalNoteEl.textContent = node.valence_note || '';

      const linked = Array.from(neighbors.get(node.id) || [])
        .map((id) => nodeById.get(id))
        .filter((candidate) => candidate && candidate.visibleByToggle)
        .sort((a, b) => a.title.localeCompare(b.title))
        .slice(0, 18)
        .map((candidate) =>
          makeListItem(
            displayNodeName(candidate),
            `${candidate.id} · ${detailTypeLabel(candidate)}`,
            () => selectNode(candidate, true)
          )
        );
      renderList(neighborListEl, linked, 'No linked context.');

      const incoming = [...(incomingWires.get(node.id) || [])]
        .sort((a, b) => a.predicate.localeCompare(b.predicate) || a.source.title.localeCompare(b.source.title))
        .slice(0, 16)
        .map((edge) =>
          makeListItem(
            `← ${edge.predicate} ← ${displayNodeName(edge.source)}`,
            `${edge.source.id} · ${edgeMetaLine(edge)}`,
            () => selectNode(edge.source, true)
          )
        );
      renderList(incomingWireListEl, incoming, 'No incoming wires.');

      const outgoing = [...(outgoingWires.get(node.id) || [])]
        .sort((a, b) => a.predicate.localeCompare(b.predicate) || a.target.title.localeCompare(b.target.title))
        .slice(0, 16)
        .map((edge) =>
          makeListItem(
            `→ ${edge.predicate} → ${displayNodeName(edge.target)}`,
            `${edge.target.id} · ${edgeMetaLine(edge)}`,
            () => selectNode(edge.target, true)
          )
        );
      renderList(outgoingWireListEl, outgoing, 'No outgoing wires.');

      const sessions = sortNodes(
        Array.from(neighbors.get(node.id) || [])
          .map((id) => nodeById.get(id))
          .filter((candidate) => candidate && candidate.is_session)
      )
        .slice(0, 10)
        .map((candidate) =>
          makeListItem(
            displayNodeName(candidate),
            `${candidate.id} · ${candidate.type}`,
            () => selectNode(candidate, true)
          )
        );
      renderList(sessionMentionsEl, sessions, 'No recent session mentions.');
    }

    function refreshSceneState() {
      const needle = searchInput.value.trim();
      const selectedNeighbors = selectedNode ? neighbors.get(selectedNode.id) || new Set() : new Set();
      for (const node of nodes) {
        const isDemohidden = state.demoMode && node.type === 'person';
        const isFolderFiltered = state.folderFilter && node.folder !== state.folderFilter;
        node.visibleByToggle = !state.hiddenTypes.has(node.type) && (state.showSessions || !node.is_session) && !isDemohidden && !isFolderFiltered;
        const visible = node.visibleByToggle;
        const connected = !!selectedNode && selectedNeighbors.has(node.id);
        const dimForSearch = needle && !node.matched && node !== selectedNode;
        const dimForBrowser = state.browserType && state.browserType !== node.type && node !== selectedNode;
        node.mesh.visible = visible;
        node.material.color.copy(
          node === selectedNode
            ? node.displayColor.clone().lerp(new THREE.Color('#fffdf4'), 0.2)
            : connected || node.matched
              ? node.displayColor
              : node.baseColor.clone().lerp(new THREE.Color('#f4d7a3'), 0.12)
        );
        node.material.opacity = !visible ? 0 : (dimForSearch || dimForBrowser ? 0.28 : connected || node === selectedNode ? 1 : 0.94);
        node.material.emissive.copy(
          node === selectedNode
            ? node.glowColor.clone().multiplyScalar(0.8)
            : connected || node.matched
              ? node.glowColor.clone().multiplyScalar(0.42)
              : node.glowColor.clone().multiplyScalar(dimForSearch || dimForBrowser ? 0.15 : 0.24)
        );
        node.mesh.scale.setScalar(node.radius * (node === selectedNode ? 1.48 : connected ? 1.18 : node.matched ? 1.08 : 1));
      }

      for (const edge of edges) {
        const visible = edge.source.visibleByToggle && edge.target.visibleByToggle && (!edge.isWire || state.showWires);
        const connected = !!selectedNode && (edge.source === selectedNode || edge.target === selectedNode);
        const matches = !needle || edge.source.matched || edge.target.matched;
        const dimForBrowser = state.browserType && edge.source.type !== state.browserType && edge.target.type !== state.browserType && !connected;
        edge.line.visible = visible;
        if (!visible) {
          continue;
        }
        edge.material.color.copy(
          connected
            ? edge.baseColor.clone().lerp(new THREE.Color('#fff2d1'), 0.34)
            : matches
              ? edge.baseColor.clone().lerp(new THREE.Color('#ffd7a3'), 0.1)
              : edge.baseColor
        );
        edge.material.opacity = connected
          ? (edge.isWire ? 1 : 0.54)
          : dimForBrowser
            ? 0.08
            : matches
              ? (edge.isWire ? 0.68 : 0.22)
              : 0.07;
      }
    }

    function updateLabels() {
      const allowed = new Set(
        sortNodes(
          nodes.filter((node) =>
            node.visibleByToggle
            && (state.showLabels || node === selectedNode || node.matched || node.degree >= 4 || state.browserType === node.type)
          )
        ).slice(0, 140).map((node) => node.id)
      );

      for (const node of nodes) {
        if (!allowed.has(node.id)) {
          node.labelEl.style.display = 'none';
          continue;
        }
        const projected = node.position.clone().project(camera);
        if (projected.z < -1 || projected.z > 1 || Math.abs(projected.x) > 1.1 || Math.abs(projected.y) > 1.1) {
          node.labelEl.style.display = 'none';
          continue;
        }
        node.labelEl.style.display = 'block';
        node.labelEl.textContent = displayNodeName(node);
        node.labelEl.className = `node-label${node === selectedNode ? ' active' : ''}`;
        node.labelEl.style.left = `${(projected.x * 0.5 + 0.5) * 100}%`;
        node.labelEl.style.top = `${(-projected.y * 0.5 + 0.5) * 100}%`;
      }
    }

    function ensureSelectionVisible() {
      const candidates = navigationCandidates();
      if (selectedNode && !candidates.includes(selectedNode)) {
        selectedNode = null;
      }
      if (!selectedNode && candidates.length) {
        selectNode(candidates[0], false);
        return;
      }
      updateDetail(selectedNode);
      refreshSceneState();
    }

    function applySearch() {
      const needle = searchInput.value.trim().toLowerCase();
      state.search = searchInput.value.trim();
      let matches = 0;
      for (const node of nodes) {
        node.matched = !!needle && !state.hiddenTypes.has(node.type) && (state.showSessions || !node.is_session) && node.haystack.includes(needle);
        if (node.matched) {
          matches += 1;
        }
      }
      matchCountEl.textContent = String(matches);
      ensureSelectionVisible();
      renderTypeBrowser();
      writeHashState();
    }

    function renderTypeBrowser() {
      typeNodeListEl.innerHTML = '';
      if (!state.browserType || state.hiddenTypes.has(state.browserType)) {
        typeBrowserTitleEl.textContent = 'Click a type to browse its nodes.';
        typeNodeListEl.appendChild(makeListItem('No type selected.', '', null));
        return;
      }
      const typed = sortNodes(nodes.filter((node) => node.type === state.browserType && node.visibleByToggle));
      typeBrowserTitleEl.textContent = `${state.browserType} · ${typed.length} visible`;
      if (!typed.length) {
        typeNodeListEl.appendChild(makeListItem('No visible nodes in this type.', '', null));
        return;
      }
      typed.slice(0, 40).forEach((node) => {
        typeNodeListEl.appendChild(
          makeListItem(
            displayNodeName(node),
            `${node.id} · degree ${node.degree}`,
            () => selectNode(node, true)
          )
        );
      });
    }

    function renderLegend() {
      legendEl.innerHTML = '';
      for (const typeName of typeNames) {
        const row = document.createElement('div');
        row.className = `legend-row${state.browserType === typeName ? ' active' : ''}`;

        const main = document.createElement('button');
        main.type = 'button';
        main.className = 'legend-main';
        main.innerHTML = `<span class="swatch" style="background:${typeColors[typeName] || '#b6c2cf'}"></span><span>${typeName}</span>`;
        main.addEventListener('click', () => {
          if (state.hiddenTypes.has(typeName)) {
            state.hiddenTypes.delete(typeName);
          }
          state.browserType = state.browserType === typeName ? null : typeName;
          if (state.browserType) {
            const first = sortNodes(nodes.filter((node) => node.type === state.browserType && node.visibleByToggle))[0];
            if (first) {
              selectNode(first, false);
              smartFitCamera();
            }
          }
          renderLegend();
          renderTypeBrowser();
          refreshSceneState();
          writeHashState();
        });

        const actions = document.createElement('div');
        actions.className = 'legend-actions';
        const count = document.createElement('span');
        count.className = 'mono subtle';
        count.textContent = String(atlasGraphPayload.type_counts[typeName]);
        const toggle = document.createElement('button');
        toggle.type = 'button';
        toggle.className = 'legend-toggle';
        toggle.textContent = state.hiddenTypes.has(typeName) ? 'show' : 'hide';
        toggle.addEventListener('click', (event) => {
          event.stopPropagation();
          if (state.hiddenTypes.has(typeName)) {
            state.hiddenTypes.delete(typeName);
          } else {
            state.hiddenTypes.add(typeName);
          }
          if (state.browserType === typeName && state.hiddenTypes.has(typeName)) {
            state.browserType = null;
          }
          layoutNodes();
          applySearch();
          renderLegend();
          renderTypeBrowser();
          smartFitCamera();
        });
        actions.appendChild(count);
        actions.appendChild(toggle);
        row.appendChild(main);
        row.appendChild(actions);
        legendEl.appendChild(row);
      }
    }

    function renderFolderFilter() {
      // Collect unique folders from nodes
      const folders = new Set();
      for (const node of nodes) {
        if (node.folder && node.visibleByToggle) {
          folders.add(node.folder);
        }
      }
      const sortedFolders = Array.from(folders).sort();

      // Clear existing options except 'all folders'
      folderFilterSelect.innerHTML = '<option value="">all folders</option>';

      // Add folder options
      for (const folder of sortedFolders) {
        const option = document.createElement('option');
        option.value = folder;
        const count = nodes.filter(n => n.folder === folder && n.visibleByToggle).length;
        option.textContent = `${folder} (${count})`;
        folderFilterSelect.appendChild(option);
      }
    }

    function selectNode(node, center = true) {
      selectedNode = node || null;
      updateDetail(selectedNode);
      refreshSceneState();
      if (center && selectedNode) {
        focusNode(selectedNode);
      }
      writeHashState();
    }

    function resizeRenderer() {
      const width = canvasHost.clientWidth || 1;
      const height = canvasHost.clientHeight || 1;
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    }

    function pickNode(event) {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const hits = raycaster.intersectObjects(nodes.map((node) => node.mesh), false);
      return hits.find((hit) => hit.object.visible)?.object?.userData?.node || null;
    }

    function projectNode(node) {
      return node.position.clone().project(camera);
    }

    function moveDirectional(direction) {
      const candidates = navigationCandidates();
      if (!candidates.length) {
        selectNode(null, false);
        return;
      }
      if (!selectedNode || !candidates.includes(selectedNode)) {
        selectNode(candidates[0], true);
        return;
      }
      const origin = projectNode(selectedNode);
      let bestNode = null;
      let bestScore = Infinity;
      for (const candidate of candidates) {
        if (candidate === selectedNode) {
          continue;
        }
        const point = projectNode(candidate);
        const dx = point.x - origin.x;
        const dy = point.y - origin.y;
        let primary = 0;
        let secondary = 0;
        if (direction === 'left') {
          primary = -dx;
          secondary = Math.abs(dy);
        } else if (direction === 'right') {
          primary = dx;
          secondary = Math.abs(dy);
        } else if (direction === 'up') {
          primary = dy;
          secondary = Math.abs(dx);
        } else {
          primary = -dy;
          secondary = Math.abs(dx);
        }
        if (primary <= 0.001) {
          continue;
        }
        const score = secondary * 8 + Math.hypot(dx, dy) / primary;
        if (score < bestScore) {
          bestScore = score;
          bestNode = candidate;
        }
      }
      if (bestNode) {
        selectNode(bestNode, true);
      }
    }

    function cycleSelection(delta) {
      const candidates = navigationCandidates();
      if (!candidates.length) {
        selectNode(null, false);
        return;
      }
      const current = selectedNode ? candidates.findIndex((node) => node.id === selectedNode.id) : -1;
      const next = current < 0
        ? (delta > 0 ? 0 : candidates.length - 1)
        : (current + delta + candidates.length) % candidates.length;
      selectNode(candidates[next], true);
    }

    function exportVisibleGraph() {
      const activeIds = new Set(activeNodes().map((node) => node.id));
      const searchIds = state.search ? new Set(nodes.filter((node) => node.matched).map((node) => node.id)) : null;
      const chosenIds = searchIds && searchIds.size ? searchIds : activeIds;
      const subgraph = {
        generated: atlasGraphPayload.generated,
        atlas_root: atlasGraphPayload.atlas_root,
        nodes: atlasGraphPayload.nodes.filter((node) => chosenIds.has(node.id)),
        edges: atlasGraphPayload.edges.filter((edge) => {
          if (!chosenIds.has(edge.source) || !chosenIds.has(edge.target)) {
            return false;
          }
          if (edge.kind === 'wire' && !state.showWires) {
            return false;
          }
          return true;
        }),
      };
      const blob = new Blob([JSON.stringify(subgraph, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'atlas-subgraph.json';
      link.click();
      URL.revokeObjectURL(url);
    }

    function exportPng() {
      const link = document.createElement('a');
      link.href = renderer.domElement.toDataURL('image/png');
      link.download = 'atlas-viewport.png';
      link.click();
    }

    function restoreHashSelection() {
      if (!initialHashState) {
        return;
      }
      if (Array.isArray(initialHashState.cameraPosition) && initialHashState.cameraPosition.length === 3) {
        camera.position.fromArray(initialHashState.cameraPosition);
      }
      if (Array.isArray(initialHashState.cameraTarget) && initialHashState.cameraTarget.length === 3) {
        cameraTarget.fromArray(initialHashState.cameraTarget);
        camera.lookAt(cameraTarget);
        syncCameraStateFromActual();
      }
      if (typeof initialHashState.selected === 'string' && nodeById.has(initialHashState.selected)) {
        selectedNode = nodeById.get(initialHashState.selected);
      }
    }

    function animate() {
      requestAnimationFrame(animate);
      stars.rotation.y += 0.0002;
      stars.rotation.x += 0.00004;
      if (cameraGoal) {
        camera.position.lerp(cameraGoal.position, 0.12);
        cameraTarget.lerp(cameraGoal.target, 0.12);
        camera.lookAt(cameraTarget);
        if (camera.position.distanceTo(cameraGoal.position) < 0.4 && cameraTarget.distanceTo(cameraGoal.target) < 0.4) {
          camera.position.copy(cameraGoal.position);
          cameraTarget.copy(cameraGoal.target);
          camera.lookAt(cameraTarget);
          syncCameraStateFromActual();
          cameraGoal = null;
          writeHashState();
        }
      } else {
        applyCameraState(0.18);
      }
      renderer.render(scene, camera);
      updateLabels();
    }

    renderer.domElement.addEventListener('contextmenu', (event) => {
      event.preventDefault();
    });
    renderer.domElement.addEventListener('wheel', (event) => {
      event.preventDefault();
      if (event.shiftKey) {
        cameraState.azimuth += event.deltaY * 0.0025;
      } else {
        const multiplier = event.ctrlKey ? 0.0014 : 0.001;
        cameraState.distance = clamp(cameraState.distance * (1 + event.deltaY * multiplier), 55, 2400);
      }
      writeHashState();
    }, { passive: false });
    renderer.domElement.addEventListener('pointerdown', (event) => {
      pointerDown = { x: event.clientX, y: event.clientY, pointerId: event.pointerId };
      moved = false;
      dragMode = event.button === 2 || event.shiftKey ? 'pan' : 'orbit';
      renderer.domElement.setPointerCapture?.(event.pointerId);
    });
    renderer.domElement.addEventListener('pointermove', (event) => {
      if (!pointerDown) {
        return;
      }
      const dx = event.clientX - pointerDown.x;
      const dy = event.clientY - pointerDown.y;
      if (Math.hypot(dx, dy) > 2) {
        moved = true;
      }
      if (dragMode === 'orbit') {
        cameraState.azimuth -= dx * 0.005;
        cameraState.polar = clamp(cameraState.polar + dy * 0.005, 0.08, Math.PI - 0.08);
      } else {
        const scale = cameraState.distance * 0.0015;
        const forward = cameraTarget.clone().sub(camera.position).normalize();
        const right = new THREE.Vector3().crossVectors(forward, WORLD_UP).normalize();
        const up = new THREE.Vector3().crossVectors(right, forward).normalize();
        cameraState.target.add(right.multiplyScalar(-dx * scale));
        cameraState.target.add(up.multiplyScalar(dy * scale));
      }
      pointerDown.x = event.clientX;
      pointerDown.y = event.clientY;
    });
    renderer.domElement.addEventListener('pointerup', (event) => {
      if (!moved) {
        const node = pickNode(event);
        if (node) {
          selectNode(node, false);
        }
      }
      if (pointerDown) {
        renderer.domElement.releasePointerCapture?.(pointerDown.pointerId);
      }
      pointerDown = null;
      dragMode = null;
      writeHashState();
    });
    renderer.domElement.addEventListener('dblclick', () => {
      if (selectedNode) {
        focusNode(selectedNode);
      } else {
        resetCamera();
      }
    });

    searchInput.addEventListener('input', applySearch);
    searchInput.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        searchInput.value = '';
        applySearch();
        searchInput.blur();
      }
    });

    showLabelsToggle.addEventListener('change', () => {
      state.showLabels = showLabelsToggle.checked;
      saveToggles();
      refreshSceneState();
      writeHashState();
    });
    demoModeToggle.addEventListener('change', () => {
      state.demoMode = demoModeToggle.checked;
      saveToggles();
      layoutNodes();
      applySearch();
      renderTypeBrowser();
      refreshSceneState();
      smartFitCamera();
      writeHashState();
    });
    hideNamesToggle.addEventListener('change', () => {
      state.hideNames = hideNamesToggle.checked;
      saveToggles();
      updateDetail(selectedNode);
      renderTypeBrowser();
      refreshSceneState();
      writeHashState();
    });
    folderFilterSelect.addEventListener('change', () => {
      state.folderFilter = folderFilterSelect.value;
      layoutNodes();
      applySearch();
      renderFolderFilter();
      renderTypeBrowser();
      refreshSceneState();
      smartFitCamera();
      writeHashState();
    });
    showSessionsToggle.addEventListener('change', () => {
      state.showSessions = showSessionsToggle.checked;
      saveToggles();
      layoutNodes();
      applySearch();
      renderLegend();
      renderTypeBrowser();
      smartFitCamera();
    });
    showWiresToggle.addEventListener('change', () => {
      state.showWires = showWiresToggle.checked;
      saveToggles();
      refreshSceneState();
      writeHashState();
    });

    document.getElementById('reset-layout').addEventListener('click', () => {
      layoutNodes();
      applySearch();
      smartFitCamera();
    });
    document.getElementById('fit-view').addEventListener('click', () => smartFitCamera({ preferSelection: true }));
    document.getElementById('show-all-types').addEventListener('click', () => {
      state.hiddenTypes.clear();
      state.browserType = null;
      renderLegend();
      layoutNodes();
      applySearch();
      renderTypeBrowser();
      smartFitCamera();
    });
    document.getElementById('export-png').addEventListener('click', exportPng);
    document.getElementById('export-json').addEventListener('click', exportVisibleGraph);
    document.getElementById('copy-link').addEventListener('click', async () => {
      writeHashState();
      try {
        await navigator.clipboard.writeText(location.href);
      } catch (error) {
        window.prompt('Copy graph link:', location.href);
      }
    });

    window.addEventListener('resize', () => {
      resizeRenderer();
      updateLabels();
    });

    document.addEventListener('keydown', (event) => {
      if (event.metaKey || event.ctrlKey || event.altKey) {
        return;
      }
      if (document.activeElement === searchInput) {
        return;
      }
      if (event.key === '/') {
        event.preventDefault();
        searchInput.focus();
        searchInput.select();
        return;
      }
      if (event.key === 'h') {
        event.preventDefault();
        helpOverlay.hidden = !helpOverlay.hidden;
        return;
      }
      if (event.key === 's') {
        event.preventDefault();
        showSessionsToggle.checked = !showSessionsToggle.checked;
        showSessionsToggle.dispatchEvent(new Event('change'));
        return;
      }
      if (event.key === 'w') {
        event.preventDefault();
        showWiresToggle.checked = !showWiresToggle.checked;
        showWiresToggle.dispatchEvent(new Event('change'));
        return;
      }
      if (event.key === 'x') {
        event.preventDefault();
        hideNamesToggle.checked = !hideNamesToggle.checked;
        hideNamesToggle.dispatchEvent(new Event('change'));
        return;
      }
      if (event.key === 'r') {
        event.preventDefault();
        resetCamera();
        return;
      }
      if (event.key === '0') {
        event.preventDefault();
        state.hiddenTypes.clear();
        state.browserType = null;
        renderLegend();
        layoutNodes();
        applySearch();
        renderTypeBrowser();
        smartFitCamera();
        return;
      }
      if (event.key === 'j') {
        event.preventDefault();
        cycleSelection(1);
        return;
      }
      if (event.key === 'k') {
        event.preventDefault();
        cycleSelection(-1);
        return;
      }
      if (event.key === 'ArrowLeft') {
        event.preventDefault();
        moveDirectional('left');
        return;
      }
      if (event.key === 'ArrowRight') {
        event.preventDefault();
        moveDirectional('right');
        return;
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault();
        moveDirectional('up');
        return;
      }
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        moveDirectional('down');
        return;
      }
      if ((event.key === 'Enter' || event.key === ' ') && selectedNode) {
        event.preventDefault();
        focusNode(selectedNode);
      }
    });

    resizeRenderer();
    layoutNodes();
    restoreHashSelection();
    renderLegend();
    renderFolderFilter();
    applySearch();
    renderTypeBrowser();
    refreshSceneState();
    if (selectedNode && selectedNode.visibleByToggle) {
      updateDetail(selectedNode);
    } else {
      ensureSelectionVisible();
    }
    if (!initialHashState || !initialHashState.cameraPosition) {
      resetCamera();
    }
    animate();
    })();
  </script>
</body>
</html>
"""
    return (
        template
        .replace("__THREE_VENDOR__", vendor_three)
        .replace("__PAYLOAD__", payload_json)
    )
