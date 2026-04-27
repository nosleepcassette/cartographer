from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from .config import load_config
from .notes import parse_frontmatter
from .profiles import profile_payload
from .wires import VALID_WIRE_PREDICATES


TYPE_COLORS = {
    "person": "#8ec1ff",
    "project": "#d9a95d",
    "goal": "#e6c15d",
    "entity": "#6cb88f",
    "agent-log": "#7aa6d9",
    "session": "#7aa6d9",
    "daily": "#7d9fd8",
    "learning": "#d5b06b",
    "note": "#e6ecf5",
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
SHIPPED_GRAPH_THEMES = {"baseline", "astral"}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _discover_theme_files(atlas_root: Path) -> list[Path]:
    theme_dir = atlas_root / "themes"
    if not theme_dir.exists():
        return []
    return sorted(path for path in theme_dir.glob("*.js") if path.is_file())


def _graph_config_payload(atlas_root: Path) -> dict[str, Any]:
    config = load_config(root=atlas_root)
    active_profile = profile_payload(atlas_root, config=config)
    graph = config.get("graph", {}) if isinstance(config, dict) else {}
    if not isinstance(graph, dict):
        graph = {}
    privacy = graph.get("privacy", {})
    if not isinstance(privacy, dict):
        privacy = {}
    mode = str(privacy.get("mode") or "off").strip().lower()
    if mode not in {"off", "names", "names_relationships", "full"}:
        mode = "off"
    theme_preset = str(graph.get("theme_preset") or "baseline").strip().lower() or "baseline"
    theme_files = _discover_theme_files(atlas_root)
    available_theme_presets = sorted(
        SHIPPED_GRAPH_THEMES | {path.stem.strip().lower() for path in theme_files if path.stem.strip()}
    )
    return {
        "theme_preset": theme_preset,
        "profile": active_profile,
        "available_theme_presets": available_theme_presets,
        "theme_script_paths": [f"./themes/{path.name}" for path in theme_files],
        "show_people": bool(graph.get("show_people", True)),
        "always_visible_people": _string_list(graph.get("always_visible_people")),
        "visible_people": _string_list(graph.get("visible_people")),
        "hidden_people": _string_list(graph.get("hidden_people")),
        "privacy": {
            "mode": mode,
            "never_redact_ids": _string_list(privacy.get("never_redact_ids")),
            "person_order": _string_list(privacy.get("person_order")),
        },
    }


def _wire_metadata_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "weight": None if row["weight"] is None else float(row["weight"]),
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
        "author": None if row["author"] is None else str(row["author"]),
        "method": None if row["method"] is None else str(row["method"]),
        "reviewed": None if row["reviewed"] is None else bool(row["reviewed"]),
        "reviewed_by": None if row["reviewed_by"] is None else str(row["reviewed_by"]),
        "reviewed_at": None if row["reviewed_at"] is None else str(row["reviewed_at"]),
        "review_duration_s": None
        if row["review_duration_s"] is None
        else float(row["review_duration_s"]),
 "confidence": None if row["confidence"] is None else str(row["confidence"]),
 "note": None if row["note"] is None else str(row["note"]),
 "privacy": None if row["privacy"] is None else str(row["privacy"]),
 "state_modifiers": None if row["state_modifiers"] is None else str(row["state_modifiers"]),
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


def load_graph_payload(atlas_root: Path | str, *, plugin_names: tuple[str, ...] = ()) -> dict[str, Any]:
    atlas_root = Path(atlas_root)
    db_path = atlas_root / ".cartographer" / "index.db"
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    graph_config = _graph_config_payload(atlas_root)
    active_profile = graph_config.get("profile", {})
    predicate_colors = active_profile.get("predicate_colors", {})

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
                source_block,
                target_note,
                target_block,
                predicate,
                weight,
                relationship,
                bidirectional,
                emotional_valence,
                energy_impact,
                avoidance_risk,
                growth_edge,
                current_state,
                since,
                until,
                valence_note,
                author,
                method,
                reviewed,
                reviewed_by,
                reviewed_at,
                review_duration_s,
    confidence,
    note,
    privacy,
    state_modifiers,
    path,
    line
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

    valid_predicates = set(active_profile.get("default_predicates") or VALID_WIRE_PREDICATES)
    # Merge plugin predicates so plugin-provided wires aren't filtered out
    if plugin_names:
        from .graph_plugins import discover_graph_plugins, plugin_predicate_lookup
        _payload_plugins = [p for p in discover_graph_plugins() if p.name in plugin_names]
        if _payload_plugins:
            for pred_name in plugin_predicate_lookup(_payload_plugins):
                valid_predicates.add(pred_name)
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
            "source_block": None if row["source_block"] is None else str(row["source_block"]),
            "target_block": None if row["target_block"] is None else str(row["target_block"]),
            "predicate": predicate,
            "color": predicate_colors.get(predicate),
            "path": None if row["path"] is None else str(row["path"]),
            "line": None if row["line"] is None else int(row["line"]),
            **_wire_metadata_payload(row),
            "bidirectional": bool(row["bidirectional"]),
        }
        incident_payload = {
            "source": source,
            "target": target,
            "source_block": None if row["source_block"] is None else str(row["source_block"]),
            "target_block": None if row["target_block"] is None else str(row["target_block"]),
            "predicate": predicate,
            "path": None if row["path"] is None else str(row["path"]),
            "line": None if row["line"] is None else int(row["line"]),
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
                "person_order_index": None,
                "privacy_alias": None,
                "preview": _note_preview(Path(raw_path)) if raw_path else "",
                "is_session": note_type in SESSION_NOTE_TYPES,
            }
        )

    configured_person_order = [
        str(value).strip().lower()
        for value in graph_config.get("privacy", {}).get("person_order", [])
        if str(value).strip()
    ]
    configured_person_rank = {
        note_id: index for index, note_id in enumerate(configured_person_order)
    }
    ordered_people = sorted(
        (node for node in nodes if node["type"] == "person"),
        key=lambda node: (
            configured_person_rank.get(str(node["id"]).lower(), 10_000),
            str(node["title"]).lower(),
            str(node["id"]).lower(),
        ),
    )
    for index, node in enumerate(ordered_people, start=1):
        node["person_order_index"] = index
        node["privacy_alias"] = f"Person {index}"

    return {
        "generated": date.today().isoformat(),
        "atlas_root": str(atlas_root),
        "graph_config": graph_config,
        "predicate_palette": [
            {
                "name": predicate,
                "color": str(predicate_colors.get(predicate) or ""),
            }
            for predicate in active_profile.get("default_predicates", [])
        ],
        "node_count": len(nodes),
        "edge_count": len(edges),
        "wire_count": wire_count,
        "unresolved_edge_count": unresolved_edge_count,
        "type_counts": dict(sorted(type_counts.items())),
        "nodes": nodes,
        "edges": edges,
    }


def render_graph_html(payload: dict[str, Any], *, plugin_names: tuple[str, ...] = ()) -> str:
    # Load graph plugin predicates for edge styling (only when plugins are requested)
    if plugin_names:
        from .graph_plugins import discover_graph_plugins, plugin_predicate_lookup
        _graph_plugins = [p for p in discover_graph_plugins() if p.name in plugin_names]
        if _graph_plugins:
            payload['graph_config']['plugin_predicates'] = plugin_predicate_lookup(_graph_plugins)
            payload['graph_config']['privacy_tiers'] = [t for t in ['public', 'inner-circle', 'private']]

    payload_json = (
        json.dumps(payload, ensure_ascii=False)
        .replace("</", "<\\/")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    vendor_three = _vendor_script_text("three.module.js")
    graph_config = payload.get("graph_config", {})
    theme_script_tags = "\n".join(
        f'  <script src="{path}"></script>'
        for path in graph_config.get("theme_script_paths", [])
        if isinstance(path, str) and path.strip()
    )
    template = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>atlas graph</title>
  <script>
    (function() {
      const registry = window.CART_THEMES || {};
      const themes = registry._themes || new Map();

      function normalizeTheme(definition) {
        if (!definition || typeof definition !== 'object') {
          return null;
        }
        const id = String(definition.id || definition.preset?.id || '').trim().toLowerCase();
        if (!id) {
          return null;
        }
        const preset = definition.preset && typeof definition.preset === 'object'
          ? { ...definition.preset, id }
          : { id };
        const glyphs = definition.glyphs && typeof definition.glyphs === 'object'
          ? { ...definition.glyphs }
          : {};
        const wireAspects = definition.wireAspects && typeof definition.wireAspects === 'object'
          ? { ...definition.wireAspects }
          : {};
        const runtime = definition.runtime && typeof definition.runtime === 'object'
          ? { ...definition.runtime }
          : {};
        return { id, preset, glyphs, wireAspects, runtime };
      }

      function mergeTheme(baseTheme, overrideTheme) {
        return {
          id: overrideTheme.id || baseTheme.id,
          preset: { ...(baseTheme.preset || {}), ...(overrideTheme.preset || {}), id: overrideTheme.id || baseTheme.id },
          glyphs: { ...(baseTheme.glyphs || {}), ...(overrideTheme.glyphs || {}) },
          wireAspects: { ...(baseTheme.wireAspects || {}), ...(overrideTheme.wireAspects || {}) },
          runtime: { ...(baseTheme.runtime || {}), ...(overrideTheme.runtime || {}) },
        };
      }

      registry._themes = themes;
      registry.register = function(definition) {
        const normalized = normalizeTheme(definition);
        if (!normalized) {
          return;
        }
        const existing = themes.get(normalized.id);
        themes.set(normalized.id, existing ? mergeTheme(existing, normalized) : normalized);
      };
      registry.registerBuiltIn = function(definition) {
        const normalized = normalizeTheme(definition);
        if (!normalized) {
          return;
        }
        const existing = themes.get(normalized.id);
        themes.set(normalized.id, existing ? mergeTheme(normalized, existing) : normalized);
      };
      registry.get = function(id) {
        const key = String(id || '').trim().toLowerCase();
        return themes.get(key) || themes.get('baseline') || null;
      };
      registry.list = function() {
        return Array.from(themes.values()).sort((a, b) =>
          String(a.preset?.title || a.id).localeCompare(String(b.preset?.title || b.id))
        );
      };
      window.CART_THEMES = registry;
    })();
  </script>
  <style>
    :root {
      --panel: rgba(12, 16, 28, 0.92);
      --panel-border: rgba(255, 255, 255, 0.08);
      --text: #eef3ff;
      --muted: #a8b3cb;
      --accent: #8fc9ff;
      --accent-warm: #d9e7ff;
      --surface: rgba(255, 255, 255, 0.045);
      --surface-strong: rgba(255, 255, 255, 0.075);
      --shadow: 0 26px 80px rgba(0, 0, 0, 0.45);
      --body-bg:
        radial-gradient(circle at 18% 18%, rgba(115, 141, 255, 0.09), transparent 24rem),
        radial-gradient(circle at 78% 20%, rgba(80, 220, 255, 0.05), transparent 30rem),
        linear-gradient(180deg, #04070f 0%, #09111d 42%, #0d1626 100%);
      --canvas-bg:
        radial-gradient(circle at 22% 18%, rgba(114, 137, 255, 0.06), transparent 28%),
        radial-gradient(circle at 74% 22%, rgba(88, 227, 255, 0.04), transparent 32%),
        linear-gradient(180deg, rgba(5, 8, 14, 0.98), rgba(8, 13, 22, 0.95));
      --title-color: #d9e7ff;
      --survey-color: #cfe3ff;
      --glyph-color: #bfd5ff;
      --label-glow: rgba(0, 0, 0, 0.88);
    }
    body[data-theme="astral"] {
      --panel: rgba(10, 13, 23, 0.9);
      --panel-border: rgba(132, 166, 255, 0.14);
      --muted: #9aa7c6;
      --accent: #9fd2ff;
      --accent-warm: #efd08f;
      --body-bg:
        radial-gradient(circle at 18% 18%, rgba(115, 141, 255, 0.18), transparent 24rem),
        radial-gradient(circle at 78% 20%, rgba(80, 220, 255, 0.11), transparent 30rem),
        radial-gradient(circle at 55% 82%, rgba(237, 208, 143, 0.09), transparent 24rem),
        linear-gradient(180deg, #03050d 0%, #070b16 42%, #0a1020 100%);
      --canvas-bg:
        radial-gradient(circle at 22% 18%, rgba(114, 137, 255, 0.12), transparent 28%),
        radial-gradient(circle at 74% 22%, rgba(88, 227, 255, 0.09), transparent 32%),
        radial-gradient(circle at 58% 74%, rgba(239, 208, 143, 0.07), transparent 28%),
        linear-gradient(180deg, rgba(5, 7, 13, 0.98), rgba(8, 12, 22, 0.95));
      --title-color: #efd08f;
      --survey-color: #efd08f;
      --glyph-color: #efd08f;
      --label-glow: rgba(0, 0, 0, 0.9);
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; }
    body {
      background: var(--body-bg);
      color: var(--text);
      font-family: "Avenir Next", "SF Pro Display", "Segoe UI", sans-serif;
      overflow: hidden;
    }
    .app {
      display: grid;
      grid-template-columns: 14.5rem 1fr 18.5rem;
      gap: 0.5rem;
      height: 100vh;
      padding: 0.5rem;
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
      gap: 0.5rem;
      padding: 0.5rem;
      overflow: hidden;
    }
    .sidebar-scroll {
      min-height: 0;
      overflow: auto;
      display: grid;
      gap: 0.38rem;
      padding-right: 0.12rem;
      padding-bottom: 0.2rem;
      overscroll-behavior: contain;
    }
    .sidebar-footer {
      display: grid;
      gap: 0.4rem;
      padding-top: 0.2rem;
      border-top: 1px solid rgba(255, 255, 255, 0.05);
    }
    .canvas-panel {
      position: relative;
      overflow: hidden;
      background: var(--canvas-bg);
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
      text-shadow: 0 0 12px var(--label-glow);
    }
    .node-label.active { color: var(--accent); font-weight: 700; }
    .edge-label {
      position: absolute;
      transform: translate(-50%, -50%);
      color: #f7ebc8;
      font-size: 0.64rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      white-space: nowrap;
      padding: 0.16rem 0.34rem;
      border-radius: 999px;
      background: rgba(10, 12, 22, 0.58);
      border: 1px solid rgba(255, 232, 184, 0.12);
      box-shadow: 0 0 16px rgba(0, 0, 0, 0.26);
    }
 /* PLUGIN_HOOK:wire_styling */
 /* PLUGIN_HOOK:edge_rendering */
    .eyebrow {
      color: var(--muted);
      font-size: 0.65rem;
      text-transform: uppercase;
      letter-spacing: 0.15em;
    }
    h1, h2, p { margin: 0; }
    h1 {
      font-family: "Baskerville", "Iowan Old Style", serif;
      font-size: 1.34rem;
      line-height: 1;
      color: var(--title-color);
    }
    h2 { font-size: 0.95rem; line-height: 1.05; }
    .subtle { color: var(--muted); font-size: 0.75rem; line-height: 1.25; }
    .stat-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 0.35rem;
    }
    .stat, .card {
      padding: 0.42rem;
      border-radius: 0.8rem;
      background: var(--surface);
      border: 1px solid rgba(255, 255, 255, 0.06);
    }
    .card.compact-card {
      padding: 0.36rem 0.4rem;
    }
    .stat strong {
      display: block;
      color: var(--accent-warm);
      font-size: 0.9rem;
    }
    .stat { font-size: 0.72rem; }
    details {
      padding: 0.42rem;
      border-radius: 0.8rem;
      background: var(--surface);
      border: 1px solid rgba(255, 255, 255, 0.06);
    }
    summary {
      cursor: pointer;
      user-select: none;
      outline: none;
    }
    summary:hover {
      color: var(--accent);
    }
    details[open] summary {
      margin-bottom: 0.3rem;
    }
    .label { color: var(--muted); font-size: 0.7rem; }
    .search-wrap { display: grid; gap: 0.3rem; }
    input[type="search"] {
      width: 100%;
      border: 1px solid rgba(255, 255, 255, 0.08);
      background: rgba(0, 0, 0, 0.28);
      color: var(--text);
      border-radius: 0.75rem;
      padding: 0.5rem 0.65rem;
      outline: none;
      font-size: 0.8rem;
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
      border-radius: 0.7rem;
      padding: 0.4rem 0.5rem;
      outline: none;
      font: inherit;
      font-size: 0.8rem;
    }
    select:focus {
      border-color: rgba(237, 203, 128, 0.42);
      box-shadow: 0 0 0 3px rgba(237, 203, 128, 0.08);
    }
    select option {
      background: #1a1f2e;
      color: var(--text);
    }
    input[type="text"],
    input[type="number"],
    textarea {
      width: 100%;
      border: 1px solid rgba(255, 255, 255, 0.08);
      background: rgba(0, 0, 0, 0.28);
      color: var(--text);
      border-radius: 0.7rem;
      padding: 0.45rem 0.55rem;
      outline: none;
      font: inherit;
      font-size: 0.78rem;
    }
    input[type="text"]:focus,
    input[type="number"]:focus,
    textarea:focus {
      border-color: rgba(237, 203, 128, 0.42);
      box-shadow: 0 0 0 3px rgba(237, 203, 128, 0.08);
    }
    input[type="range"] {
      width: 100%;
      accent-color: var(--accent-warm);
    }
    .controls, .toggle-grid {
      display: flex;
      flex-wrap: wrap;
      gap: 0.35rem;
    }
    .button-row {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 0.35rem;
    }
    .mini-toggle-row {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 0.3rem;
    }
    .toggle-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 0.35rem;
    }
    button, .button-link {
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 999px;
      padding: 0.38rem 0.62rem;
      background: rgba(255, 255, 255, 0.045);
      color: var(--text);
      cursor: pointer;
      text-decoration: none;
      font: inherit;
      font-size: 0.74rem;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
    }
    button:hover, .button-link:hover {
      border-color: rgba(159, 210, 255, 0.34);
      background: rgba(159, 210, 255, 0.08);
    }
    button.compact, .button-link.compact {
      padding: 0.28rem 0.5rem;
      font-size: 0.68rem;
    }
    button.danger {
      border-color: rgba(255, 120, 120, 0.18);
      color: #ffd0d0;
    }
    button.danger:hover {
      border-color: rgba(255, 120, 120, 0.4);
      background: rgba(255, 120, 120, 0.12);
    }
    label.toggle {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 0.28rem;
      padding: 0.3rem 0.45rem;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.03);
      color: var(--muted);
      font-size: 0.68rem;
      border: 1px solid rgba(255, 255, 255, 0.05);
    }
    label.toggle.active {
      color: var(--text);
      border-color: rgba(159, 210, 255, 0.22);
      background: rgba(159, 210, 255, 0.08);
    }
    label.toggle input { accent-color: var(--accent); }
    .legend {
      display: grid;
      gap: 0.3rem;
      max-height: 11rem;
      overflow: auto;
      padding-right: 0.15rem;
    }
    .legend-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 0.35rem;
      align-items: center;
      padding: 0.3rem 0.4rem;
      border-radius: 0.65rem;
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
      padding: 0.2rem 0.4rem;
      font-size: 0.7rem;
      background: rgba(255, 255, 255, 0.05);
    }
    .swatch {
      width: 0.7rem;
      height: 0.7rem;
      border-radius: 999px;
      display: inline-block;
      box-shadow: 0 0 10px currentColor;
    }
    .glyph-swatch {
      width: 1rem;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-family: "Noto Sans Symbols 2", "Segoe UI Symbol", "Apple Symbols", serif;
      font-size: 0.9rem;
      color: var(--glyph-color);
      text-shadow: 0 0 10px rgba(159, 210, 255, 0.28);
    }
    .mono {
      font-family: "SFMono-Regular", "Menlo", monospace;
      font-size: 0.72rem;
    }
    .chips {
      display: flex;
      flex-wrap: wrap;
      gap: 0.3rem;
    }
    .chip {
      padding: 0.2rem 0.4rem;
      border-radius: 999px;
      background: rgba(237, 203, 128, 0.12);
      font-size: 0.7rem;
    }
    .chip-button {
      border: 1px solid rgba(237, 203, 128, 0.12);
      border-radius: 999px;
      padding: 0.28rem 0.55rem;
      background: rgba(255, 255, 255, 0.04);
      color: var(--text);
      cursor: pointer;
      font: inherit;
      font-size: 0.72rem;
      transition: background 120ms ease, border-color 120ms ease, opacity 120ms ease;
    }
    .chip-button:hover {
      border-color: rgba(237, 203, 128, 0.32);
    }
    .chip-button.active {
      background: rgba(237, 203, 128, 0.18);
      border-color: rgba(237, 203, 128, 0.42);
      color: #fff4d4;
    }
    .chip-button.inactive {
      opacity: 0.48;
      filter: saturate(0.72);
    }
    .folder-list {
      display: grid;
      gap: 0.28rem;
      max-height: min(16rem, 34vh);
      overflow: auto;
      padding-right: 0.1rem;
      overscroll-behavior: contain;
    }
    .folder-row {
      width: 100%;
      border-radius: 0.72rem;
      padding: 0.34rem 0.48rem;
      justify-content: space-between;
      background: rgba(255, 255, 255, 0.025);
    }
    .folder-row.active {
      border-color: rgba(159, 210, 255, 0.2);
      background: rgba(159, 210, 255, 0.07);
    }
    .folder-row.inactive {
      opacity: 0.5;
    }
    .folder-meta {
      display: inline-flex;
      align-items: center;
      gap: 0.45rem;
      min-width: 0;
    }
    .folder-name {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .folder-count {
      color: var(--muted);
      font-size: 0.68rem;
    }
    .list {
      list-style: none;
      margin: 0;
      padding: 0;
      display: grid;
      gap: 0.3rem;
    }
    .list li {
      padding: 0.3rem 0.4rem;
      border-radius: 0.6rem;
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid rgba(255, 255, 255, 0.04);
      cursor: pointer;
      font-size: 0.72rem;
    }
    .list li strong { font-size: 0.72rem; line-height: 1.15; }
    .list li span { font-size: 0.65rem; }
    .list li.empty {
      cursor: default;
      color: var(--muted);
    }
    .list strong { display: block; line-height: 1.3; }
    .detail-scroll {
      min-height: 0;
      overflow: auto;
      padding-right: 0.12rem;
      display: grid;
      gap: 0.4rem;
      overscroll-behavior: contain;
    }
    .detail-header {
      display: grid;
      gap: 0.2rem;
      min-width: 0;
      padding-bottom: 0.15rem;
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    }
    #detail-title {
      overflow-wrap: anywhere;
      line-height: 1.1;
    }
    #detail-subtitle {
      overflow-wrap: anywhere;
      line-height: 1.35;
      font-size: 0.7rem;
    }
    .preview {
      color: #f3ead9;
      font-size: 0.78rem;
    }
    .preview > :first-child { margin-top: 0; }
    .preview > :last-child { margin-bottom: 0; }
    .preview h1,
    .preview h2,
    .preview h3,
    .preview h4 {
      margin: 0 0 0.35rem;
      font-family: "Baskerville", "Iowan Old Style", serif;
      line-height: 1.02;
      color: #fff0c9;
    }
    .preview h1 { font-size: 1rem; }
    .preview h2 { font-size: 0.9rem; }
    .preview h3 { font-size: 0.82rem; }
    .preview h4 { font-size: 0.78rem; }
    .preview p,
    .preview ul,
    .preview ol,
    .preview blockquote,
    .preview pre,
    .preview table,
    .preview hr {
      margin: 0 0 0.35rem;
    }
    .preview p,
    .preview li {
      line-height: 1.3;
      color: #f0e5d0;
      font-size: 0.75rem;
    }
    .preview ul,
    .preview ol {
      padding-left: 0.9rem;
    }
    .preview li + li {
      margin-top: 0.08rem;
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
      gap: 0.5rem;
      flex-wrap: wrap;
      font-size: 0.72rem;
    }
    .panel-summary {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.5rem;
      margin-bottom: 0.25rem;
    }
    .detail-actions {
      margin: 0.4rem 0 0.2rem;
    }
    .inline-form {
      display: grid;
      gap: 0.35rem;
      margin-top: 0.45rem;
    }
    .inline-form[hidden] {
      display: none;
    }
    .stage-toolbar {
      position: absolute;
      top: 0.6rem;
      left: 0.6rem;
      right: 0.6rem;
      z-index: 2;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.7rem;
      padding: 0.42rem 0.56rem;
      border-radius: 999px;
      background: rgba(7, 10, 18, 0.72);
      border: 1px solid rgba(255, 255, 255, 0.09);
      backdrop-filter: blur(12px);
    }
    .stage-toolbar .survey {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      color: var(--survey-color);
      font-size: 0.78rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }
    .stage-toolbar .actions {
      display: inline-flex;
      align-items: center;
      gap: 0.45rem;
      min-width: 0;
    }
    .stage-toolbar .status {
      display: none;
    }
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
    #graph-error {
      position: absolute;
      left: 50%;
      top: 50%;
      transform: translate(-50%, -50%);
      z-index: 4;
      width: min(34rem, calc(100% - 2rem));
      padding: 1rem 1.1rem;
      border-radius: 1rem;
      border: 1px solid rgba(255, 120, 120, 0.34);
      background: rgba(19, 8, 12, 0.92);
      box-shadow: 0 24px 80px rgba(0, 0, 0, 0.42);
      color: #ffd4d4;
      backdrop-filter: blur(14px);
      white-space: pre-wrap;
      line-height: 1.45;
    }
    #graph-error strong {
      display: block;
      margin-bottom: 0.4rem;
      color: #fff3f3;
      font-size: 0.88rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }
    #graph-error[hidden] { display: none; }
    #help-overlay[hidden] { display: none; }
    #graph-tooltip {
      position: absolute;
      z-index: 5;
      max-width: min(22rem, 40vw);
      pointer-events: none;
      padding: 0.55rem 0.65rem;
      border-radius: 0.8rem;
      border: 1px solid rgba(245, 166, 35, 0.35);
      background: rgba(12, 14, 22, 0.92);
      box-shadow: 0 18px 50px rgba(0, 0, 0, 0.34);
      color: #ffe8bf;
      font-size: 0.72rem;
      line-height: 1.35;
      transform: translate(0.6rem, 0.6rem);
      white-space: pre-wrap;
    }
    #graph-tooltip[hidden] {
      display: none;
    }
    #help-overlay-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.5rem;
      margin-bottom: 0.65rem;
    }
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
      .button-row,
      .mini-toggle-row {
        grid-template-columns: 1fr;
      }
    }
  </style>
  <!-- CART-THEME-SCRIPTS -->
__THEME_SCRIPT_TAGS__
</head>
<body data-theme="__BODY_THEME__">
  <div class="app">
    <aside class="panel sidebar">
      <div class="sidebar-scroll">
        <div>
          <div class="eyebrow">atlas visual graph</div>
          <h1 id="graph-title">Atlas Graph</h1>
          <p class="subtle" id="graph-subtitle">Deterministic clusters, semantic wires, and camera-state links you can share.</p>
        </div>

        <div class="search-wrap">
          <label class="eyebrow" for="theme-picker">Theme</label>
          <select id="theme-picker"></select>
        </div>

        <div class="search-wrap">
          <label class="eyebrow" for="search">Search</label>
          <input id="search" type="search" placeholder="project, person, tag, note title">
        </div>

        <div class="button-row">
          <!-- PLUGIN_HOOK:toolbar -->
<button id="reset-layout" type="button" class="compact">re-layout</button>
          <button id="fit-view" type="button" class="compact">fit view</button>
          <button id="show-all-types" type="button" class="compact">reset</button>
        </div>

        <div class="card">
          <div class="panel-summary">
            <div class="eyebrow">Folders</div>
            <button id="show-all-folders" type="button" class="compact">show all</button>
          </div>
          <div class="folder-list" id="folder-chip-list"></div>
        </div>

        <details class="card compact-card" open>
          <summary class="eyebrow">privacy</summary>
          <div class="search-wrap" style="margin-top: 0.35rem;">
            <label class="eyebrow" for="privacy-mode">Mode</label>
            <select id="privacy-mode">
              <option value="off">off</option>
              <option value="names">redact names</option>
              <option value="names_relationships">redact names + relationship info</option>
              <option value="full">full redact</option>
            </select>
          </div>
          <p class="subtle">Only personal identifiers are obscured. `maps` and `cassette` always stay visible.</p>
        </details>

        <details class="card compact-card">
          <summary class="eyebrow">more controls</summary>
          <div style="display: grid; gap: 0.4rem; margin-top: 0.35rem;">
            <div>
              <div class="eyebrow" style="margin-bottom: 0.28rem;">Predicate Filters</div>
              <div class="legend" id="predicate-legend"></div>
            </div>
            <div>
              <div class="eyebrow" style="margin-bottom: 0.28rem;">Type Legend</div>
              <div class="legend" id="legend"></div>
            </div>
            <div>
              <div class="eyebrow" style="margin-bottom: 0.28rem;">Type Browser</div>
              <div class="mono" id="type-browser-title">Click a type to browse its nodes.</div>
              <ul class="list" id="type-node-list"></ul>
            </div>
            <div>
              <div class="eyebrow" style="margin-bottom: 0.28rem;">Graph Stats</div>
              <div class="stat-grid">
                <div class="stat"><strong id="node-count"></strong><span class="label">nodes</span></div>
                <div class="stat"><strong id="edge-count"></strong><span class="label">edges</span></div>
                <div class="stat"><strong id="type-count"></strong><span class="label">types</span></div>
                <div class="stat"><strong id="match-count"></strong><span class="label">matches</span></div>
              </div>
              <div class="mono subtle" id="atlas-root" style="margin-top: 0.45rem;"></div>
            </div>
          </div>
        </details>
      </div>

      <div class="sidebar-footer">
        <div class="mini-toggle-row">
          <label class="toggle active"><input id="show-wires" type="checkbox" checked> wires</label>
          <label class="toggle"><input id="show-sessions" type="checkbox"> sessions</label>
          <label class="toggle"><input id="show-labels" type="checkbox"> force labels</label>
        </div>
 <div class="mini-toggle-row">
 <label class="toggle"><input id="show-unreviewed-only" type="checkbox"> unreviewed</label>
 <label class="toggle"><input id="trace-mode" type="checkbox"> trace</label>
 <label class="toggle"><input id="discover-overlay" type="checkbox"> discover</label>
 <label class="toggle"><input id="emotional-styling" type="checkbox"> emotional</label>
 </div>

        <div class="button-row">
          <button id="export-png" type="button" class="compact">png</button>
          <button id="export-json" type="button" class="compact">json</button>
          <button id="copy-link" type="button" class="compact">link</button>
        </div>
      </div>
    </aside>

    <main class="panel canvas-panel">
      <div class="stage-toolbar">
        <div class="survey">
          <span id="survey-mark">◎</span>
          <span id="survey-title">Atlas Graph</span>
        </div>
        <div class="actions">
          <div class="status" id="selection-status">awaiting selection</div>
          <div class="status" id="pending-review-status">0 wires pending review</div>
          <button id="toggle-help" type="button" class="compact" aria-expanded="false">help</button>
        </div>
      </div>

      <div id="help-overlay" hidden>
        <div id="help-overlay-header">
          <div class="eyebrow">Keybindings</div>
          <button id="close-help" type="button" class="compact">close</button>
        </div>
        <ul>
          <li><code>/</code> focus search.</li>
          <li><code>←</code> / <code>→</code> move inside the current structural group.</li>
          <li><code>↑</code> / <code>↓</code> move across adjacent structural groups.</li>
          <li><code>j</code> / <code>k</code> cycle visible nodes.</li>
          <li><code>s</code> hide or reveal session notes. Preference is remembered locally.</li>
          <li><code>w</code> toggle semantic wires while keeping wikilinks visible.</li>
          <li>Use the <code>help</code> button or <code>F1</code>. <code>Esc</code> closes overlays.</li>
          <li><code>r</code> reset camera, <code>0</code> clear hidden types and folders.</li>
          <li><code>Enter</code> or <code>Space</code> re-center on the selected node.</li>
        </ul>
      </div>

      <div id="graph-error" hidden></div>
      <div id="graph-canvas"></div>
      <div id="label-layer" aria-hidden="true"></div>
      <div id="graph-tooltip" hidden></div>
    </main>

    <aside class="panel detail">
      <div class="detail-header">
        <div class="eyebrow">Selected Note</div>
        <h2 id="detail-title">Nothing selected</h2>
        <p class="subtle" id="detail-subtitle">Click a node to inspect it.</p>
      </div>

      <div class="detail-scroll">
        <div class="card">
          <div class="detail-meta">
            <div class="eyebrow">Preview</div>
            <a class="button-link" id="open-note" href="#" target="_blank" rel="noopener noreferrer">edit note</a>
          </div>
          <div class="button-row detail-actions">
            <button id="run-trace" type="button" class="compact">run trace</button>
            <button id="toggle-add-wire" type="button" class="compact">add wire</button>
            <button id="discover-from-node" type="button" class="compact">discover from here</button>
          </div>
          <div class="inline-form" id="add-wire-form" hidden>
            <label class="eyebrow" for="add-wire-target">Target note</label>
            <input id="add-wire-target" type="text" list="node-id-options" placeholder="target note id">
            <label class="eyebrow" for="add-wire-predicate">Predicate</label>
            <select id="add-wire-predicate"></select>
            <label class="eyebrow" for="add-wire-weight">Weight</label>
            <input id="add-wire-weight" type="range" min="0" max="1" step="0.05" value="0.7">
            <div class="mono subtle" id="add-wire-weight-label">0.70</div>
            <div class="button-row detail-actions">
              <button id="submit-add-wire" type="button" class="compact">save wire</button>
              <button id="cancel-add-wire" type="button" class="compact">cancel</button>
            </div>
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

        <div class="card">
          <div class="eyebrow">Selected Edge</div>
          <div class="mono" id="edge-detail-title">No edge selected.</div>
          <div class="subtle" id="edge-detail-meta">Click a wire to inspect its provenance.</div>
          <div class="button-row detail-actions">
            <button id="mark-edge-reviewed" type="button" class="compact">mark reviewed</button>
            <button id="delete-edge" type="button" class="compact danger">delete wire</button>
          </div>
          <div class="inline-form" id="edge-edit-form">
            <label class="eyebrow" for="edge-predicate">Predicate</label>
            <select id="edge-predicate"></select>
            <label class="eyebrow" for="edge-weight">Weight</label>
            <input id="edge-weight" type="range" min="0" max="1" step="0.05" value="0.7">
            <div class="mono subtle" id="edge-weight-label">0.70</div>
            <label class="eyebrow" for="edge-confidence">Confidence</label>
            <select id="edge-confidence">
              <option value="">unchanged</option>
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
            </select>
            <!-- PLUGIN_HOOK:privacy_controls -->
<label class="eyebrow" for="edge-note">Note</label>
            <textarea id="edge-note" rows="3" placeholder="optional review note"></textarea>
            <div class="button-row detail-actions">
              <button id="save-edge" type="button" class="compact">save edits</button>
            </div>
          </div>
        </div>

        <div class="card" id="discover-card">
          <div class="eyebrow">Discover Candidate</div>
          <div class="mono" id="discover-detail-title">No candidate selected.</div>
          <div class="subtle" id="discover-detail-meta">Turn on discover mode and click a dashed candidate edge.</div>
          <div class="inline-form">
            <label class="eyebrow" for="discover-predicate">Predicate</label>
            <select id="discover-predicate"></select>
            <label class="eyebrow" for="discover-weight">Weight</label>
            <input id="discover-weight" type="range" min="0" max="1" step="0.05" value="0.7">
            <div class="mono subtle" id="discover-weight-label">0.70</div>
            <label class="eyebrow" for="discover-confidence">Confidence</label>
            <select id="discover-confidence">
              <option value="low">low</option>
              <option value="medium" selected>medium</option>
              <option value="high">high</option>
            </select>
            <label class="eyebrow" for="discover-note">Note</label>
            <textarea id="discover-note" rows="3" placeholder="optional accept note"></textarea>
            <div class="button-row detail-actions">
              <button id="accept-discover" type="button" class="compact">accept</button>
              <button id="reject-discover" type="button" class="compact">reject</button>
            </div>
          </div>
        </div>
      </div>
    </aside>
  </div>

  <datalist id="node-id-options"></datalist>

  <script type="module">
    __THREE_VENDOR__

    const THREE = {
      CanvasTexture,
      AmbientLight,
      Box3,
      BufferAttribute,
      BufferGeometry,
      Color,
      DirectionalLight,
      FogExp2,
      Group,
      IcosahedronGeometry,
      Line,
      LineBasicMaterial,
      LineDashedMaterial,
      LineLoop,
      Mesh,
      MeshStandardMaterial,
      PerspectiveCamera,
      Points,
      PointsMaterial,
      Raycaster,
      Scene,
      Sprite,
      SpriteMaterial,
      Sphere,
      Vector2,
      Vector3,
      WebGLRenderer,
    };

    (() => {
    const atlasGraphPayload = __PAYLOAD__;
    const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
    let predicatePalette = Array.isArray(atlasGraphPayload.predicate_palette)
      ? atlasGraphPayload.predicate_palette
      : [];
    let predicateColors = Object.fromEntries(
      predicatePalette
        .filter((item) => item && item.name)
        .map((item) => [item.name, item.color || '#f0b35f'])
    );
    function rebuildPredicateColorMap() {
      predicateColors = Object.fromEntries(
        predicatePalette
          .filter((item) => item && item.name)
          .map((item) => [item.name, item.color || '#f0b35f'])
      );
    }
    const emotionalColors = {
      positive: '#67d98b',
      negative: '#f06a74',
      mixed: '#b988ff',
      neutral: '#a7b3c3',
    };
    const ASTRAL_WIRE_ASPECTS = {
      supports: '△',
      grounds: '⚹',
      intensifies_with: '☌',
      contradicts: '□',
      depends_on: '☍',
      part_of: '⚺',
      co_occurs_with: '⚺',
      precedes: '↗',
      follows: '↘',
      relates_to_goal: '✦',
      relates_to_person: '☽',
      intention_outcome: '◌',
      triggered_by: '☄',
      resistance_against: '⟂',
      'active-project': '✶',
      'core-infrastructure': '✦',
      qualifies: '◇',
      relates_to: '·',
    };
    const THEME_PRESETS = {
      baseline: {
        id: 'baseline',
        title: 'Atlas Graph',
        subtitle: 'Deterministic clusters, semantic wires, and camera-state links you can share.',
        surveyMark: '◎',
        surveyTitle: 'Atlas Graph',
        folderMark: '•',
        legendStyle: 'swatch',
        labelSigils: false,
        starfieldOpacity: 0.08,
        starfieldSize: 2.8,
        showBiomes: false,
        showSurveyGrid: false,

        // v0.5 compliance markers — make it obvious this preset understands the
        // graph-workspace / provenance era of the renderer.
        themeApiVersion: 'v0.5',
        templateCompliance: ['v0.3', 'v0.4', 'v0.5'],

        // v0.4 feature flags — reserve explicit hooks for newer atlas surfaces
        temporalPatternSignals: false,
        pluginManifestStatus: false,
        patternCacheHints: false,

        // v0.5 feature flags — graph-as-workspace behavior
        provenanceEdgeStyles: true,
        profilePredicatePalette: true,
        traceAnimation: true,
        discoverOverlayInteractions: true,
        unreviewedFilter: true,
        workspaceEditing: true,
      },
      astral: {
        id: 'astral',
        title: 'Astral Survey',
        subtitle: 'Memory rendered as a navigable star chart: sectors, routes, beacons, and hidden currents.',
        surveyMark: '✦',
        surveyTitle: 'Astral Survey',
        folderMark: '✶',
        legendStyle: 'glyph',
        labelSigils: true,
        starfieldOpacity: 0.34,
        starfieldSize: 3.7,
        showBiomes: true,
        showSurveyGrid: true,

        // v0.5 compliance markers — make it obvious this preset understands the
        // graph-workspace / provenance era of the renderer.
        themeApiVersion: 'v0.5',
        templateCompliance: ['v0.3', 'v0.4', 'v0.5'],

        // v0.4 feature flags — reserve explicit hooks for newer atlas surfaces
        temporalPatternSignals: false,
        pluginManifestStatus: false,
        patternCacheHints: false,

        // v0.5 feature flags — graph-as-workspace behavior
        provenanceEdgeStyles: true,
        profilePredicatePalette: true,
        traceAnimation: true,
        discoverOverlayInteractions: true,
        unreviewedFilter: true,
        workspaceEditing: true,
      },
    };
    const THEME_TYPE_GLYPHS = {
      baseline: {
        person: '●',
        project: '■',
        agent: '▣',
        goal: '◆',
        session: '◌',
        daily: '◐',
        learning: '◇',
        index: '◈',
        task: '▲',
        cart: '·',
      },
      astral: {
        person: '☉',
        project: '🜨',
        agent: '🝩',
        goal: '🜍',
        session: '🜄',
        daily: '🝰',
        learning: '🜁',
        index: '🜔',
        task: '🜂',
        cart: '🜳',
      },
    };
    const biomeColors = {
      projects: '#f0c46c',
      entities: '#8ec1ff',
      daily: '#cf9fff',
      agents: '#78e2ff',
      tasks: '#ffb86e',
      goals: '#9ae89a',
      readings: '#f3df9a',
      learning: '#f3df9a',
      notes: '#93a7c9',
    };
    const glyphScaleByFamily = {
      person: 3.15,
      project: 3.05,
      agent: 3.05,
      goal: 3.1,
      session: 2.9,
      daily: 2.95,
      learning: 2.9,
      index: 2.95,
      task: 2.95,
      cart: 2.85,
    };
    const haloScaleByFamily = {
      person: 6.2,
      project: 5.8,
      agent: 5.7,
      goal: 5.9,
      session: 5.4,
      daily: 5.4,
      learning: 5.4,
      index: 5.4,
      task: 5.4,
      cart: 5.2,
    };
    const typeColors = Object.fromEntries(atlasGraphPayload.nodes.map((node) => [node.type, node.type_color || node.color]));
    const SESSION_STORAGE_KEY = 'atlas.graph.showSessions';
    const LABEL_STORAGE_KEY = 'atlas.graph.showLabels';
    const PRIVACY_MODE_KEY = 'atlas.graph.privacyMode';
    const WIRES_STORAGE_KEY = 'atlas.graph.showWires';
    const THEME_STORAGE_KEY = 'atlas.graph.themePreset';
    const graphConfig = atlasGraphPayload.graph_config || {};
    const privacyConfig = graphConfig.privacy || {};
    const NEVER_REDACT_IDS = new Set((privacyConfig.never_redact_ids || []).map((value) => String(value).toLowerCase()));
    const ALWAYS_VISIBLE_PEOPLE = new Set((graphConfig.always_visible_people || []).map((value) => String(value).toLowerCase()));
    const VISIBLE_PEOPLE = new Set((graphConfig.visible_people || []).map((value) => String(value).toLowerCase()));
    const HIDDEN_PEOPLE = new Set((graphConfig.hidden_people || []).map((value) => String(value).toLowerCase()));
    const PRIVACY_MODES = new Set(['off', 'names', 'names_relationships', 'full']);
    const DEFAULT_PRIVACY_MODE = PRIVACY_MODES.has(privacyConfig.mode) ? privacyConfig.mode : 'off';

    const themeSelect = document.getElementById('theme-picker');
    const searchInput = document.getElementById('search');
    const folderChipList = document.getElementById('folder-chip-list');
    const privacyModeSelect = document.getElementById('privacy-mode');
    const showLabelsToggle = document.getElementById('show-labels');
    const showSessionsToggle = document.getElementById('show-sessions');
    const showWiresToggle = document.getElementById('show-wires');
    const showUnreviewedOnlyToggle = document.getElementById('show-unreviewed-only');
    const traceModeToggle = document.getElementById('trace-mode');
    const discoverOverlayToggle = document.getElementById('discover-overlay');
    const nodeCountEl = document.getElementById('node-count');
    const edgeCountEl = document.getElementById('edge-count');
    const typeCountEl = document.getElementById('type-count');
    const matchCountEl = document.getElementById('match-count');
    const legendEl = document.getElementById('legend');
    const predicateLegendEl = document.getElementById('predicate-legend');
    const typeBrowserTitleEl = document.getElementById('type-browser-title');
    const typeNodeListEl = document.getElementById('type-node-list');
    const atlasRootEl = document.getElementById('atlas-root');
    const graphTitleEl = document.getElementById('graph-title');
    const graphSubtitleEl = document.getElementById('graph-subtitle');
    const surveyMarkEl = document.getElementById('survey-mark');
    const surveyTitleEl = document.getElementById('survey-title');
    const selectionStatusEl = document.getElementById('selection-status');
    const pendingReviewStatusEl = document.getElementById('pending-review-status');
    const detailTitleEl = document.getElementById('detail-title');
    const detailSubtitleEl = document.getElementById('detail-subtitle');
    const detailPreviewEl = document.getElementById('detail-preview');
    const detailPathEl = document.getElementById('detail-path');
    const detailTagsEl = document.getElementById('detail-tags');
    const detailEmotionalEl = document.getElementById('detail-emotional');
    const detailEmotionalNoteEl = document.getElementById('detail-emotional-note');
    const runTraceButton = document.getElementById('run-trace');
    const toggleAddWireButton = document.getElementById('toggle-add-wire');
    const discoverFromNodeButton = document.getElementById('discover-from-node');
    const addWireFormEl = document.getElementById('add-wire-form');
    const addWireTargetEl = document.getElementById('add-wire-target');
    const addWirePredicateEl = document.getElementById('add-wire-predicate');
    const addWireWeightEl = document.getElementById('add-wire-weight');
    const addWireWeightLabelEl = document.getElementById('add-wire-weight-label');
    const submitAddWireButton = document.getElementById('submit-add-wire');
    const cancelAddWireButton = document.getElementById('cancel-add-wire');
    const neighborListEl = document.getElementById('neighbor-list');
    const incomingWireListEl = document.getElementById('incoming-wire-list');
    const outgoingWireListEl = document.getElementById('outgoing-wire-list');
    const sessionMentionsEl = document.getElementById('session-mentions');
    const edgeDetailTitleEl = document.getElementById('edge-detail-title');
    const edgeDetailMetaEl = document.getElementById('edge-detail-meta');
    const edgePredicateEl = document.getElementById('edge-predicate');
    const edgeWeightEl = document.getElementById('edge-weight');
    const edgeWeightLabelEl = document.getElementById('edge-weight-label');
    const edgeConfidenceEl = document.getElementById('edge-confidence');
    const edgeNoteEl = document.getElementById('edge-note');
    const saveEdgeButton = document.getElementById('save-edge');
    const markEdgeReviewedButton = document.getElementById('mark-edge-reviewed');
    const deleteEdgeButton = document.getElementById('delete-edge');
    const discoverDetailTitleEl = document.getElementById('discover-detail-title');
    const discoverDetailMetaEl = document.getElementById('discover-detail-meta');
    const discoverPredicateEl = document.getElementById('discover-predicate');
    const discoverWeightEl = document.getElementById('discover-weight');
    const discoverWeightLabelEl = document.getElementById('discover-weight-label');
    const discoverConfidenceEl = document.getElementById('discover-confidence');
    const discoverNoteEl = document.getElementById('discover-note');
    const acceptDiscoverButton = document.getElementById('accept-discover');
    const rejectDiscoverButton = document.getElementById('reject-discover');
    const openNoteEl = document.getElementById('open-note');
    const canvasHost = document.getElementById('graph-canvas');
    const labelLayer = document.getElementById('label-layer');
    const graphTooltipEl = document.getElementById('graph-tooltip');
    const nodeIdOptionsEl = document.getElementById('node-id-options');
    const helpOverlay = document.getElementById('help-overlay');
    const graphErrorEl = document.getElementById('graph-error');
    const toggleHelpButton = document.getElementById('toggle-help');
    const closeHelpButton = document.getElementById('close-help');
    const showAllFoldersButton = document.getElementById('show-all-folders');

    function showGraphError(error) {
      const message = error instanceof Error
        ? `${error.name}: ${error.message}`
        : String(error || 'Unknown graph error');
      graphErrorEl.hidden = false;
      graphErrorEl.innerHTML = `<strong>Graph Render Error</strong>${message}`;
      window.__graphLastError = message;
    }

    window.addEventListener('error', (event) => {
      if (event.error) {
        showGraphError(event.error);
      }
    });

    window.addEventListener('unhandledrejection', (event) => {
      showGraphError(event.reason);
    });

    function normalizeThemeName(themeName) {
      return String(themeName || '').trim().toLowerCase();
    }

    function registerBuiltInThemes() {
      window.CART_THEMES.registerBuiltIn({
        id: 'baseline',
        preset: THEME_PRESETS.baseline,
        glyphs: THEME_TYPE_GLYPHS.baseline,
      });
      window.CART_THEMES.registerBuiltIn({
        id: 'astral',
        preset: THEME_PRESETS.astral,
        glyphs: THEME_TYPE_GLYPHS.astral,
        wireAspects: ASTRAL_WIRE_ASPECTS,
      });
    }

    registerBuiltInThemes();

    function availableThemeVariants() {
      const variants = window.CART_THEMES?.list?.() || [];
      return variants.length ? variants : [
        {
          id: 'baseline',
          preset: THEME_PRESETS.baseline,
          glyphs: THEME_TYPE_GLYPHS.baseline,
          wireAspects: {},
          runtime: {},
        },
      ];
    }

    function resolveThemeVariant(themeName) {
      return (
        window.CART_THEMES?.get?.(normalizeThemeName(themeName))
        || window.CART_THEMES?.get?.('baseline')
        || {
          id: 'baseline',
          preset: THEME_PRESETS.baseline,
          glyphs: THEME_TYPE_GLYPHS.baseline,
          wireAspects: {},
          runtime: {},
        }
      );
    }

    function glyphFamilyForType(typeName) {
      if (typeName === 'person') {
        return 'person';
      }
      if (typeName === 'project') {
        return 'project';
      }
      if (typeName === 'goal') {
        return 'goal';
      }
      if (typeName === 'daily') {
        return 'daily';
      }
      if (typeName === 'session') {
        return 'session';
      }
      if (typeName.startsWith('agent-')) {
        return 'agent';
      }
      if (typeName === 'learning-topic' || typeName === 'reference' || typeName === 'ref' || typeName === 'skill-spec') {
        return 'learning';
      }
      if (typeName === 'task-list' || typeName === 'task-intake') {
        return 'task';
      }
      if (typeName === 'index' || typeName === 'registry' || typeName === 'master-summary') {
        return 'index';
      }
      return 'cart';
    }

    function glyphForType(typeName) {
      const family = glyphFamilyForType(typeName);
      return activeTypeGlyphs[family] || activeTypeGlyphs.cart || '·';
    }

    function wireAspectForEdge(edge) {
      return activeWireAspects[edge.predicate] || '';
    }

 // PLUGIN_HOOK:wire_label
 function wireLabelText(edge) {
 const emotionalOn = typeof window._etEmotionalStylingOn === 'function' && window._etEmotionalStylingOn();
 const pluginPreds = (graphConfig.plugin_predicates || {});
 const predDef = pluginPreds[edge.predicate];

 // Emotional label: "predicate · state_modifiers · note_snippet"
 if (emotionalOn && predDef) {
 let parts = [predDef.label || edge.predicate.replaceAll('_', ' ')];
 if (edge.state_modifiers) {
 parts = parts.concat(edge.state_modifiers.split(',').map(m => m.trim()));
 }
 if (edge.note && edge.privacy !== 'public') {
 let snippet = edge.note;
 if (snippet.length > 60) snippet = snippet.substring(0, 57).trim() + '…';
 parts.push(snippet);
 } else if (edge.note && edge.privacy === 'public') {
 // public tier: predicate only, no note
 }
 return parts.join(' · ');
 }

 // When emotional toggle is OFF and this is a plugin predicate,
 // show generic "relates to" instead of the love spectrum term
 if (!emotionalOn && predDef && predDef.category === 'love_spectrum') {
 return 'relates to';
 }

 // Default: aspect + predicate name
 const aspect = wireAspectForEdge(edge);
 if (aspect) {
 return `${aspect} ${edge.predicate.replaceAll('_', ' ')}`;
 }
 return edge.predicate.replaceAll('_', ' ');
 }

 // Emotional styling: swap edge colors and labels when toggle is on
 window._cartographerApplyEmotionalStyling = function(enabled) {
 const pluginPreds = (graphConfig.plugin_predicates || {});
 const hasPlugins = Object.keys(pluginPreds).length > 0;
 if (!hasPlugins) return;

 for (const edge of edges) {
 if (!edge.isWire) continue;
 const predDef = pluginPreds[edge.predicate];

 if (enabled && predDef) {
 // Apply plugin predicate color
 const newColor = new THREE.Color(predDef.color || '#71717a');
 edge.baseColor = newColor;
 edge.material.color.copy(newColor);
 if (edge.markerMaterial) edge.markerMaterial.color.copy(newColor);
 // Apply thickness (as opacity visual cue since Three.js lines don't have width per-edge easily)
 edge.material.opacity = Math.min(1.0, 0.5 + (predDef.thickness || 1) * 0.2);
 } else if (predDef) {
 // Love spectrum edge with toggle OFF: revert to neutral zinc (same as relates_to_person)
 const neutralColor = new THREE.Color(predicateColors['relates_to_person'] || '#71717a');
 edge.baseColor = neutralColor;
 edge.material.color.copy(neutralColor);
 if (edge.markerMaterial) edge.markerMaterial.color.copy(neutralColor);
 edge.material.opacity = edge.isWire ? (usingThemeSigils ? 0.84 : 0.76) : 0.28;
 } else {
 // Non-plugin edge: revert to original predicate color
 const origColor = new THREE.Color(predicateColors[edge.predicate] || '#f0b35f');
 edge.baseColor = origColor;
 edge.material.color.copy(origColor);
 if (edge.markerMaterial) edge.markerMaterial.color.copy(origColor);
 edge.material.opacity = edge.isWire ? (usingThemeSigils ? 0.84 : 0.76) : 0.28;
 }

 // Update label text
 if (edge.labelEl && edge.labelEl.style.display !== 'none') {
 edge.labelEl.textContent = wireLabelText(edge);
 // Color the label to match
 if (enabled && predDef) {
 edge.labelEl.style.color = predDef.color || '#f7ebc8';
 edge.labelEl.style.borderColor = (predDef.color || '#71717a') + '30';
 } else {
 edge.labelEl.style.color = '';
 edge.labelEl.style.borderColor = '';
 }
 }
 }
 };

    const storedThemePreset = normalizeThemeName(window.localStorage.getItem(THEME_STORAGE_KEY) || '');
    const requestedThemePreset = storedThemePreset || normalizeThemeName(graphConfig.theme_preset || 'baseline');
    const activeThemeVariant = resolveThemeVariant(requestedThemePreset);
    const activeTheme = activeThemeVariant.preset || THEME_PRESETS.baseline;
    const activeTypeGlyphs = activeThemeVariant.glyphs || THEME_TYPE_GLYPHS.baseline;
    const activeWireAspects = activeThemeVariant.wireAspects || {};
    const activeThemeRuntime = activeThemeVariant.runtime || {};
    const usingThemeSigils = activeTheme.id !== 'baseline';
    document.body.dataset.theme = activeTheme.id;
    graphTitleEl.textContent = activeTheme.title || activeTheme.id || 'Atlas Graph';
    graphSubtitleEl.textContent = activeTheme.subtitle || '';
    surveyMarkEl.textContent = activeTheme.surveyMark || '◎';
    surveyTitleEl.textContent = activeTheme.surveyTitle || graphTitleEl.textContent;

    function renderThemePicker() {
      themeSelect.innerHTML = '';
      for (const variant of availableThemeVariants()) {
        const option = document.createElement('option');
        option.value = variant.id;
        option.textContent = variant.preset?.title || variant.id;
        themeSelect.appendChild(option);
      }
      themeSelect.value = activeTheme.id;
    }

    renderThemePicker();

    function syncRangeLabel(input, label) {
      label.textContent = Number(input.value || 0).toFixed(2);
    }

    function populatePredicateSelect(selectEl, selectedValue = '') {
      if (!selectEl) {
        return;
      }
      const currentValue = String(selectedValue || '');
      selectEl.innerHTML = '';
      for (const entry of predicatePalette) {
        const option = document.createElement('option');
        option.value = entry.name;
        option.textContent = entry.name;
        selectEl.appendChild(option);
      }
      if (currentValue && Array.from(selectEl.options).some((option) => option.value === currentValue)) {
        selectEl.value = currentValue;
      } else if (selectEl.options.length) {
        selectEl.value = selectEl.options[0].value;
      }
    }

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
      hiddenFolders: new Set(),
      hiddenTypes: new Set(),
      hiddenPredicates: new Set(),
      browserType: null,
      showSessions: storageBool(SESSION_STORAGE_KEY, false),
      showLabels: storageBool(LABEL_STORAGE_KEY, false),
      privacyMode: PRIVACY_MODES.has(window.localStorage.getItem(PRIVACY_MODE_KEY) || '')
        ? (window.localStorage.getItem(PRIVACY_MODE_KEY) || '')
        : DEFAULT_PRIVACY_MODE,
      showWires: storageBool(WIRES_STORAGE_KEY, true),
      showUnreviewedOnly: false,
      traceMode: false,
      discoverOverlay: false,
      traceData: null,
      traceStartedAt: 0,
      serverLastRegen: null,
    };

    const initialHashState = readHashState();
    if (initialHashState) {
      state.search = typeof initialHashState.search === 'string' ? initialHashState.search : '';
      state.browserType = typeof initialHashState.browserType === 'string' ? initialHashState.browserType : null;
      state.showSessions = initialHashState.showSessions ?? state.showSessions;
      state.showLabels = initialHashState.showLabels ?? state.showLabels;
      state.privacyMode = PRIVACY_MODES.has(initialHashState.privacyMode) ? initialHashState.privacyMode : state.privacyMode;
      state.showWires = initialHashState.showWires ?? state.showWires;
      for (const folderName of initialHashState.hiddenFolders || []) {
        state.hiddenFolders.add(folderName);
      }
      for (const typeName of initialHashState.hiddenTypes || []) {
        state.hiddenTypes.add(typeName);
      }
    }

    searchInput.value = state.search;
    showLabelsToggle.checked = state.showLabels;
    privacyModeSelect.value = state.privacyMode;
    showSessionsToggle.checked = state.showSessions;
    showWiresToggle.checked = state.showWires;
    showUnreviewedOnlyToggle.checked = state.showUnreviewedOnly;
    traceModeToggle.checked = state.traceMode;
    discoverOverlayToggle.checked = state.discoverOverlay;
    populatePredicateSelect(addWirePredicateEl);
    populatePredicateSelect(edgePredicateEl);
    populatePredicateSelect(discoverPredicateEl);
    syncRangeLabel(addWireWeightEl, addWireWeightLabelEl);
    syncRangeLabel(edgeWeightEl, edgeWeightLabelEl);
    syncRangeLabel(discoverWeightEl, discoverWeightLabelEl);

    function syncCompactToggles() {
      for (const input of [showWiresToggle, showSessionsToggle, showLabelsToggle, showUnreviewedOnlyToggle, traceModeToggle, discoverOverlayToggle]) {
        input.closest('.toggle')?.classList.toggle('active', input.checked);
      }
    }

    syncCompactToggles();

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
      displayColor: new THREE.Color(node.color).lerp(
        new THREE.Color(usingThemeSigils ? '#fff4d4' : '#f4f8ff'),
        usingThemeSigils ? 0.24 : 0.12,
      ),
      glowColor: new THREE.Color(node.color).lerp(
        new THREE.Color(usingThemeSigils ? '#ffc987' : '#9fc8ff'),
        usingThemeSigils ? 0.18 : 0.08,
      ),
      baseRadius: node.base_radius || (4.8 + Math.min(node.degree, 14) * 0.55),
      radius: 0,
      renderScale: 1,
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
    for (const node of sortNodes(nodes)) {
      const option = document.createElement('option');
      option.value = node.id;
      option.label = node.title || node.id;
      nodeIdOptionsEl.appendChild(option);
    }
    const folderNames = Array.from(new Set(nodes.map((node) => node.folder).filter(Boolean))).sort((a, b) => a.localeCompare(b));
    const folderOrder = new Map(folderNames.map((folder, index) => [folder, index]));
    const folderGlyphFamilyCache = new Map();

    function folderGlyphForName(folder) {
      if (!folder) {
        return activeTheme.folderMark || '•';
      }
      if (!folderGlyphFamilyCache.has(folder)) {
        const counts = new Map();
        for (const node of nodes) {
          if (node.folder !== folder) {
            continue;
          }
          const family = glyphFamilyForType(node.type);
          counts.set(family, (counts.get(family) || 0) + 1);
        }
        const winner = [...counts.entries()].sort((left, right) =>
          right[1] - left[1] || left[0].localeCompare(right[0])
        )[0]?.[0] || null;
        folderGlyphFamilyCache.set(folder, winner);
      }
      const family = folderGlyphFamilyCache.get(folder);
      return (family && activeTypeGlyphs[family]) || activeTheme.folderMark || '•';
    }
    const orderedPeople = nodes
      .filter((node) => node.type === 'person')
      .sort((a, b) => {
        const aRank = Number.isFinite(a.person_order_index) ? a.person_order_index : Number.MAX_SAFE_INTEGER;
        const bRank = Number.isFinite(b.person_order_index) ? b.person_order_index : Number.MAX_SAFE_INTEGER;
        if (aRank !== bRank) {
          return aRank - bRank;
        }
        return a.title.localeCompare(b.title) || a.id.localeCompare(b.id);
      });
    const personAliasById = new Map(orderedPeople.map((node, index) => [node.id, node.privacy_alias || `Person ${index + 1}`]));
    const redactionTerms = [];
    for (const node of orderedPeople) {
      if (NEVER_REDACT_IDS.has(node.id.toLowerCase())) {
        continue;
      }
      redactionTerms.push({ term: node.title, node });
      redactionTerms.push({ term: node.id, node });
    }
    redactionTerms.sort((left, right) => right.term.length - left.term.length);
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
            ? predicateColors[edge.predicate] || '#f0b35f'
            : '#6e7b96'
        ),
        line: null,
        material: null,
        marker: null,
        markerMaterial: null,
        labelEl: null,
        markerT: 0.62,
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
        opacity: activeTheme.starfieldOpacity,
        size: activeTheme.starfieldSize,
        sizeAttenuation: true,
      })
    );
    scene.add(stars);
    stars.visible = activeTheme.starfieldOpacity > 0;

    function unitLoopGeometry(points = 72, wobble = 0) {
      const vertices = [];
      for (let index = 0; index < points; index += 1) {
        const theta = (index / points) * Math.PI * 2;
        const wobbleFactor = wobble ? (1 + Math.sin(theta * 3) * wobble) : 1;
        vertices.push(new THREE.Vector3(Math.cos(theta) * wobbleFactor, 0, Math.sin(theta) * wobbleFactor));
      }
      return new THREE.BufferGeometry().setFromPoints(vertices);
    }

    function makeDustGeometry(count = 36) {
      const vertices = [];
      for (let index = 0; index < count; index += 1) {
        const angle = Math.random() * Math.PI * 2;
        const radius = Math.sqrt(Math.random()) * 0.95;
        const vertical = (Math.random() - 0.5) * 0.34;
        vertices.push(
          new THREE.Vector3(
            Math.cos(angle) * radius,
            vertical,
            Math.sin(angle) * radius * (0.72 + Math.random() * 0.24),
          )
        );
      }
      return new THREE.BufferGeometry().setFromPoints(vertices);
    }

    const glyphTextureCache = new Map();
    let haloTexture = null;

    function glyphCanvasKey(typeName) {
      return `${activeTheme.id}:${typeName}`;
    }

    function createHaloTexture() {
      if (haloTexture) {
        return haloTexture;
      }
      const canvas = document.createElement('canvas');
      canvas.width = 256;
      canvas.height = 256;
      const ctx = canvas.getContext('2d');
      if (!ctx) {
        haloTexture = new THREE.CanvasTexture(canvas);
        haloTexture.needsUpdate = true;
        return haloTexture;
      }
      const gradient = ctx.createRadialGradient(128, 128, 10, 128, 128, 128);
      gradient.addColorStop(0, 'rgba(255,255,255,0.95)');
      gradient.addColorStop(0.25, 'rgba(255,255,255,0.42)');
      gradient.addColorStop(0.55, 'rgba(255,255,255,0.14)');
      gradient.addColorStop(1, 'rgba(255,255,255,0)');
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, 256, 256);
      haloTexture = new THREE.CanvasTexture(canvas);
      haloTexture.needsUpdate = true;
      return haloTexture;
    }

    let wireMarkerTexture = null;

    function createWireMarkerTexture() {
      if (wireMarkerTexture) {
        return wireMarkerTexture;
      }
      const canvas = document.createElement('canvas');
      canvas.width = 192;
      canvas.height = 192;
      const ctx = canvas.getContext('2d');
      if (!ctx) {
        wireMarkerTexture = new THREE.CanvasTexture(canvas);
        wireMarkerTexture.needsUpdate = true;
        return wireMarkerTexture;
      }
      ctx.translate(96, 96);
      ctx.fillStyle = 'rgba(255,255,255,0.96)';
      ctx.beginPath();
      ctx.moveTo(-54, -26);
      ctx.lineTo(56, 0);
      ctx.lineTo(-54, 26);
      ctx.closePath();
      ctx.fill();
      wireMarkerTexture = new THREE.CanvasTexture(canvas);
      wireMarkerTexture.needsUpdate = true;
      return wireMarkerTexture;
    }

    function drawOrbitalTicks(ctx, radius, count, length, lineWidth = 8) {
      ctx.save();
      ctx.lineWidth = lineWidth;
      for (let index = 0; index < count; index += 1) {
        const theta = (index / count) * Math.PI * 2;
        const inner = radius - length;
        ctx.beginPath();
        ctx.moveTo(Math.cos(theta) * inner, Math.sin(theta) * inner);
        ctx.lineTo(Math.cos(theta) * radius, Math.sin(theta) * radius);
        ctx.stroke();
      }
      ctx.restore();
    }

    function drawDiamond(ctx, radius) {
      ctx.beginPath();
      ctx.moveTo(0, -radius);
      ctx.lineTo(radius, 0);
      ctx.lineTo(0, radius);
      ctx.lineTo(-radius, 0);
      ctx.closePath();
      ctx.stroke();
    }

    function drawGoalReticle(ctx, radius) {
      ctx.beginPath();
      ctx.arc(0, 0, radius, 0, Math.PI * 2);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(-radius - 18, 0);
      ctx.lineTo(-radius + 6, 0);
      ctx.moveTo(radius - 6, 0);
      ctx.lineTo(radius + 18, 0);
      ctx.moveTo(0, -radius - 18);
      ctx.lineTo(0, -radius + 6);
      ctx.moveTo(0, radius - 6);
      ctx.lineTo(0, radius + 18);
      ctx.stroke();
    }

    function drawTriangle(ctx, radius, inverted = false) {
      const top = inverted ? radius : -radius;
      const base = inverted ? -radius : radius;
      ctx.beginPath();
      ctx.moveTo(0, top);
      ctx.lineTo(radius * 0.92, base * 0.72);
      ctx.lineTo(-radius * 0.92, base * 0.72);
      ctx.closePath();
      ctx.stroke();
    }

    function drawCross(ctx, size) {
      ctx.beginPath();
      ctx.moveTo(-size, 0);
      ctx.lineTo(size, 0);
      ctx.moveTo(0, -size);
      ctx.lineTo(0, size);
      ctx.stroke();
    }

    function drawCrucible(ctx) {
      ctx.beginPath();
      ctx.moveTo(-74, 56);
      ctx.quadraticCurveTo(-64, -12, -36, -68);
      ctx.lineTo(36, -68);
      ctx.quadraticCurveTo(64, -12, 74, 56);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(-48, 22);
      ctx.lineTo(48, 22);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(-18, 56);
      ctx.lineTo(18, 56);
      ctx.stroke();
    }

    function drawDailyMark(ctx) {
      ctx.beginPath();
      ctx.arc(0, -8, 64, Math.PI * 0.18, Math.PI * 0.82);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(0, -12);
      ctx.lineTo(0, 76);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(-26, 46);
      ctx.lineTo(26, 46);
      ctx.stroke();
    }

    function drawMetalMark(ctx) {
      drawDiamond(ctx, 72);
      ctx.beginPath();
      ctx.moveTo(-72, 0);
      ctx.lineTo(72, 0);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(0, -72);
      ctx.lineTo(0, 72);
      ctx.stroke();
    }

    function createGlyphTexture(typeName) {
      const cacheKey = glyphCanvasKey(typeName);
      if (glyphTextureCache.has(cacheKey)) {
        return glyphTextureCache.get(cacheKey);
      }
      const canvas = document.createElement('canvas');
      canvas.width = 256;
      canvas.height = 256;
      const ctx = canvas.getContext('2d');
      if (ctx) {
        ctx.translate(128, 128);
        ctx.strokeStyle = 'rgba(255,255,255,0.95)';
        ctx.fillStyle = 'rgba(255,255,255,1)';
        ctx.lineJoin = 'round';
        ctx.lineCap = 'round';
        ctx.lineWidth = 8;
        const family = glyphFamilyForType(typeName);
        const themeId = activeTheme.id;

        if (themeId === 'astral') {
          // ── ASTRAL: hand-drawn celestial sigils ──────────────────────────
          switch (family) {
            case 'person':
              ctx.beginPath();
              ctx.arc(0, 0, 72, 0, Math.PI * 2);
              ctx.stroke();
              drawOrbitalTicks(ctx, 98, 12, 16, 7);
              ctx.beginPath();
              ctx.arc(0, 0, 18, 0, Math.PI * 2);
              ctx.fill();
              break;
            case 'project':
              ctx.beginPath();
              ctx.arc(0, 0, 82, 0, Math.PI * 2);
              ctx.stroke();
              drawCross(ctx, 72);
              break;
            case 'agent':
              drawCrucible(ctx);
              break;
            case 'goal':
              drawDiamond(ctx, 92);
              drawGoalReticle(ctx, 56);
              break;
            case 'session':
              drawTriangle(ctx, 88, true);
              ctx.beginPath();
              ctx.moveTo(0, -84);
              ctx.lineTo(0, -24);
              ctx.stroke();
              break;
            case 'daily':
              drawDailyMark(ctx);
              break;
            case 'learning':
              drawTriangle(ctx, 88, false);
              ctx.beginPath();
              ctx.moveTo(-58, 18);
              ctx.lineTo(58, 18);
              ctx.stroke();
              break;
            case 'task':
              drawTriangle(ctx, 94, false);
              break;
            case 'index':
              drawOrbitalTicks(ctx, 96, 4, 22, 8);
              ctx.beginPath();
              ctx.arc(0, 0, 58, 0, Math.PI * 2);
              ctx.stroke();
              ctx.beginPath();
              ctx.moveTo(-42, 0);
              ctx.lineTo(42, 0);
              ctx.stroke();
              break;
            default:
              drawMetalMark(ctx);
              break;
          }
        } else if (themeId === 'synaptic-vesper') {
          // ── VESPER: signal-crest sigils from theme module ─────────────────
          const drawFn = window.__VESPER_SIGILS__?.drawByFamily?.[family];
          if (drawFn) {
            ctx.lineWidth = 9;
            drawFn(ctx);
          } else {
            drawMetalMark(ctx);
          }
        } else {
          // ── UNICODE GLYPH THEMES (cassette, wizard, etc.) ─────────────────
          // Render the Unicode character defined in the theme's glyphs map.
          const glyph = activeTypeGlyphs[family] || activeTheme.folderMark || '•';
          ctx.font = 'bold 128px sans-serif';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillStyle = 'rgba(255,255,255,0.95)';
          ctx.fillText(glyph, 0, 6);
        }
      }

      const texture = new THREE.CanvasTexture(canvas);
      texture.needsUpdate = true;
      glyphTextureCache.set(cacheKey, texture);
      return texture;
    }

    const biomeObjects = new Map();
    const biomeBaseGeometry = unitLoopGeometry(72, 0.04);
    const biomeOuterGeometry = unitLoopGeometry(88, 0.08);
    const biomeDustGeometry = makeDustGeometry(52);

    for (const folder of folderNames) {
      const color = new THREE.Color(biomeColors[folder] || '#93a7c9');
      const group = new THREE.Group();
      const innerRing = new THREE.LineLoop(
        biomeBaseGeometry.clone(),
        new THREE.LineBasicMaterial({
          color: color.clone().lerp(new THREE.Color('#ffffff'), 0.18),
          transparent: true,
          opacity: 0.22,
        }),
      );
      innerRing.rotation.x = Math.PI / 2;
      innerRing.rotation.z = 0.18;
      group.add(innerRing);

      const outerRing = new THREE.LineLoop(
        biomeOuterGeometry.clone(),
        new THREE.LineBasicMaterial({
          color: color.clone().lerp(new THREE.Color('#fff1c5'), 0.28),
          transparent: true,
          opacity: 0.12,
        }),
      );
      outerRing.rotation.x = Math.PI / 2;
      outerRing.rotation.z = -0.24;
      outerRing.scale.set(1.18, 1, 0.88);
      group.add(outerRing);

      const dust = new THREE.Points(
        biomeDustGeometry.clone(),
        new THREE.PointsMaterial({
          color,
          transparent: true,
          opacity: 0.14,
          size: 3.6,
          sizeAttenuation: true,
        }),
      );
      group.add(dust);
      group.visible = false;
      scene.add(group);
      biomeObjects.set(folder, {
        group,
        innerRing,
        outerRing,
        dust,
        color,
        phase: (folderOrder.get(folder) || 0) * 0.7,
      });
    }

    const surveyGrid = [];
    for (const radius of [180, 270, 390]) {
      const line = new THREE.LineLoop(
        unitLoopGeometry(96, 0.015),
        new THREE.LineBasicMaterial({
          color: new THREE.Color('#8fb5ff'),
          transparent: true,
          opacity: radius === 180 ? 0.09 : 0.05,
        }),
      );
      line.rotation.x = Math.PI / 2;
      line.rotation.z = radius === 270 ? 0.22 : -0.14;
      line.scale.set(radius, 1, radius * 0.76);
      line.visible = activeTheme.showSurveyGrid;
      scene.add(line);
      surveyGrid.push(line);
    }

    const sphereGeometry = new THREE.IcosahedronGeometry(1, 3);
    for (const node of nodes) {
      const material = new THREE.MeshStandardMaterial({
        color: node.displayColor.clone(),
        emissive: node.glowColor.clone().multiplyScalar(usingThemeSigils ? 0.22 : 0.16),
        roughness: usingThemeSigils ? 0.2 : 0.3,
        metalness: usingThemeSigils ? 0.18 : 0.08,
        transparent: true,
        opacity: 0.95,
      });
      const mesh = new THREE.Mesh(sphereGeometry, material);
      mesh.userData.node = node;
      mesh.scale.setScalar(node.radius);
      scene.add(mesh);
      node.mesh = mesh;
      node.material = material;
      node.sigil = null;
      node.sigilMaterial = null;
      node.halo = null;
      node.haloMaterial = null;

      if (usingThemeSigils) {
        const haloMaterial = new THREE.SpriteMaterial({
          map: createHaloTexture(),
          color: node.glowColor.clone(),
          transparent: true,
          opacity: 0.18,
          depthWrite: false,
          depthTest: false,
        });
        const halo = new THREE.Sprite(haloMaterial);
        halo.userData.node = node;
        scene.add(halo);
        node.halo = halo;
        node.haloMaterial = haloMaterial;

        const sigilMaterial = new THREE.SpriteMaterial({
          map: createGlyphTexture(node.type),
          color: node.displayColor.clone(),
          transparent: true,
          opacity: 0.96,
          depthWrite: false,
          depthTest: false,
        });
        const sigil = new THREE.Sprite(sigilMaterial);
        sigil.userData.node = node;
        scene.add(sigil);
        node.sigil = sigil;
        node.sigilMaterial = sigilMaterial;

        node.material.opacity = 0.22;
        node.material.depthWrite = true;
        mesh.renderOrder = 1;
        halo.renderOrder = 2;
        sigil.renderOrder = 3;
      }
    }

    for (const edge of edges) {
      const geometry = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(),
        new THREE.Vector3(),
      ]);
      const themedEdgeStyle = edgeStyle(edge);
      const reviewedEdge = themedEdgeStyle.lineStyle !== 'dashed';
      const material = new (reviewedEdge ? THREE.LineBasicMaterial : THREE.LineDashedMaterial)({
        color: edge.baseColor,
        transparent: true,
        opacity: edge.isWire
          ? (reviewedEdge ? (usingThemeSigils ? 0.72 : 0.62) : 0.52) * themedEdgeStyle.opacityMultiplier
          : 0.2,
        dashSize: reviewedEdge ? undefined : 10,
        gapSize: reviewedEdge ? undefined : 6,
      });
      material.linewidth = 1 + (Number(edge.weight || 0.5) * 3);
      const line = new THREE.Line(geometry, material);
      line.userData.edge = edge;
      if (!reviewedEdge && typeof line.computeLineDistances === 'function') {
        line.computeLineDistances();
      }
      scene.add(line);
      edge.line = line;
      edge.material = material;
      edge.lineStyle = themedEdgeStyle.lineStyle;
      if (edge.isWire) {
        const markerMaterial = new THREE.SpriteMaterial({
          map: createWireMarkerTexture(),
          color: edge.baseColor.clone(),
          transparent: true,
          opacity: usingThemeSigils ? 0.58 : 0.36,
          depthWrite: false,
          depthTest: false,
        });
        const marker = new THREE.Sprite(markerMaterial);
        marker.userData.edge = edge;
        scene.add(marker);
        edge.marker = marker;
        edge.markerMaterial = markerMaterial;
        edge.labelEl = document.createElement('div');
        edge.labelEl.className = 'edge-label';
        labelLayer.appendChild(edge.labelEl);
      }
    }

    const raycaster = new THREE.Raycaster();
    raycaster.params.Line = { threshold: 10 };
    const pointer = new THREE.Vector2();
    let selectedNode = null;
    let selectedEdge = null;
    let selectedDiscoverCandidate = null;
    let discoverOverlayData = [];
    let cameraGoal = null;
    let homeTarget = new THREE.Vector3();
    let homePosition = new THREE.Vector3(0, 120, 520);
    let pointerDown = null;
    let moved = false;
    let dragMode = null;

    function clearDiscoverOverlay() {
      for (const candidate of discoverOverlayData) {
        if (candidate.line) {
          scene.remove(candidate.line);
        }
      }
      discoverOverlayData = [];
      if (selectedDiscoverCandidate) {
        selectedDiscoverCandidate = null;
      }
    }

    async function loadDiscoverOverlay(noteId = null) {
      const params = new URLSearchParams({ format: 'json' });
      if (noteId) {
        params.set('note', noteId);
      }
      const response = await fetch(`/api/discover?${params.toString()}`);
      if (!response.ok) {
        throw new Error(`discover overlay failed: ${response.status}`);
      }
      const payload = await response.json();
      clearDiscoverOverlay();
      for (const candidate of payload.candidates || []) {
        const source = nodeById.get(candidate.left_id);
        const target = nodeById.get(candidate.right_id);
        if (!source || !target) {
          continue;
        }
        const geometry = new THREE.BufferGeometry().setFromPoints([
          new THREE.Vector3(),
          new THREE.Vector3(),
        ]);
        const material = new THREE.LineDashedMaterial({
          color: '#f5a623',
          transparent: true,
          opacity: 0.0,
          dashSize: 10,
          gapSize: 6,
        });
        const line = new THREE.Line(geometry, material);
        line.userData.discoverCandidate = candidate;
        scene.add(line);
        if (typeof line.computeLineDistances === 'function') {
          line.computeLineDistances();
        }
        discoverOverlayData.push({
          ...candidate,
          source,
          target,
          line,
          material,
          selectedAt: 0,
        });
      }
      refreshSceneState();
      updateLabels();
      updateDiscoverDetail(selectedDiscoverCandidate);
    }

    function fileHref(path) {
      if (!path) {
        return '#';
      }
      return 'file://' + encodeURI(path);
    }

    function isNeverRedactedNode(node) {
      return !!node && NEVER_REDACT_IDS.has(String(node.id).toLowerCase());
    }

    function personAlias(node) {
      return personAliasById.get(node.id) || 'Person';
    }

    function namePrivacyEnabled() {
      return state.privacyMode === 'names' || state.privacyMode === 'names_relationships';
    }

    function relationshipPrivacyEnabled() {
      return state.privacyMode === 'names_relationships';
    }

    function shouldHidePerson(node) {
      if (!node || node.type !== 'person') {
        return false;
      }
      const id = String(node.id).toLowerCase();
      if (ALWAYS_VISIBLE_PEOPLE.has(id)) {
        return false;
      }
      if (graphConfig.show_people === false) {
        return true;
      }
      if (HIDDEN_PEOPLE.has(id)) {
        return true;
      }
      if (VISIBLE_PEOPLE.size && !VISIBLE_PEOPLE.has(id)) {
        return true;
      }
      return false;
    }

    function shouldRedactLabel(node) {
      if (!node || !namePrivacyEnabled() || isNeverRedactedNode(node)) {
        return false;
      }
      return true;
    }

    function shouldRedactRelationships(node) {
      if (!node || isNeverRedactedNode(node)) {
        return false;
      }
      return relationshipPrivacyEnabled() || state.privacyMode === 'full';
    }

    function shouldFullyRedact(node) {
      if (!node || isNeverRedactedNode(node)) {
        return false;
      }
      return state.privacyMode === 'full';
    }

    function displayNodeIdentifier(node) {
      if (!node) {
        return '—';
      }
      if (shouldFullyRedact(node)) {
        return node.type === 'person' ? personAlias(node) : `${node.type}-${node.typeOrdinal}`;
      }
      if (!shouldRedactLabel(node)) {
        return node.id;
      }
      return node.type === 'person' ? personAlias(node) : redactNames(node.id);
    }

    function escapeRegExp(value) {
      return String(value).replace(/[.*+?^${}()|[\\]\\\\]/g, '\\$&');
    }

    function redactNames(text) {
      let output = String(text || '');
      for (const entry of redactionTerms) {
        const alias = personAlias(entry.node);
        const pattern = new RegExp(`(^|[^A-Za-z0-9])(${escapeRegExp(entry.term)})(?=[^A-Za-z0-9]|$)`, 'gi');
        output = output.replace(pattern, (_, prefix) => `${prefix}${alias}`);
      }
      return output;
    }

    function containsSensitivePersonReference(text) {
      const value = String(text || '').toLowerCase();
      if (!value.trim()) {
        return false;
      }
      return redactionTerms.some((entry) => value.includes(String(entry.term).toLowerCase()));
    }

    function redactRenderedText(text, node, { fullFallback = 'Content redacted by privacy mode.' } = {}) {
      if (!node) {
        return String(text || '');
      }
      if (shouldFullyRedact(node)) {
        return fullFallback;
      }
      if (!namePrivacyEnabled()) {
        return String(text || '');
      }
      return redactNames(text);
    }

    function shouldSuppressPreview(node) {
      if (!node) {
        return false;
      }
      if (shouldFullyRedact(node)) {
        return true;
      }
      if (!relationshipPrivacyEnabled() || isNeverRedactedNode(node)) {
        return false;
      }
      return node.type === 'person'
        || containsSensitivePersonReference(node.title)
        || containsSensitivePersonReference(node.path)
        || containsSensitivePersonReference(node.preview)
        || containsSensitivePersonReference(node.valence_note);
    }

    function displayNodeName(node) {
      if (!node) {
        return 'Nothing selected';
      }
      if (shouldFullyRedact(node)) {
        return node.type === 'person' ? personAlias(node) : `${node.type} ${node.typeOrdinal}`;
      }
      if (node.type === 'person' && shouldRedactLabel(node)) {
        return personAlias(node);
      }
      return shouldRedactLabel(node) ? redactNames(node.title) : node.title;
    }

    function detailTypeLabel(node) {
      const bits = [node.type];
      if (node.status) {
        bits.push(node.status);
      }
      if (node.folder) {
        bits.push(`folder ${node.folder}`);
      }
      return bits.join(' · ');
    }

    function edgeMetaLine(edge) {
      const bits = [];
      if (edge.weight !== null && edge.weight !== undefined) {
        bits.push(`weight ${Number(edge.weight).toFixed(1)}`);
      }
      if (!relationshipPrivacyEnabled() && edge.relationship && edge.relationship !== edge.predicate) {
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
      if (edge.author) {
        bits.push(`author ${edge.author}`);
      }
      if (edge.method) {
        bits.push(`method ${edge.method}`);
      }
      if (edge.reviewed === false) {
        bits.push('unreviewed');
      } else if (edge.reviewed === true) {
        bits.push('reviewed');
      }
      return bits.join(' · ') || 'wire';
    }

    function edgeReviewed(edge) {
      return edge.reviewed === true || edge.method === 'manual' || (!edge.method && edge.reviewed !== false);
    }

    function edgeStyle(edge) {
      const fallback = edgeReviewed(edge)
        ? { lineStyle: 'solid', opacityMultiplier: 1.0 }
        : { lineStyle: 'dashed', opacityMultiplier: 0.7 };
      if (typeof activeThemeRuntime.getEdgeStyle !== 'function') {
        return fallback;
      }
      try {
        const custom = activeThemeRuntime.getEdgeStyle(edge, { edgeReviewed });
        return {
          lineStyle: custom?.lineStyle || custom?.['line-style'] || fallback.lineStyle,
          opacityMultiplier: Number(custom?.opacityMultiplier ?? custom?.opacity ?? fallback.opacityMultiplier),
        };
      } catch (_error) {
        return fallback;
      }
    }

    function candidateReasonText(candidate) {
      const reasons = candidate?.reasons || {};
      const bits = [];
      if (Array.isArray(reasons.tags) && reasons.tags.length) {
        bits.push(`#${reasons.tags.slice(0, 3).join(', #')}`);
      }
      if (Array.isArray(reasons.keywords) && reasons.keywords.length) {
        bits.push(`keyword "${reasons.keywords.slice(0, 4).join('", "')}"`);
      }
      if (Array.isArray(reasons.links) && reasons.links.length) {
        bits.push(`links ${reasons.links.slice(0, 3).join(', ')}`);
      }
      if (Array.isArray(reasons.frontmatter) && reasons.frontmatter.length) {
        bits.push(`frontmatter ${reasons.frontmatter.slice(0, 3).join(', ')}`);
      }
      if (reasons.type_match) {
        bits.push('matching note type');
      }
      return bits.join(' · ') || 'shared context detected';
    }

    function showGraphTooltip(text, event) {
      if (!text || !event) {
        graphTooltipEl.hidden = true;
        graphTooltipEl.textContent = '';
        return;
      }
      graphTooltipEl.hidden = false;
      graphTooltipEl.textContent = text;
      graphTooltipEl.style.left = `${event.clientX - canvasHost.getBoundingClientRect().left}px`;
      graphTooltipEl.style.top = `${event.clientY - canvasHost.getBoundingClientRect().top}px`;
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

    function labelTextForNode(node) {
      const text = displayNodeName(node);
      if (!activeTheme.labelSigils) {
        return text;
      }
      return `${glyphForType(node.type)} ${text}`;
    }

    function metadataChipValue(node, value) {
      if (value === null || value === undefined || value === '') {
        return null;
      }
      if (shouldFullyRedact(node)) {
        return null;
      }
      return redactRenderedText(String(value), node, { fullFallback: '' }) || null;
    }

    function activeNodes() {
      return nodes.filter((node) => {
        if (state.hiddenTypes.has(node.type)) {
          return false;
        }
        if (node.folder && state.hiddenFolders.has(node.folder)) {
          return false;
        }
        if (shouldHidePerson(node)) {
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

    function visibleNodesForBiome(folder) {
      return nodes.filter((node) =>
        node.folder === folder
        && !state.hiddenTypes.has(node.type)
        && (state.showSessions || !node.is_session)
        && !shouldHidePerson(node)
        && !state.hiddenFolders.has(folder)
      );
    }

    function updateBiomes() {
      for (const [folder, biome] of biomeObjects.entries()) {
        const folderNodes = visibleNodesForBiome(folder);
        if (!activeTheme.showBiomes || !folderNodes.length) {
          biome.group.visible = false;
          continue;
        }
        const center = new THREE.Vector3();
        folderNodes.forEach((node) => center.add(node.position));
        center.divideScalar(folderNodes.length);
        let maxDistance = 24;
        for (const node of folderNodes) {
          maxDistance = Math.max(maxDistance, center.distanceTo(node.position) + node.radius * 1.25);
        }
        biome.group.visible = true;
        biome.group.position.copy(center);
        biome.group.scale.set(maxDistance * 1.15, Math.max(12, maxDistance * 0.18), maxDistance * 0.9);
        biome.group.rotation.y = biome.phase;
      }
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
          if (node.sigil) {
            node.sigil.position.copy(node.position);
            const glyphFamily = glyphFamilyForType(node.type);
            const glyphScale = glyphScaleByFamily[glyphFamily] || 3;
            node.sigil.scale.set(node.radius * glyphScale, node.radius * glyphScale, 1);
          }
          if (node.halo) {
            node.halo.position.copy(node.position);
            const glyphFamily = glyphFamilyForType(node.type);
            const haloScale = haloScaleByFamily[glyphFamily] || 5.4;
            node.halo.scale.set(node.radius * haloScale, node.radius * haloScale, 1);
          }
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
        if (typeof edge.line.computeLineDistances === 'function') {
          edge.line.computeLineDistances();
        }
        if (edge.marker) {
          const targetPoint = edge.source.position.clone().lerp(edge.target.position, edge.markerT);
          edge.marker.position.copy(targetPoint);
          const markerScale = edge.isWire
            ? ((usingThemeSigils ? 16 : 12) + Number(edge.weight || 0.5) * 6)
            : 10;
          edge.marker.scale.set(markerScale, markerScale, 1);
        }
      }
      for (const candidate of discoverOverlayData) {
        const positions = candidate.line.geometry.attributes.position.array;
        positions[0] = candidate.source.position.x;
        positions[1] = candidate.source.position.y;
        positions[2] = candidate.source.position.z;
        positions[3] = candidate.target.position.x;
        positions[4] = candidate.target.position.y;
        positions[5] = candidate.target.position.z;
        candidate.line.geometry.attributes.position.needsUpdate = true;
        candidate.line.geometry.computeBoundingSphere();
        if (typeof candidate.line.computeLineDistances === 'function') {
          candidate.line.computeLineDistances();
        }
      }
      updateBiomes();
      updateHomeCamera();
    }

    function saveToggles() {
      window.localStorage.setItem(SESSION_STORAGE_KEY, state.showSessions ? '1' : '0');
      window.localStorage.setItem(LABEL_STORAGE_KEY, state.showLabels ? '1' : '0');
      window.localStorage.setItem(PRIVACY_MODE_KEY, state.privacyMode);
      window.localStorage.setItem(WIRES_STORAGE_KEY, state.showWires ? '1' : '0');
    }

    function writeHashState() {
      const payload = {
        search: state.search,
        hiddenFolders: [...state.hiddenFolders],
        hiddenTypes: [...state.hiddenTypes],
        browserType: state.browserType,
        showSessions: state.showSessions,
        showLabels: state.showLabels,
        privacyMode: state.privacyMode,
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

    function maskText(text, minLength = 3) {
      if (!text) return '';
      if (text.length <= minLength) return text[0] + '*'.repeat(Math.max(1, text.length - 1));
      return text[0] + '*'.repeat(text.length - 2) + text[text.length - 1];
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
      detailSubtitleEl.textContent = redactRenderedText(detailTypeLabel(node), node, { fullFallback: 'metadata redacted' });
      detailPreviewEl.innerHTML = shouldSuppressPreview(node)
        ? renderPreviewMarkdown(
            shouldFullyRedact(node)
              ? 'Preview redacted by full privacy mode.'
              : 'Preview hidden by name + relationship privacy mode.'
          )
        : renderPreviewMarkdown(redactRenderedText(node.preview || 'No preview available.', node));
      detailPathEl.textContent = shouldFullyRedact(node)
        ? '—'
        : redactRenderedText(node.path || '—', node, { fullFallback: '—' });
      openNoteEl.href = fileHref(node.path);
      selectionStatusEl.textContent = `${displayNodeName(node)} · ${node.type}`;

      const detailValues = [
        node.type,
        `degree ${node.degree}`,
        node.status,
        node.emotional_valence,
        node.energy_impact,
        node.avoidance_risk ? `avoidance:${node.avoidance_risk}` : null,
        node.growth_edge ? 'growth-edge' : null,
        node.current_state ? `state:${node.current_state}` : null,
        node.raw_type && node.raw_type !== node.type ? `raw:${node.raw_type}` : null,
        node.folder ? `folder:${node.folder}` : null,
        ...(node.tags || []).slice(0, 8),
      ];
      detailTagsEl.innerHTML = '';
      for (const value of detailValues) {
        const safeValue = metadataChipValue(node, value);
        if (!safeValue) {
          continue;
        }
        const chip = document.createElement('span');
        chip.className = 'chip';
        chip.textContent = safeValue;
        detailTagsEl.appendChild(chip);
      }
      const emotionalBits = nodeEmotionalSummary(node);
      detailEmotionalEl.textContent = emotionalBits.length
        ? emotionalBits.join(' · ')
        : 'No emotional topology on this node yet.';
      detailEmotionalNoteEl.textContent = relationshipPrivacyEnabled()
        ? ''
        : redactRenderedText(node.valence_note || '', node, { fullFallback: '' });

      const linked = Array.from(neighbors.get(node.id) || [])
        .map((id) => nodeById.get(id))
        .filter((candidate) => candidate && candidate.visibleByToggle)
        .sort((a, b) => a.title.localeCompare(b.title))
        .slice(0, 18)
        .map((candidate) =>
          makeListItem(
            displayNodeName(candidate),
            `${displayNodeIdentifier(candidate)} · ${detailTypeLabel(candidate)}`,
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
            `${displayNodeIdentifier(edge.source)} · ${edgeMetaLine(edge)}`,
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
            `${displayNodeIdentifier(edge.target)} · ${edgeMetaLine(edge)}`,
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
            `${displayNodeIdentifier(candidate)} · ${candidate.type}`,
            () => selectNode(candidate, true)
          )
        );
      renderList(sessionMentionsEl, sessions, 'No recent session mentions.');
    }

    function updateEdgeDetail(edge) {
      if (!edge) {
        edgeDetailTitleEl.textContent = 'No edge selected.';
        edgeDetailMetaEl.textContent = 'Click a wire to inspect its provenance.';
        populatePredicateSelect(edgePredicateEl);
        edgeWeightEl.value = '0.7';
        edgeConfidenceEl.value = '';
        edgeNoteEl.value = '';
        syncRangeLabel(edgeWeightEl, edgeWeightLabelEl);
        saveEdgeButton.disabled = true;
        markEdgeReviewedButton.disabled = true;
        deleteEdgeButton.disabled = true;
        return;
      }
      edgeDetailTitleEl.textContent = `${displayNodeIdentifier(edge.source)} → ${displayNodeIdentifier(edge.target)}`;
      edgeDetailMetaEl.textContent = [
        edge.predicate,
        edge.weight !== null && edge.weight !== undefined ? `weight ${Number(edge.weight).toFixed(1)}` : null,
        edge.author ? `author ${edge.author}` : null,
        edge.method ? `method ${edge.method}` : null,
        edge.reviewed === false ? 'unreviewed' : edge.reviewed === true ? 'reviewed' : null,
        edge.reviewed_by ? `reviewed by ${edge.reviewed_by}` : null,
        edge.reviewed_at ? edge.reviewed_at : null,
        edge.review_duration_s !== null && edge.review_duration_s !== undefined ? `${Number(edge.review_duration_s).toFixed(1)}s` : null,
        edge.confidence ? `confidence ${edge.confidence}` : null,
        edge.note ? edge.note : null,
      ].filter(Boolean).join(' · ');
      populatePredicateSelect(edgePredicateEl, edge.predicate);
      edgeWeightEl.value = String(edge.weight ?? 0.7);
      edgeConfidenceEl.value = edge.confidence || '';
      edgeNoteEl.value = edge.note || '';
      syncRangeLabel(edgeWeightEl, edgeWeightLabelEl);
      saveEdgeButton.disabled = false;
      markEdgeReviewedButton.disabled = !!edgeReviewed(edge);
      deleteEdgeButton.disabled = false;
    }

    function updateDiscoverDetail(candidate) {
      if (!candidate) {
        discoverDetailTitleEl.textContent = 'No candidate selected.';
        discoverDetailMetaEl.textContent = 'Turn on discover mode and click a dashed candidate edge.';
        populatePredicateSelect(discoverPredicateEl);
        discoverWeightEl.value = '0.7';
        discoverConfidenceEl.value = 'medium';
        discoverNoteEl.value = '';
        syncRangeLabel(discoverWeightEl, discoverWeightLabelEl);
        acceptDiscoverButton.disabled = true;
        rejectDiscoverButton.disabled = true;
        return;
      }
      discoverDetailTitleEl.textContent = `${displayNodeIdentifier(candidate.source)} ←?→ ${displayNodeIdentifier(candidate.target)}`;
      discoverDetailMetaEl.textContent = `score ${Number(candidate.score || 0).toFixed(2)} · ${candidateReasonText(candidate)}`;
      populatePredicateSelect(discoverPredicateEl, predicatePalette[0]?.name || '');
      discoverWeightEl.value = String(Math.max(0, Math.min(1, Number(candidate.score || 0.7))).toFixed(2));
      discoverConfidenceEl.value = 'medium';
      discoverNoteEl.value = candidate.note || '';
      syncRangeLabel(discoverWeightEl, discoverWeightLabelEl);
      acceptDiscoverButton.disabled = false;
      rejectDiscoverButton.disabled = false;
    }

    function refreshSceneState(nowMs = performance.now()) {
      const needle = searchInput.value.trim();
      const selectedNeighbors = selectedNode ? neighbors.get(selectedNode.id) || new Set() : new Set();
      const traceById = state.traceData
        ? new Map(state.traceData.results.map((item) => [item.note_id, item]))
        : new Map();
      const traceActive = !!state.traceMode && traceById.size > 0;
      const traceElapsed = traceActive ? Math.max(0, nowMs - (state.traceStartedAt || nowMs)) : Number.POSITIVE_INFINITY;
      for (const node of nodes) {
        const isFolderHidden = !!(node.folder && state.hiddenFolders.has(node.folder));
        node.visibleByToggle = !state.hiddenTypes.has(node.type)
          && (state.showSessions || !node.is_session)
          && !isFolderHidden
          && !shouldHidePerson(node);
        const visible = node.visibleByToggle;
        const connected = !!selectedNode && selectedNeighbors.has(node.id);
        const dimForSearch = needle && !node.matched && node !== selectedNode;
        const dimForBrowser = state.browserType && state.browserType !== node.type && node !== selectedNode;
        const traceHit = traceById.get(node.id);
        const traceStrength = traceHit ? Math.max(0, Math.min(1, Number(traceHit.activation || 0))) : 0;
        const traceDepth = traceHit ? Math.max(1, Number(traceHit.depth || 1)) : 0;
        const traceReveal = !traceHit
          ? 0
          : Math.max(0, Math.min(1, (traceElapsed - (traceDepth - 1) * 300) / 220));
        node.mesh.visible = visible;
        const visibleColor = traceActive
          ? (
            node.id === state.traceData.note_id
              ? node.displayColor.clone().lerp(new THREE.Color('#ffffff'), 0.36)
              : traceHit
                ? node.displayColor.clone().lerp(new THREE.Color('#ffffff'), 0.22 + traceStrength * 0.48 * traceReveal)
                : node.baseColor.clone()
          )
          : node === selectedNode
          ? node.displayColor.clone().lerp(new THREE.Color('#fffdf4'), 0.2)
          : connected || node.matched
            ? node.displayColor
            : node.baseColor.clone().lerp(new THREE.Color('#f4d7a3'), usingThemeSigils ? 0.18 : 0.12);
        const visibleOpacity = !visible
          ? 0
          : traceActive
            ? (
              node.id === state.traceData.note_id
                ? 1
                : traceHit
                  ? 0.2 + 0.8 * traceReveal
                  : 0.2
            )
            : (dimForSearch || dimForBrowser ? 0.28 : connected || node === selectedNode ? 1 : 0.94);
        const glow = node === selectedNode
          ? node.glowColor.clone().multiplyScalar(0.8)
          : connected || node.matched
            ? node.glowColor.clone().multiplyScalar(0.42)
            : node.glowColor.clone().multiplyScalar(dimForSearch || dimForBrowser ? 0.15 : 0.24);
        node.material.color.copy(visibleColor);
        node.material.opacity = usingThemeSigils
          ? (!visible ? 0 : 0.001)
          : visibleOpacity;
        node.material.emissive.copy(glow);
        const connectivityScale = node.degree >= 12 ? 1.08 : node.degree >= 8 ? 1.04 : 1;
        node.renderScale = node.radius * connectivityScale * (node === selectedNode ? 1.48 : connected ? 1.18 : node.matched ? 1.08 : 1);
        node.mesh.scale.setScalar(node.renderScale);
        if (node.sigil && node.sigilMaterial) {
          node.sigil.visible = visible;
          node.sigilMaterial.color.copy(visibleColor);
          node.sigilMaterial.opacity = !visible ? 0 : (dimForSearch || dimForBrowser ? 0.2 : connected || node === selectedNode ? 1 : 0.92);
        }
        if (node.halo && node.haloMaterial) {
          node.halo.visible = visible;
          node.haloMaterial.color.copy(glow);
          node.haloMaterial.opacity = !visible ? 0 : (
            node === selectedNode
              ? 0.34
              : connected
                ? 0.2
                : node.degree >= 12
                  ? 0.14
                  : 0.1
          );
        }
      }

      for (const edge of edges) {
        const hiddenByPredicate = edge.isWire && state.hiddenPredicates.has(edge.predicate);
        const visible = edge.source.visibleByToggle
          && edge.target.visibleByToggle
          && (!edge.isWire || state.showWires)
          && !hiddenByPredicate;
        const connected = !!selectedNode && (edge.source === selectedNode || edge.target === selectedNode);
        const matches = !needle || edge.source.matched || edge.target.matched;
        const dimForBrowser = state.browserType && edge.source.type !== state.browserType && edge.target.type !== state.browserType && !connected;
        const reviewedWire = edgeReviewed(edge);
        const themedEdgeStyle = edgeStyle(edge);
        const traceEdge = traceActive
          && (
            edge.source.id === state.traceData.note_id
            || edge.target.id === state.traceData.note_id
            || (traceById.has(edge.source.id) && traceById.has(edge.target.id))
          );
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
        edge.renderOpacity = connected
          ? (edge.isWire ? 1 : 0.64)
          : state.showUnreviewedOnly && edge.isWire && reviewedWire
            ? 0.15
            : traceActive
              ? (traceEdge ? 0.96 : 0.14)
          : dimForBrowser
            ? 0.08
            : matches
              ? (edge.isWire ? (usingThemeSigils ? 0.84 : 0.76) : 0.28)
              : (usingThemeSigils ? (edge.isWire ? 0.18 : 0.12) : 0.12);
        edge.material.opacity = edge.renderOpacity * (themedEdgeStyle.opacityMultiplier || 1);
        if (edge.marker && edge.markerMaterial) {
          edge.marker.visible = visible;
          edge.markerMaterial.color.copy(
            connected
              ? edge.baseColor.clone().lerp(new THREE.Color('#fff6d8'), 0.42)
              : edge.baseColor
          );
          edge.markerMaterial.opacity = !visible ? 0 : (
            connected
              ? 0.96
              : state.showUnreviewedOnly && reviewedWire
                ? 0.12
                : traceActive
                  ? (traceEdge ? 0.82 : 0.08)
              : matches
                ? (usingThemeSigils ? 0.52 : 0.34)
                : (usingThemeSigils ? 0.16 : 0.1)
          );
        }
      }

      for (const candidate of discoverOverlayData) {
        const candidateVisible = !!state.discoverOverlay
          && candidate.source.visibleByToggle
          && candidate.target.visibleByToggle
          && (!selectedNode || candidate.source === selectedNode || candidate.target === selectedNode);
        const selected = selectedDiscoverCandidate === candidate;
        const connected = !!selectedNode && (candidate.source === selectedNode || candidate.target === selectedNode);
        candidate.line.visible = candidateVisible;
        if (!candidateVisible) {
          continue;
        }
        candidate.material.opacity = selected ? 0.96 : connected ? 0.72 : 0.42;
      }

      for (const [folder, biome] of biomeObjects.entries()) {
        if (!biome.group.visible) {
          continue;
        }
        const emphasized = !!selectedNode && selectedNode.folder === folder;
        biome.innerRing.material.opacity = emphasized ? 0.34 : 0.22;
        biome.outerRing.material.opacity = emphasized ? 0.22 : 0.12;
        biome.dust.material.opacity = emphasized ? 0.2 : 0.14;
      }
      pendingReviewStatusEl.textContent = `${edges.filter((edge) => edge.isWire && !edgeReviewed(edge)).length} wires pending review`;
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
        node.labelEl.textContent = labelTextForNode(node);
        node.labelEl.className = `node-label${node === selectedNode ? ' active' : ''}`;
        node.labelEl.style.left = `${(projected.x * 0.5 + 0.5) * 100}%`;
        node.labelEl.style.top = `${(-projected.y * 0.5 + 0.5) * 100}%`;
      }

      let edgeLabelsShown = 0;
      for (const edge of edges) {
        if (!edge.labelEl) {
          continue;
        }
        const connected = !!selectedNode && (edge.source === selectedNode || edge.target === selectedNode);
        const shouldShow = edge.isWire
          && state.showWires
          && edge.line.visible
          && (connected || (state.showLabels && edge.renderOpacity >= 0.22))
          && edgeLabelsShown < 90;
        if (!shouldShow) {
          edge.labelEl.style.display = 'none';
          continue;
        }
        const midpoint = edge.source.position.clone().lerp(edge.target.position, 0.5).project(camera);
        if (midpoint.z < -1 || midpoint.z > 1 || Math.abs(midpoint.x) > 1.1 || Math.abs(midpoint.y) > 1.1) {
          edge.labelEl.style.display = 'none';
          continue;
        }
        edge.labelEl.style.display = 'block';
        edge.labelEl.textContent = wireLabelText(edge);
        edge.labelEl.style.left = `${(midpoint.x * 0.5 + 0.5) * 100}%`;
        edge.labelEl.style.top = `${(-midpoint.y * 0.5 + 0.5) * 100}%`;
        edge.labelEl.style.opacity = connected ? '1' : '0.82';
        edgeLabelsShown += 1;
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
        node.matched = !!needle
          && !state.hiddenTypes.has(node.type)
          && (!node.folder || !state.hiddenFolders.has(node.folder))
          && (state.showSessions || !node.is_session)
          && !shouldHidePerson(node)
          && node.haystack.includes(needle);
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
            `${displayNodeIdentifier(node)} · degree ${node.degree}`,
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
        if (activeTheme.legendStyle === 'glyph') {
          main.innerHTML = `<span class="glyph-swatch" style="color:${typeColors[typeName] || '#b6c2cf'}">${glyphForType(typeName)}</span><span>${typeName}</span>`;
        } else {
          main.innerHTML = `<span class="swatch" style="background:${typeColors[typeName] || '#b6c2cf'}"></span><span>${typeName}</span>`;
        }
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
          renderPredicateLegend();
          renderFolderChips();
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
          renderPredicateLegend();
          renderFolderChips();
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

    function renderPredicateLegend() {
      predicateLegendEl.innerHTML = '';
      for (const entry of predicatePalette) {
        const row = document.createElement('div');
        row.className = 'legend-row';
        const main = document.createElement('button');
        main.type = 'button';
        main.className = 'legend-main';
        main.innerHTML = `<span class="swatch" style="background:${entry.color || '#f0b35f'}"></span><span>${escapeHtml(entry.name)}</span>`;
        main.addEventListener('click', () => {
          if (state.hiddenPredicates.has(entry.name)) {
            state.hiddenPredicates.delete(entry.name);
          } else {
            state.hiddenPredicates.add(entry.name);
          }
          renderPredicateLegend();
          refreshSceneState();
          updateLabels();
        });
        const actions = document.createElement('div');
        actions.className = 'legend-actions';
        const count = document.createElement('span');
        count.className = 'mono subtle';
        count.textContent = String(edges.filter((edge) => edge.isWire && edge.predicate === entry.name).length);
        const toggle = document.createElement('button');
        toggle.type = 'button';
        toggle.className = `legend-toggle${state.hiddenPredicates.has(entry.name) ? ' inactive' : ''}`;
        toggle.textContent = state.hiddenPredicates.has(entry.name) ? 'show' : 'hide';
        toggle.addEventListener('click', (event) => {
          event.stopPropagation();
          if (state.hiddenPredicates.has(entry.name)) {
            state.hiddenPredicates.delete(entry.name);
          } else {
            state.hiddenPredicates.add(entry.name);
          }
          renderPredicateLegend();
          refreshSceneState();
          updateLabels();
        });
        actions.appendChild(count);
        actions.appendChild(toggle);
        row.appendChild(main);
        row.appendChild(actions);
        predicateLegendEl.appendChild(row);
      }
    }

    function renderFolderChips() {
      folderChipList.innerHTML = '';
      for (const folder of folderNames) {
        const visibleCount = nodes.filter((node) =>
          node.folder === folder
          && !state.hiddenTypes.has(node.type)
          && (state.showSessions || !node.is_session)
          && !shouldHidePerson(node)
        ).length;
        const button = document.createElement('button');
        button.type = 'button';
        const active = !state.hiddenFolders.has(folder);
        const folderGlyph = folderGlyphForName(folder);
        button.className = `folder-row${active ? ' active' : ' inactive'}`;
        button.innerHTML = `
          <span class="folder-meta">
            <span class="glyph-swatch">${escapeHtml(folderGlyph)}</span>
            <span class="folder-name">${escapeHtml(folder)}</span>
          </span>
          <span class="folder-count">${visibleCount}</span>
        `;
        button.addEventListener('click', () => {
          if (state.hiddenFolders.has(folder)) {
            state.hiddenFolders.delete(folder);
          } else {
            state.hiddenFolders.add(folder);
          }
          applySearch();
          renderFolderChips();
          renderTypeBrowser();
          refreshSceneState();
          writeHashState();
        });
        folderChipList.appendChild(button);
      }
    }

    function selectNode(node, center = true) {
      selectedNode = node || null;
      selectedEdge = null;
      selectedDiscoverCandidate = null;
      updateDetail(selectedNode);
      updateEdgeDetail(selectedEdge);
      updateDiscoverDetail(selectedDiscoverCandidate);
      if (state.traceMode && selectedNode) {
        fetch(`/api/trace?note=${encodeURIComponent(selectedNode.id)}&depth=3`)
          .then((response) => response.json())
          .then((payload) => {
            state.traceData = payload;
            state.traceStartedAt = performance.now();
            refreshSceneState();
            updateLabels();
          })
          .catch(() => {
            state.traceData = null;
          });
      } else if (!selectedNode) {
        state.traceData = null;
        state.traceStartedAt = 0;
      }
      if (state.discoverOverlay) {
        loadDiscoverOverlay(selectedNode ? selectedNode.id : null).catch(() => {
          clearDiscoverOverlay();
          updateDiscoverDetail(null);
        });
      }
      refreshSceneState();
      if (center && selectedNode) {
        focusNode(selectedNode);
      }
      writeHashState();
    }

    function selectEdge(edge) {
      selectedEdge = edge || null;
      selectedNode = null;
      selectedDiscoverCandidate = null;
      updateDetail(null);
      updateEdgeDetail(selectedEdge);
      updateDiscoverDetail(selectedDiscoverCandidate);
      if (selectedEdge) {
        selectionStatusEl.textContent = `${selectedEdge.predicate} · ${displayNodeIdentifier(selectedEdge.source)} → ${displayNodeIdentifier(selectedEdge.target)}`;
      }
      refreshSceneState();
      writeHashState();
    }

    function selectDiscoverCandidate(candidate) {
      selectedDiscoverCandidate = candidate || null;
      selectedNode = null;
      selectedEdge = null;
      updateDetail(null);
      updateEdgeDetail(null);
      updateDiscoverDetail(selectedDiscoverCandidate);
      if (selectedDiscoverCandidate && !selectedDiscoverCandidate.selectedAt) {
        selectedDiscoverCandidate.selectedAt = performance.now();
      }
      if (selectedDiscoverCandidate) {
        selectionStatusEl.textContent = `candidate · ${displayNodeIdentifier(selectedDiscoverCandidate.source)} ↔ ${displayNodeIdentifier(selectedDiscoverCandidate.target)}`;
      } else {
        selectionStatusEl.textContent = 'awaiting selection';
      }
      refreshSceneState();
      writeHashState();
    }

    function resizeRenderer() {
      const width = canvasHost.clientWidth || 1;
      const height = canvasHost.clientHeight || 1;
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    }

    function pickGraphTarget(event) {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const hits = raycaster.intersectObjects(nodes.map((node) => node.mesh), true);
      for (const hit of hits) {
        if (!hit.object.visible) {
          continue;
        }
        if (hit.object.userData?.node) {
          return { type: 'node', value: hit.object.userData.node };
        }
      }
      const edgeHits = raycaster.intersectObjects(edges.map((edge) => edge.line), true);
      for (const hit of edgeHits) {
        if (!hit.object.visible) {
          continue;
        }
        if (hit.object.userData?.edge) {
          return { type: 'edge', value: hit.object.userData.edge };
        }
      }
      const discoverHits = raycaster.intersectObjects(discoverOverlayData.map((candidate) => candidate.line), true);
      for (const hit of discoverHits) {
        if (!hit.object.visible) {
          continue;
        }
        if (hit.object.userData?.discoverCandidate) {
          const candidate = discoverOverlayData.find((item) => item.line === hit.object);
          if (candidate) {
            return { type: 'discover', value: candidate };
          }
        }
      }
      return null;
    }

    function projectNode(node) {
      return node.position.clone().project(camera);
    }

    function currentGroupKey(node) {
      if (!node) {
        return null;
      }
      if (node.type === 'person') {
        return 'type:person';
      }
      return node.folder ? `folder:${node.folder}` : `type:${node.type}`;
    }

    function groupCandidates(node) {
      const candidates = navigationCandidates();
      if (!node) {
        return candidates;
      }
      if (node.type === 'person') {
        return orderedPeople.filter((candidate) => candidates.includes(candidate));
      }
      const key = currentGroupKey(node);
      return sortNodes(
        candidates.filter((candidate) => currentGroupKey(candidate) === key)
      );
    }

    function structuralGroups() {
      const candidates = navigationCandidates();
      const groups = new Map();
      for (const node of candidates) {
        const key = currentGroupKey(node);
        if (!groups.has(key)) {
          groups.set(key, []);
        }
        groups.get(key).push(node);
      }
      return [...groups.entries()]
        .sort((left, right) => {
          const [leftKey, leftNodes] = left;
          const [rightKey, rightNodes] = right;
          const leftNode = leftNodes[0];
          const rightNode = rightNodes[0];
          if (leftNode.type === 'person' && rightNode.type !== 'person') {
            return -1;
          }
          if (leftNode.type !== 'person' && rightNode.type === 'person') {
            return 1;
          }
          const leftFolder = folderOrder.get(leftNode.folder || '') ?? Number.MAX_SAFE_INTEGER;
          const rightFolder = folderOrder.get(rightNode.folder || '') ?? Number.MAX_SAFE_INTEGER;
          if (leftFolder !== rightFolder) {
            return leftFolder - rightFolder;
          }
          return leftKey.localeCompare(rightKey);
        })
        .map(([key, group]) => [key, groupCandidates(group[0])]);
    }

    function moveWithinGroup(delta) {
      const candidates = navigationCandidates();
      if (!candidates.length) {
        selectNode(null, false);
        return;
      }
      if (!selectedNode || !candidates.includes(selectedNode)) {
        selectNode(candidates[0], true);
        return;
      }
      const group = groupCandidates(selectedNode);
      if (!group.length) {
        selectNode(candidates[0], true);
        return;
      }
      const currentIndex = group.findIndex((candidate) => candidate.id === selectedNode.id);
      const nextIndex = currentIndex < 0
        ? 0
        : (currentIndex + delta + group.length) % group.length;
      selectNode(group[nextIndex], true);
    }

    function moveAcrossGroups(delta) {
      const groups = structuralGroups();
      if (!groups.length) {
        selectNode(null, false);
        return;
      }
      if (!selectedNode) {
        selectNode(groups[0][1][0], true);
        return;
      }
      const currentKey = currentGroupKey(selectedNode);
      const groupIndex = groups.findIndex(([key]) => key === currentKey);
      const normalizedGroupIndex = groupIndex < 0 ? 0 : groupIndex;
      const [, currentGroup] = groups[normalizedGroupIndex];
      const currentIndex = Math.max(
        0,
        currentGroup.findIndex((candidate) => candidate.id === selectedNode.id)
      );
      const nextGroupIndex = (normalizedGroupIndex + delta + groups.length) % groups.length;
      const [, nextGroup] = groups[nextGroupIndex];
      if (!nextGroup.length) {
        return;
      }
      const nextIndex = Math.min(currentIndex, nextGroup.length - 1);
      selectNode(nextGroup[nextIndex], true);
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

    async function postJson(url, payload) {
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data?.error || `request failed: ${response.status}`);
      }
      return data;
    }

    async function refreshPredicatePaletteFromServer() {
      try {
        const response = await fetch('/api/predicates');
        if (!response.ok) {
          return;
        }
        const payload = await response.json();
        if (!Array.isArray(payload) || !payload.length) {
          return;
        }
        predicatePalette = payload;
        rebuildPredicateColorMap();
        for (const edge of edges) {
          if (!edge.isWire) {
            continue;
          }
          edge.baseColor = new THREE.Color(predicateColors[edge.predicate] || '#f0b35f');
          edge.material.color.copy(edge.baseColor);
          if (edge.markerMaterial) {
            edge.markerMaterial.color.copy(edge.baseColor);
          }
        }
        populatePredicateSelect(addWirePredicateEl, addWirePredicateEl.value);
        populatePredicateSelect(edgePredicateEl, edgePredicateEl.value || selectedEdge?.predicate || '');
        populatePredicateSelect(discoverPredicateEl, discoverPredicateEl.value);
        renderPredicateLegend();
        refreshSceneState();
      } catch (_error) {
        // Static HTML exports don't have the live API surface. Keep payload colors.
      }
    }

    async function pollLiveServerStatus() {
      try {
        const response = await fetch('/status');
        if (!response.ok) {
          return;
        }
        const payload = await response.json();
        if (!state.serverLastRegen) {
          state.serverLastRegen = payload.last_regen || null;
          return;
        }
        if (payload.last_regen && payload.last_regen !== state.serverLastRegen) {
          location.reload();
        }
      } catch (_error) {
        // Ignore in exported, offline HTML.
      }
    }

    function showActionStatus(message) {
      selectionStatusEl.textContent = message;
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
      const nowMs = performance.now();
      const now = nowMs * 0.001;
      if (state.traceMode && state.traceData) {
        refreshSceneState(nowMs);
      }
      if (usingThemeSigils) {
        stars.rotation.y += 0.0002;
        stars.rotation.x += 0.00004;
        surveyGrid.forEach((line, index) => {
          line.rotation.z += 0.00006 * (index % 2 === 0 ? 1 : -1);
        });
        for (const biome of biomeObjects.values()) {
          if (!biome.group.visible) {
            continue;
          }
          biome.innerRing.rotation.y = now * 0.14 + biome.phase;
          biome.outerRing.rotation.y = -now * 0.09 + biome.phase * 0.6;
          biome.dust.rotation.y = now * 0.045 + biome.phase * 0.4;
        }
      }
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
      for (const node of nodes) {
        if (!node.mesh.visible) {
          continue;
        }
        const pulse = node === selectedNode
          ? 1 + Math.sin(now * 3.6) * 0.035
          : node.degree >= 12
            ? 1 + Math.sin(now * 2.2 + node.index * 0.12) * 0.018
            : 1;
        node.mesh.scale.setScalar(node.renderScale * pulse);
        const glyphFamily = glyphFamilyForType(node.type);
        if (node.sigil) {
          const glyphScale = glyphScaleByFamily[glyphFamily] || 3;
          node.sigil.scale.set(
            node.renderScale * glyphScale * pulse,
            node.renderScale * glyphScale * pulse,
            1,
          );
        }
        if (node.halo) {
          const haloScale = haloScaleByFamily[glyphFamily] || 5.4;
          const haloPulse = node === selectedNode
            ? 1 + Math.sin(now * 4.4) * 0.045
            : pulse;
          node.halo.scale.set(
            node.renderScale * haloScale * haloPulse,
            node.renderScale * haloScale * haloPulse,
            1,
          );
        }
      }
      for (const edge of edges) {
        if (!edge.line.visible || !edge.isWire) {
          continue;
        }
        if (selectedNode && (edge.source === selectedNode || edge.target === selectedNode)) {
          edge.material.opacity = Math.min(1, (edge.renderOpacity || edge.material.opacity) + 0.08 + Math.sin(now * 5.5) * 0.04);
        }
        if (edge.marker) {
          const connected = !!selectedNode && (edge.source === selectedNode || edge.target === selectedNode);
          const travel = connected
            ? 0.56 + ((Math.sin(now * 3.6 + edge.source.index * 0.31) + 1) * 0.5) * 0.22
            : 0.62;
          const markerPos = edge.source.position.clone().lerp(edge.target.position, travel);
          edge.marker.position.copy(markerPos);
          const markerScale = connected ? 20 : (usingThemeSigils ? 16 : 12);
          edge.marker.scale.set(markerScale, markerScale, 1);
        }
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
        const target = pickGraphTarget(event);
        if (target?.type === 'discover') {
          showGraphTooltip(candidateReasonText(target.value), event);
        } else {
          showGraphTooltip('', null);
        }
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
        const target = pickGraphTarget(event);
        if (target?.type === 'node') {
          selectNode(target.value, false);
        } else if (target?.type === 'edge') {
          selectEdge(target.value);
        } else if (target?.type === 'discover') {
          selectDiscoverCandidate(target.value);
        } else if (state.traceMode) {
          state.traceData = null;
          state.traceStartedAt = 0;
          refreshSceneState();
          updateLabels();
        }
      }
      if (pointerDown) {
        renderer.domElement.releasePointerCapture?.(pointerDown.pointerId);
      }
      pointerDown = null;
      dragMode = null;
      showGraphTooltip('', null);
      writeHashState();
    });
    renderer.domElement.addEventListener('dblclick', () => {
      if (selectedNode) {
        focusNode(selectedNode);
      } else {
        resetCamera();
      }
    });
    renderer.domElement.addEventListener('mouseleave', () => {
      showGraphTooltip('', null);
    });

    searchInput.addEventListener('input', applySearch);
    searchInput.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        searchInput.value = '';
        applySearch();
        searchInput.blur();
      }
    });
    addWireWeightEl.addEventListener('input', () => syncRangeLabel(addWireWeightEl, addWireWeightLabelEl));
    edgeWeightEl.addEventListener('input', () => syncRangeLabel(edgeWeightEl, edgeWeightLabelEl));
    discoverWeightEl.addEventListener('input', () => syncRangeLabel(discoverWeightEl, discoverWeightLabelEl));
    runTraceButton.addEventListener('click', async () => {
      if (!selectedNode) {
        return;
      }
      traceModeToggle.checked = true;
      traceModeToggle.dispatchEvent(new Event('change'));
    });
    toggleAddWireButton.addEventListener('click', () => {
      addWireFormEl.hidden = !addWireFormEl.hidden;
      if (!addWireFormEl.hidden) {
        populatePredicateSelect(addWirePredicateEl, addWirePredicateEl.value);
        addWireTargetEl.focus();
      }
    });
    cancelAddWireButton.addEventListener('click', () => {
      addWireFormEl.hidden = true;
    });
    submitAddWireButton.addEventListener('click', async () => {
      if (!selectedNode) {
        return;
      }
      try {
        const payload = await postJson('/api/wire/create', {
          source_note: selectedNode.id,
          source_path: selectedNode.path,
          target_note: addWireTargetEl.value,
          predicate: addWirePredicateEl.value,
          weight: addWireWeightEl.value,
        });
        showActionStatus(payload.created ? 'wire created' : payload.updated ? 'wire updated' : 'wire unchanged');
        location.reload();
      } catch (error) {
        showActionStatus(String(error.message || error));
      }
    });
    saveEdgeButton.addEventListener('click', async () => {
      if (!selectedEdge) {
        return;
      }
      try {
        await postJson('/api/wire/update', {
          path: selectedEdge.path,
          source_note: selectedEdge.source.id,
          source_block: selectedEdge.source_block,
          target_note: selectedEdge.target.id,
          target_block: selectedEdge.target_block,
          predicate: selectedEdge.predicate,
          new_predicate: edgePredicateEl.value,
          weight: edgeWeightEl.value,
          confidence: edgeConfidenceEl.value || null,
          note: edgeNoteEl.value || null,
        });
        showActionStatus('wire updated');
        location.reload();
      } catch (error) {
        showActionStatus(String(error.message || error));
      }
    });
    markEdgeReviewedButton.addEventListener('click', async () => {
      if (!selectedEdge) {
        return;
      }
      try {
        await postJson('/api/wire/review', {
          path: selectedEdge.path,
          source_note: selectedEdge.source.id,
          source_block: selectedEdge.source_block,
          target_note: selectedEdge.target.id,
          target_block: selectedEdge.target_block,
          predicate: selectedEdge.predicate,
          confidence: edgeConfidenceEl.value || selectedEdge.confidence || 'medium',
          note: edgeNoteEl.value || selectedEdge.note || null,
        });
        showActionStatus('wire reviewed');
        location.reload();
      } catch (error) {
        showActionStatus(String(error.message || error));
      }
    });
    deleteEdgeButton.addEventListener('click', async () => {
      if (!selectedEdge || !window.confirm('Delete this wire from the note file?')) {
        return;
      }
      try {
        await postJson('/api/wire/delete', {
          path: selectedEdge.path,
          source_note: selectedEdge.source.id,
          source_block: selectedEdge.source_block,
          target_note: selectedEdge.target.id,
          target_block: selectedEdge.target_block,
          predicate: selectedEdge.predicate,
        });
        showActionStatus('wire deleted');
        location.reload();
      } catch (error) {
        showActionStatus(String(error.message || error));
      }
    });
    discoverFromNodeButton.addEventListener('click', async () => {
      if (!selectedNode) {
        return;
      }
      discoverOverlayToggle.checked = true;
      state.discoverOverlay = true;
      syncCompactToggles();
      try {
        await loadDiscoverOverlay(selectedNode.id);
        showActionStatus(`discover overlay for ${displayNodeIdentifier(selectedNode)}`);
      } catch (error) {
        showActionStatus(String(error.message || error));
      }
    });
    acceptDiscoverButton.addEventListener('click', async () => {
      if (!selectedDiscoverCandidate) {
        return;
      }
      try {
        await postJson('/api/discover/accept', {
          left_id: selectedDiscoverCandidate.left_id,
          right_id: selectedDiscoverCandidate.right_id,
          left_path: selectedDiscoverCandidate.left_path,
          right_path: selectedDiscoverCandidate.right_path,
          score: selectedDiscoverCandidate.score,
          reasons: selectedDiscoverCandidate.reasons,
          predicate: discoverPredicateEl.value,
          weight: discoverWeightEl.value,
          confidence: discoverConfidenceEl.value,
          note: discoverNoteEl.value || null,
          review_duration_s: selectedDiscoverCandidate.selectedAt
            ? (performance.now() - selectedDiscoverCandidate.selectedAt) / 1000
            : null,
        });
        showActionStatus('candidate accepted');
        location.reload();
      } catch (error) {
        showActionStatus(String(error.message || error));
      }
    });
    rejectDiscoverButton.addEventListener('click', () => {
      if (!selectedDiscoverCandidate) {
        return;
      }
      const rejecting = selectedDiscoverCandidate;
      discoverOverlayData = discoverOverlayData.filter((candidate) => candidate !== rejecting);
      if (rejecting.line) {
        scene.remove(rejecting.line);
      }
      selectDiscoverCandidate(null);
      refreshSceneState();
      updateLabels();
      showActionStatus('candidate dismissed');
    });

    showLabelsToggle.addEventListener('change', () => {
      state.showLabels = showLabelsToggle.checked;
      syncCompactToggles();
      saveToggles();
      refreshSceneState();
      writeHashState();
    });
    privacyModeSelect.addEventListener('change', () => {
      state.privacyMode = PRIVACY_MODES.has(privacyModeSelect.value) ? privacyModeSelect.value : DEFAULT_PRIVACY_MODE;
      saveToggles();
      updateDetail(selectedNode);
      renderTypeBrowser();
      refreshSceneState();
      writeHashState();
    });
    showSessionsToggle.addEventListener('change', () => {
      state.showSessions = showSessionsToggle.checked;
      syncCompactToggles();
      saveToggles();
      layoutNodes();
      applySearch();
      renderLegend();
      renderPredicateLegend();
      renderFolderChips();
      renderTypeBrowser();
      smartFitCamera();
    });
    showWiresToggle.addEventListener('change', () => {
      state.showWires = showWiresToggle.checked;
      syncCompactToggles();
      saveToggles();
      refreshSceneState();
      writeHashState();
    });
    showUnreviewedOnlyToggle.addEventListener('change', () => {
      state.showUnreviewedOnly = showUnreviewedOnlyToggle.checked;
      syncCompactToggles();
      refreshSceneState();
      updateLabels();
    });
    traceModeToggle.addEventListener('change', async () => {
      state.traceMode = traceModeToggle.checked;
      syncCompactToggles();
      if (state.traceMode && selectedNode) {
        try {
          const response = await fetch(`/api/trace?note=${encodeURIComponent(selectedNode.id)}&depth=3`);
          state.traceData = await response.json();
          state.traceStartedAt = performance.now();
        } catch (_error) {
          state.traceData = null;
          state.traceStartedAt = 0;
        }
      } else {
        state.traceData = null;
        state.traceStartedAt = 0;
      }
      refreshSceneState();
      updateLabels();
    });
    discoverOverlayToggle.addEventListener('change', async () => {
      state.discoverOverlay = discoverOverlayToggle.checked;
      syncCompactToggles();
      if (state.discoverOverlay) {
        try {
          await loadDiscoverOverlay(selectedNode ? selectedNode.id : null);
        } catch (_error) {
          clearDiscoverOverlay();
        }
      } else {
        clearDiscoverOverlay();
        updateDiscoverDetail(null);
      }
      refreshSceneState();
      updateLabels();
    });
    themeSelect.addEventListener('change', () => {
      const nextTheme = normalizeThemeName(themeSelect.value) || 'baseline';
      const configTheme = normalizeThemeName(graphConfig.theme_preset || 'baseline');
      if (nextTheme === configTheme) {
        window.localStorage.removeItem(THEME_STORAGE_KEY);
      } else {
        window.localStorage.setItem(THEME_STORAGE_KEY, nextTheme);
      }
      location.reload();
    });

    document.getElementById('reset-layout').addEventListener('click', () => {
      layoutNodes();
      applySearch();
      smartFitCamera();
    });
    document.getElementById('fit-view').addEventListener('click', () => smartFitCamera({ preferSelection: true }));
    document.getElementById('show-all-types').addEventListener('click', () => {
      state.hiddenTypes.clear();
      state.hiddenFolders.clear();
      state.browserType = null;
      renderLegend();
      renderPredicateLegend();
      layoutNodes();
      applySearch();
      renderFolderChips();
      renderTypeBrowser();
      smartFitCamera();
    });
    showAllFoldersButton.addEventListener('click', () => {
      state.hiddenFolders.clear();
      applySearch();
      renderFolderChips();
      renderTypeBrowser();
      refreshSceneState();
      writeHashState();
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

    function toggleHelp(forceHidden = null) {
      helpOverlay.hidden = forceHidden === null ? !helpOverlay.hidden : forceHidden;
      toggleHelpButton.setAttribute('aria-expanded', String(!helpOverlay.hidden));
    }

    toggleHelpButton.addEventListener('click', () => toggleHelp());
    closeHelpButton.addEventListener('click', () => toggleHelp(true));
    helpOverlay.addEventListener('click', (event) => {
      if (event.target === helpOverlay) {
        toggleHelp(true);
      }
    });

    function isTextEntryTarget(target) {
      if (!target) {
        return false;
      }
      return target === searchInput
        || target.tagName === 'INPUT'
        || target.tagName === 'TEXTAREA'
        || target.isContentEditable;
    }

    window.addEventListener('keydown', (event) => {
      if (event.metaKey || event.ctrlKey || event.altKey) {
        return;
      }
      const key = String(event.key || '');
      const lowerKey = key.toLowerCase();
      if (event.key === 'F1') {
        event.preventDefault();
        toggleHelp();
        return;
      }
      if (lowerKey === 'h' || event.code === 'KeyH') {
        event.preventDefault();
        toggleHelp();
        return;
      }
      if (key === 'Escape') {
        if (!helpOverlay.hidden) {
          event.preventDefault();
          toggleHelp(true);
          return;
        }
        if (document.activeElement === searchInput) {
          searchInput.value = '';
          applySearch();
          searchInput.blur();
          return;
        }
        state.traceData = null;
        refreshSceneState();
        updateLabels();
      }
      if (isTextEntryTarget(document.activeElement)) {
        return;
      }
      if (event.key === '/') {
        event.preventDefault();
        searchInput.focus();
        searchInput.select();
        return;
      }
      if (lowerKey === 's') {
        event.preventDefault();
        showSessionsToggle.checked = !showSessionsToggle.checked;
        showSessionsToggle.dispatchEvent(new Event('change'));
        return;
      }
      if (lowerKey === 'w') {
        event.preventDefault();
        showWiresToggle.checked = !showWiresToggle.checked;
        showWiresToggle.dispatchEvent(new Event('change'));
        return;
      }
      if (lowerKey === 'r') {
        event.preventDefault();
        resetCamera();
        return;
      }
      if (event.key === '0') {
        event.preventDefault();
        state.hiddenTypes.clear();
        state.hiddenFolders.clear();
        state.hiddenPredicates.clear();
        state.browserType = null;
        renderLegend();
        renderPredicateLegend();
        layoutNodes();
        applySearch();
        renderFolderChips();
        renderTypeBrowser();
        smartFitCamera();
        return;
      }
      if (lowerKey === 'j') {
        event.preventDefault();
        cycleSelection(1);
        return;
      }
      if (lowerKey === 'k') {
        event.preventDefault();
        cycleSelection(-1);
        return;
      }
      if (event.key === 'ArrowLeft') {
        event.preventDefault();
        moveWithinGroup(-1);
        return;
      }
      if (event.key === 'ArrowRight') {
        event.preventDefault();
        moveWithinGroup(1);
        return;
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault();
        moveAcrossGroups(-1);
        return;
      }
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        moveAcrossGroups(1);
        return;
      }
      if ((event.key === 'Enter' || event.key === ' ') && selectedNode) {
        event.preventDefault();
        focusNode(selectedNode);
      }
    }, true);

    try {
      resizeRenderer();
      layoutNodes();
      restoreHashSelection();
      renderLegend();
      renderPredicateLegend();
      renderFolderChips();
      updateEdgeDetail(null);
      updateDiscoverDetail(null);
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
      refreshPredicatePaletteFromServer();
      window.setInterval(pollLiveServerStatus, 2000);
      animate();
    } catch (error) {
      console.error('graph init failed', error);
      showGraphError(error);
    }
    })();
  </script>
</body>
</html>
"""
    # Inject graph-rendering plugins
    from .graph_plugins import discover_graph_plugins, inject_plugin_hooks
    if plugin_names:
        # Only inject explicitly requested plugins
        graph_plugins = [p for p in discover_graph_plugins() if p.name in plugin_names]
        if graph_plugins:
            template = inject_plugin_hooks(template, graph_plugins)

    return (
        template
        .replace("__THREE_VENDOR__", vendor_three)
        .replace("__PAYLOAD__", payload_json)
        .replace("__THEME_SCRIPT_TAGS__", theme_script_tags)
        .replace("__BODY_THEME__", str(payload.get("graph_config", {}).get("theme_preset") or "baseline"))
    )
