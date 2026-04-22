from __future__ import annotations

from collections import defaultdict, deque
import sqlite3
from pathlib import Path
from typing import Any

from .config import load_config
from .index import Index
from .profiles import profile_payload


_VALENCE_WEIGHT = {
    "positive": 1.1,
    "mixed": 1.05,
    "negative": 0.9,
}


def _note_lookup(connection: sqlite3.Connection) -> dict[str, dict[str, str]]:
    rows = connection.execute(
        "SELECT id, title, path, type FROM notes ORDER BY id ASC"
    ).fetchall()
    return {
        str(row[0]): {
            "title": str(row[1] or row[0]),
            "path": str(row[2]),
            "type": str(row[3] or "note"),
        }
        for row in rows
    }


def _wire_graph(connection: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rows = connection.execute(
        """
        SELECT
            source_note,
            target_note,
            predicate,
            weight,
            bidirectional,
            emotional_valence
        FROM wires
        ORDER BY source_note ASC, target_note ASC, predicate ASC
        """
    ).fetchall()
    for source_note, target_note, predicate, weight, bidirectional, emotional_valence in rows:
        payload = {
            "neighbor": str(target_note),
            "predicate": str(predicate),
            "weight": 0.5 if weight is None else float(weight),
            "emotional_valence": None if emotional_valence is None else str(emotional_valence),
        }
        adjacency[str(source_note)].append(payload)
        if bool(bidirectional):
            adjacency[str(target_note)].append(
                {
                    "neighbor": str(source_note),
                    "predicate": str(predicate),
                    "weight": 0.5 if weight is None else float(weight),
                    "emotional_valence": None
                    if emotional_valence is None
                    else str(emotional_valence),
                }
            )
    return adjacency


def spreading_activation(
    atlas_root: Path | str,
    start_id: str,
    *,
    depth: int = 3,
    decay: float = 0.85,
    emotional_weight: bool = True,
    threshold: float = 0.05,
    predicate: str | None = None,
) -> list[dict[str, Any]]:
    atlas_root = Path(atlas_root).expanduser()
    index = Index(atlas_root)
    canonical_start = index.canonicalize_note_ref(start_id) or start_id

    connection = sqlite3.connect(str(index.db_path))
    try:
        notes = _note_lookup(connection)
        adjacency = _wire_graph(connection)
    finally:
        connection.close()

    if canonical_start not in notes:
        raise ValueError(f"note not found: {start_id}")

    queue: deque[tuple[str, float, int, list[str], list[dict[str, Any]]]] = deque(
        [(canonical_start, 1.0, 0, [canonical_start], [])]
    )
    best_activation: dict[str, float] = {canonical_start: 1.0}
    best_path: dict[str, list[str]] = {canonical_start: [canonical_start]}
    best_depth: dict[str, int] = {canonical_start: 0}
    best_path_edges: dict[str, list[dict[str, Any]]] = {canonical_start: []}
    allowed_predicates = set(
        profile_payload(atlas_root, config=load_config(atlas_root)).get("default_predicates") or []
    )

    while queue:
        current_note, activation, current_depth, path, path_edges = queue.popleft()
        if current_depth >= depth:
            continue
        for edge in adjacency.get(current_note, []):
            if allowed_predicates and str(edge["predicate"]) not in allowed_predicates:
                continue
            if predicate is not None and str(edge["predicate"]) != predicate:
                continue
            neighbor = str(edge["neighbor"])
            next_activation = activation * decay
            if emotional_weight:
                next_activation *= _VALENCE_WEIGHT.get(
                    str(edge.get("emotional_valence") or "").lower(),
                    1.0,
                )
            if next_activation < threshold:
                continue
            if next_activation <= best_activation.get(neighbor, 0.0):
                continue
            next_path = [*path, neighbor]
            next_path_edges = [
                *path_edges,
                {
                    "source_note": current_note,
                    "target_note": neighbor,
                    "predicate": str(edge["predicate"]),
                    "weight": round(float(edge.get("weight") or 0.5), 6),
                    "emotional_valence": edge.get("emotional_valence"),
                },
            ]
            best_activation[neighbor] = next_activation
            best_path[neighbor] = next_path
            best_depth[neighbor] = current_depth + 1
            best_path_edges[neighbor] = next_path_edges
            queue.append((neighbor, next_activation, current_depth + 1, next_path, next_path_edges))

    results: list[dict[str, Any]] = []
    for note_id, activation in best_activation.items():
        if note_id == canonical_start:
            continue
        note_info = notes.get(note_id, {"title": note_id, "path": "", "type": "note"})
        results.append(
            {
                "note_id": note_id,
                "title": note_info["title"],
                "path": note_info["path"],
                "type": note_info["type"],
                "activation": round(float(activation), 6),
                "depth": int(best_depth[note_id]),
                "path_ids": best_path[note_id],
                "path_edges": best_path_edges.get(note_id, []),
                "via_predicate": None
                if not best_path_edges.get(note_id)
                else str(best_path_edges[note_id][-1]["predicate"]),
                "via_weight": None
                if not best_path_edges.get(note_id)
                else float(best_path_edges[note_id][-1]["weight"]),
            }
        )
    results.sort(key=lambda item: (-float(item["activation"]), str(item["note_id"])))
    return results


def configured_think_settings(atlas_root: Path | str) -> dict[str, Any]:
    config = load_config(root=atlas_root)
    raw = config.get("think", {}) if isinstance(config, dict) else {}
    return raw if isinstance(raw, dict) else {}
