"""graph_extensions.py — Wire styling logic for the emotional-topology plugin.

Reads predicates.toml to resolve color, thickness, and label for each
person-to-person wire. Provides:

- resolve_edge_style()   — per-wire color/thickness/dash dict
- format_wire_label()    — compact "predicate · modifier · snippet" label
- group_person_wires()   — bundle wires by predicate category when above threshold
- build_edge_payloads()  — directional edge pairs with independent styling
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:
        tomllib = None  # type: ignore[assignment]

NEUTRAL_COLOR = "#71717a"  # zinc-500 — when emotional styling is OFF
NEUTRAL_THICKNESS = 1
REVIEWED_DASH = None       # solid
UNREVIEWED_DASH = "6 4"    # dashed

_PREDICATES_CACHE: dict[str, Any] | None = None
_PREDICATES_PATH: Path | None = None


# ── TOML loading ──────────────────────────────────────────

def _load_predicates(plugin_dir: Path | None = None) -> dict[str, Any]:
    """Load and cache predicates.toml from the plugin directory."""
    global _PREDICATES_CACHE, _PREDICATES_PATH
    if plugin_dir is None:
        plugin_dir = Path(__file__).resolve().parent
    toml_path = plugin_dir / "predicates.toml"
    if _PREDICATES_CACHE is not None and _PREDICATES_PATH == toml_path:
        return _PREDICATES_CACHE
    if tomllib is None:
        raise RuntimeError("tomllib (Python 3.11+) or tomli required to load predicates.toml")
    with open(toml_path, "rb") as f:
        data = tomllib.load(f)
    _PREDICATES_CACHE = data
    _PREDICATES_PATH = toml_path
    return data


def _color_hex(predicates: dict[str, Any], predicate_def: dict[str, Any]) -> str:
    """Resolve a predicate's color name to hex via the color_reference table."""
    color_name = predicate_def.get("color", "zinc")
    ref = predicates.get("color_reference", {})
    return ref.get(color_name, predicate_def.get("hex", NEUTRAL_COLOR))


# ── Edge style resolution ─────────────────────────────────

def resolve_edge_style(
    *,
    predicate: str,
    state_modifiers: list[str] | None = None,
    emotional_styling_on: bool = False,
    reviewed: bool | None = None,
    plugin_dir: Path | None = None,
) -> dict[str, Any]:
    """Return a style dict for a single directed edge.

    Returns keys: color, thickness, dash, label_parts, state_modifiers
    """
    predicates = _load_predicates(plugin_dir)
    love_spectrum = predicates.get("love_spectrum", {})
    love_order = love_spectrum.get("order", [])
    person_preds = predicates.get("person_predicates", {})
    state_mods = predicates.get("state_modifiers", {})
    modifiers = list(state_modifiers or [])

    # Find the predicate definition — love spectrum first, then person predicates
    pred_def: dict[str, Any] | None = None
    if predicate in love_order and predicate in love_spectrum:
        pred_def = love_spectrum[predicate]
        # Thickness from position in love_spectrum order (1-indexed)
        position = love_order.index(predicate) + 1
    elif predicate in person_preds:
        pred_def = person_preds[predicate]

    if pred_def is None:
        # Unknown predicate — fallback
        return {
            "color": NEUTRAL_COLOR,
            "thickness": NEUTRAL_THICKNESS,
            "dash": UNREVIEWED_DASH if reviewed is False else REVIEWED_DASH,
            "label_parts": [predicate] if predicate else [],
            "state_modifiers": modifiers,
        }

    # Base thickness: position in love spectrum, or explicit thickness
    thickness = pred_def.get("thickness", NEUTRAL_THICKNESS)
    if predicate in love_order:
        thickness = max(thickness, love_order.index(predicate) + 1)

    # Color
    if emotional_styling_on:
        color = _color_hex(predicates, pred_def)
    else:
        color = NEUTRAL_COLOR
        thickness = NEUTRAL_THICKNESS

    # Dash — reserved for review status ONLY
    dash = UNREVIEWED_DASH if reviewed is False else REVIEWED_DASH

    # Label parts
    label_parts = [pred_def.get("label", predicate)]
    for mod_key in modifiers:
        mod_def = state_mods.get(mod_key, {})
        suffix = mod_def.get("suffix")
        if suffix:
            label_parts.append(suffix)

    # State modifier visual overlays
    modifier_visuals = []
    for mod_key in modifiers:
        mod_def = state_mods.get(mod_key, {})
        vis = mod_def.get("visual")
        if vis:
            modifier_visuals.append({"key": mod_key, "visual": vis})

    return {
        "color": color,
        "thickness": thickness,
        "dash": dash,
        "label_parts": label_parts,
        "state_modifiers": modifiers,
        "modifier_visuals": modifier_visuals,
    }


# ── Wire label formatting ─────────────────────────────────

def format_wire_label(
    *,
    predicate: str,
    state_modifiers: list[str] | None = None,
    note_snippet: str | None = None,
    plugin_dir: Path | None = None,
) -> str:
    """Format a compact wire label: "predicate · modifier · snippet".

    Fallback chain:
      predicate + modifiers + note_snippet → predicate + modifiers →
      note_snippet only → "relates to person" (generic fallback)
    """
    predicates = _load_predicates(plugin_dir)
    love_spectrum = predicates.get("love_spectrum", {})
    love_order = love_spectrum.get("order", [])
    person_preds = predicates.get("person_predicates", {})
    state_mods = predicates.get("state_modifiers", {})
    modifiers = list(state_modifiers or [])

    parts: list[str] = []

    # Resolve predicate label
    pred_label: str | None = None
    if predicate in love_spectrum and predicate in love_order:
        pred_label = love_spectrum[predicate].get("label")
    elif predicate in person_preds:
        pred_label = person_preds[predicate].get("label")
    elif predicate:
        pred_label = predicate

    if pred_label:
        parts.append(pred_label)

    # Append state modifier suffixes
    for mod_key in modifiers:
        mod_def = state_mods.get(mod_key, {})
        suffix = mod_def.get("suffix")
        if suffix:
            parts.append(suffix)

    # Append note snippet (truncated)
    if note_snippet:
        snippet = note_snippet.strip()
        if len(snippet) > 60:
            snippet = snippet[:57].rstrip() + "…"
        parts.append(snippet)

    if parts:
        return " · ".join(parts)

    # Ultimate fallback
    return "relates to person"


# ── Directional edge pairs ────────────────────────────────

def build_edge_payloads(
    wires: list[dict[str, Any]],
    *,
    emotional_styling_on: bool = False,
    plugin_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Convert person-to-person wires into directional edge payloads.

    Each wire becomes two directed edges (source→target, target→source)
    with independent styling. Non-person wires pass through unchanged.
    """
    edges: list[dict[str, Any]] = []

    for wire in wires:
        source = wire.get("source", "")
        target = wire.get("target", "")
        predicate = wire.get("predicate", "relates_to")
        note = wire.get("note")
        reviewed = wire.get("reviewed")
        state_mods = wire.get("state_modifiers", [])
        privacy = wire.get("privacy", "public")

        # Forward edge: source → target
        style = resolve_edge_style(
            predicate=predicate,
            state_modifiers=state_mods,
            emotional_styling_on=emotional_styling_on,
            reviewed=reviewed,
            plugin_dir=plugin_dir,
        )
        label = format_wire_label(
            predicate=predicate,
            state_modifiers=state_mods,
            note_snippet=note,
            plugin_dir=plugin_dir,
        )
        edges.append({
            "source": source,
            "target": target,
            "predicate": predicate,
            "label": label,
            "color": style["color"],
            "thickness": style["thickness"],
            "dash": style["dash"],
            "modifier_visuals": style.get("modifier_visuals", []),
            "privacy": privacy,
            "direction": "forward",
            **{k: wire.get(k) for k in ("note", "author", "method", "confidence",
                                         "reviewed", "reviewed_by", "reviewed_at",
                                         "review_duration_s", "weight",
                                         "emotional_valence", "energy_impact")},
        })

        # Reverse edge: target → source (if bidirectional data exists)
        reverse_predicate = wire.get("reverse_predicate") or wire.get("predicate_reverse")
        if reverse_predicate:
            rev_style = resolve_edge_style(
                predicate=reverse_predicate,
                state_modifiers=wire.get("reverse_state_modifiers", []),
                emotional_styling_on=emotional_styling_on,
                reviewed=reviewed,
                plugin_dir=plugin_dir,
            )
            rev_label = format_wire_label(
                predicate=reverse_predicate,
                state_modifiers=wire.get("reverse_state_modifiers", []),
                note_snippet=wire.get("reverse_note"),
                plugin_dir=plugin_dir,
            )
            edges.append({
                "source": target,
                "target": source,
                "predicate": reverse_predicate,
                "label": rev_label,
                "color": rev_style["color"],
                "thickness": rev_style["thickness"],
                "dash": rev_style["dash"],
                "modifier_visuals": rev_style.get("modifier_visuals", []),
                "privacy": wire.get("reverse_privacy", privacy),
                "direction": "reverse",
                **{k: wire.get(k) for k in ("note", "author", "method", "confidence",
                                             "reviewed", "reviewed_by", "reviewed_at",
                                             "review_duration_s", "weight",
                                             "emotional_valence", "energy_impact")},
            })

    return edges


# ── Edge grouping ─────────────────────────────────────────

def group_person_wires(
    wires: list[dict[str, Any]],
    *,
    grouping_threshold: int = 5,
    plugin_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Group person-wires by predicate category when a node exceeds the threshold.

    Returns a list where each item is either:
      - a single wire (below threshold or unique predicate)
      - a group dict with keys: group_predicate, count, wires, dominant_color
    """
    predicates = _load_predicates(plugin_dir)
    love_spectrum = predicates.get("love_spectrum", {})
    love_order = love_spectrum.get("order", [])
    person_preds = predicates.get("person_predicates", {})

    # Bucket wires by (node_id, predicate_category)
    # "love" category = anything in love_spectrum
    # other categories = individual predicate keys
    def _category(pred: str) -> str:
        if pred in love_order:
            return "love"
        return pred

    node_buckets: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for wire in wires:
        source = wire.get("source", "")
        target = wire.get("target", "")
        predicate = wire.get("predicate", "relates_to")
        # Track from the perspective of the non-maps node
        for node_id in (source, target):
            if node_id.lower() != "maps":
                continue
            cat = _category(predicate)
            node_buckets[node_id][cat].append(wire)

    result: list[dict[str, Any]] = []

    for node_id, categories in node_buckets.items():
        total = sum(len(v) for v in categories.values())
        if total <= grouping_threshold:
            # Below threshold — emit individual wires
            for cat_wires in categories.values():
                result.extend(cat_wires)
            continue

        # Above threshold — group by category
        for cat, cat_wires in categories.items():
            if len(cat_wires) <= 1:
                result.extend(cat_wires)
                continue

            # Determine dominant color
            sample_pred = cat_wires[0].get("predicate", "relates_to")
            if cat == "love" and sample_pred in love_spectrum:
                pred_def = love_spectrum[sample_pred]
            elif sample_pred in person_preds:
                pred_def = person_preds[sample_pred]
            else:
                pred_def = {}
            dominant_color = pred_def.get("hex", NEUTRAL_COLOR)

            # Determine category display label
            if cat == "love":
                # Count sub-categories
                sub_counts: dict[str, int] = defaultdict(int)
                for w in cat_wires:
                    sub_counts[w.get("predicate", "relates_to")] += 1
                display_parts = []
                for pred_name, count in sub_counts.items():
                    label = pred_name.replace("_", " ")
                    display_parts.append(f"{count} {label}")
                group_label = ", ".join(display_parts)
            else:
                pred_label = person_preds.get(sample_pred, {}).get("label", cat)
                group_label = f"{len(cat_wires)} {pred_label}"

            result.append({
                "type": "group",
                "node_id": node_id,
                "group_predicate": cat,
                "group_label": group_label,
                "count": len(cat_wires),
                "dominant_color": dominant_color,
                "wires": cat_wires,
                "expandable": True,
            })

    return result


# ── Convenience: full edge data for graph renderer ────────

def compute_emotional_edges(
    wires: list[dict[str, Any]],
    *,
    emotional_styling_on: bool = False,
    grouping_threshold: int = 5,
    plugin_dir: Path | None = None,
) -> dict[str, Any]:
    """Top-level entry point called by the graph renderer.

    Returns:
      edges: list of directional edge payloads
      groups: grouped wire bundles (for collapsed view)
      predicates: the loaded predicate definitions (for JS-side lookup)
    """
    predicates = _load_predicates(plugin_dir)
    edges = build_edge_payloads(
        wires,
        emotional_styling_on=emotional_styling_on,
        plugin_dir=plugin_dir,
    )
    groups = group_person_wires(
        wires,
        grouping_threshold=grouping_threshold,
        plugin_dir=plugin_dir,
    )
    return {
        "edges": edges,
        "groups": groups,
        "predicates": predicates,
    }
