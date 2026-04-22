from __future__ import annotations

from collections import defaultdict, deque
import sqlite3
from pathlib import Path
from typing import Any

from .index import Index


_RISK_ORDER = {"high": 3, "medium": 2, "low": 1, "none": 0}


def _note_titles(connection: sqlite3.Connection) -> dict[str, str]:
    rows = connection.execute("SELECT id, title FROM notes ORDER BY id ASC").fetchall()
    return {str(row[0]): str(row[1] or row[0]) for row in rows}


def _wire_adjacency(connection: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rows = connection.execute(
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
            valence_note,
            path,
            line
        FROM wires
        ORDER BY path ASC, line ASC
        """
    ).fetchall()
    for row in rows:
        payload = {
            "predicate": str(row[2]),
            "relationship": None if row[3] is None else str(row[3]),
            "bidirectional": bool(row[4]),
            "emotional_valence": None if row[5] is None else str(row[5]),
            "energy_impact": None if row[6] is None else str(row[6]),
            "avoidance_risk": None if row[7] is None else str(row[7]),
            "growth_edge": None if row[8] is None else bool(row[8]),
            "current_state": None if row[9] is None else str(row[9]),
            "since": None if row[10] is None else str(row[10]),
            "until": None if row[11] is None else str(row[11]),
            "valence_note": None if row[12] is None else str(row[12]),
            "path": str(row[13]),
            "line": int(row[14]),
        }
        source_note = str(row[0])
        target_note = str(row[1])
        adjacency[source_note].append(
            {
                **payload,
                "neighbor": target_note,
                "direction": "outgoing",
            }
        )
        adjacency[target_note].append(
            {
                **payload,
                "neighbor": source_note,
                "direction": "incoming",
            }
        )
    return adjacency


def _matches_filters(
    edge: dict[str, Any],
    *,
    filter_avoidance: str | None,
    filter_growth_edge: bool,
) -> bool:
    if filter_growth_edge and not bool(edge.get("growth_edge")):
        return False
    if filter_avoidance is not None:
        risk = str(edge.get("avoidance_risk") or "").lower()
        if risk not in _RISK_ORDER:
            return False
        if _RISK_ORDER[risk] < _RISK_ORDER[filter_avoidance]:
            return False
    return True


def walk_atlas(
    atlas_root: Path | str,
    start_id: str,
    *,
    depth: int = 2,
    filter_avoidance: str | None = None,
    filter_growth_edge: bool = False,
) -> list[dict[str, Any]]:
    atlas_root = Path(atlas_root).expanduser()
    index = Index(atlas_root)
    canonical_start = index.canonicalize_note_ref(start_id) or start_id

    connection = sqlite3.connect(str(index.db_path))
    try:
        titles = _note_titles(connection)
        adjacency = _wire_adjacency(connection)
    finally:
        connection.close()

    if canonical_start not in titles:
        raise ValueError(f"note not found: {start_id}")

    queue: deque[tuple[str, int, list[str]]] = deque([(canonical_start, 0, [canonical_start])])
    seen_depth: dict[str, int] = {canonical_start: 0}
    traversals: list[dict[str, Any]] = []
    seen_traversal_keys: set[tuple[int, str, str, str, int, str]] = set()

    while queue:
        current_note, current_depth, path_ids = queue.popleft()
        if current_depth >= depth:
            continue
        next_depth = current_depth + 1
        for edge in adjacency.get(current_note, []):
            if not _matches_filters(
                edge,
                filter_avoidance=filter_avoidance,
                filter_growth_edge=filter_growth_edge,
            ):
                continue
            neighbor = str(edge["neighbor"])
            traversal_key = (
                next_depth,
                current_note,
                neighbor,
                str(edge["predicate"]),
                int(edge["line"]),
                str(edge["direction"]),
            )
            if traversal_key not in seen_traversal_keys:
                seen_traversal_keys.add(traversal_key)
                traversals.append(
                    {
                        "depth": next_depth,
                        "from_note": current_note,
                        "from_title": titles.get(current_note, current_note),
                        "to_note": neighbor,
                        "to_title": titles.get(neighbor, neighbor),
                        "direction": str(edge["direction"]),
                        "predicate": str(edge["predicate"]),
                        "relationship": edge.get("relationship"),
                        "bidirectional": bool(edge.get("bidirectional")),
                        "emotional_valence": edge.get("emotional_valence"),
                        "energy_impact": edge.get("energy_impact"),
                        "avoidance_risk": edge.get("avoidance_risk"),
                        "growth_edge": edge.get("growth_edge"),
                        "current_state": edge.get("current_state"),
                        "since": edge.get("since"),
                        "until": edge.get("until"),
                        "valence_note": edge.get("valence_note"),
                        "path": edge.get("path"),
                        "line": edge.get("line"),
                        "path_ids": [*path_ids, neighbor],
                    }
                )

            if next_depth >= depth:
                continue
            previous_depth = seen_depth.get(neighbor)
            if previous_depth is not None and previous_depth <= next_depth:
                continue
            seen_depth[neighbor] = next_depth
            queue.append((neighbor, next_depth, [*path_ids, neighbor]))

    traversals.sort(
        key=lambda item: (
            int(item["depth"]),
            str(item["from_note"]),
            str(item["predicate"]),
            str(item["to_note"]),
            str(item["direction"]),
        )
    )
    return traversals
