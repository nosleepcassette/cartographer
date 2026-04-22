from __future__ import annotations

from collections import Counter, defaultdict, deque
from datetime import datetime, timedelta
import sqlite3
from pathlib import Path
from typing import Any

from .embed import embeddings_coverage
from .index import Index
from .notes import Note


def _parse_iso_date(value: str | None) -> datetime | None:
    if value is None:
        return None
    candidate = str(value).strip()
    if not candidate:
        return None
    for attempt in (candidate, candidate[:10]):
        try:
            parsed = datetime.fromisoformat(attempt)
        except ValueError:
            continue
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed
    return None


def _file_note_snapshots(atlas_root: Path, index: Index) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for path in index.iter_note_paths():
        note = Note.from_file(path)
        frontmatter = note.frontmatter
        created = _parse_iso_date(str(frontmatter.get("created") or "")) or datetime.fromtimestamp(
            path.stat().st_mtime
        )
        modified = _parse_iso_date(str(frontmatter.get("modified") or "")) or datetime.fromtimestamp(
            path.stat().st_mtime
        )
        snapshots.append(
            {
                "id": str(frontmatter.get("id") or path.stem),
                "title": str(frontmatter.get("title") or path.stem),
                "type": str(frontmatter.get("type") or "note"),
                "path": path,
                "created": created,
                "modified": modified,
            }
        )
    return snapshots


def _load_notes_and_wires(atlas_root: Path) -> tuple[list[sqlite3.Row], list[sqlite3.Row], list[sqlite3.Row]]:
    connection = sqlite3.connect(str(atlas_root / ".cartographer" / "index.db"))
    connection.row_factory = sqlite3.Row
    try:
        notes = connection.execute(
            "SELECT id, path, title, type, modified FROM notes ORDER BY id ASC"
        ).fetchall()
        wires = connection.execute(
            """
            SELECT
                source_note,
                target_note,
                predicate,
                emotional_valence,
                avoidance_risk,
                growth_edge,
                since,
                path,
                line
            FROM wires
            ORDER BY source_note ASC, target_note ASC, predicate ASC
            """
        ).fetchall()
        block_refs = connection.execute(
            "SELECT from_note, to_note FROM block_refs ORDER BY from_note ASC, to_note ASC"
        ).fetchall()
    finally:
        connection.close()
    return notes, wires, block_refs


def _components_without(adjacency: dict[str, set[str]], *, removed: str | None = None) -> int:
    remaining = [node for node in adjacency.keys() if node != removed]
    seen: set[str] = set()
    components = 0
    for node in remaining:
        if node in seen:
            continue
        components += 1
        queue: deque[str] = deque([node])
        seen.add(node)
        while queue:
            current = queue.popleft()
            for neighbor in adjacency.get(current, set()):
                if neighbor == removed or neighbor in seen:
                    continue
                seen.add(neighbor)
                queue.append(neighbor)
    return components


def _bridge_nodes(adjacency: dict[str, set[str]]) -> list[str]:
    base_components = _components_without(adjacency)
    bridges: list[str] = []
    for node, neighbors in adjacency.items():
        if len(neighbors) < 2:
            continue
        if _components_without(adjacency, removed=node) > base_components:
            bridges.append(node)
    return sorted(bridges)


def atlas_stats(atlas_root: Path | str) -> dict[str, Any]:
    atlas_root = Path(atlas_root).expanduser()
    index = Index(atlas_root)
    note_rows, wire_rows, block_ref_rows = _load_notes_and_wires(atlas_root)
    note_snapshots = _file_note_snapshots(atlas_root, index)
    now = datetime.now()
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    notes_by_id = {str(row["id"]): row for row in note_rows}
    note_type_counts = Counter(str(row["type"] or "note") for row in note_rows)
    created_dates = sorted(snapshot["created"] for snapshot in note_snapshots)
    notes_this_week = sum(1 for snapshot in note_snapshots if snapshot["created"] >= week_ago)
    notes_this_month = sum(1 for snapshot in note_snapshots if snapshot["created"] >= month_ago)
    growth_rate = round(notes_this_month / 30.0, 2)

    wire_predicates = Counter(str(row["predicate"]) for row in wire_rows)
    valence_counts = Counter(str(row["emotional_valence"] or "neutral") for row in wire_rows)
    adjacency: dict[str, set[str]] = defaultdict(set)
    wire_degree = Counter()
    for row in wire_rows:
        source = str(row["source_note"])
        target = str(row["target_note"])
        adjacency[source].add(target)
        adjacency[target].add(source)
        wire_degree[source] += 1
        wire_degree[target] += 1

    backlink_inbound = Counter(str(row["to_note"]) for row in block_ref_rows)
    orphans = sorted(
        note_id
        for note_id in notes_by_id
        if wire_degree.get(note_id, 0) == 0 and backlink_inbound.get(note_id, 0) == 0
    )

    connectivity_by_type: dict[str, list[int]] = defaultdict(list)
    for row in note_rows:
        connectivity_by_type[str(row["type"] or "note")].append(wire_degree.get(str(row["id"]), 0))
    isolated_type = min(
        (
            (
                note_type,
                sum(values) / len(values),
            )
            for note_type, values in connectivity_by_type.items()
            if values
        ),
        key=lambda item: (item[1], item[0]),
        default=("none", 0.0),
    )

    duplicate_ids: dict[str, list[str]] = defaultdict(list)
    for snapshot in note_snapshots:
        duplicate_ids[str(snapshot["id"])].append(str(snapshot["path"]))
    duplicate_ids = {
        note_id: paths
        for note_id, paths in duplicate_ids.items()
        if len(paths) > 1
    }

    indexed_paths = {str(row["path"]) for row in note_rows}
    file_paths = {str(path) for path in index.iter_note_paths()}
    missing_from_index = sorted(file_paths - indexed_paths)
    orphan_index_entries = sorted(indexed_paths - file_paths)
    wire_doctor = index.wire_doctor()

    high_avoidance = [
        f"{row['source_note']}↔{row['target_note']}"
        for row in wire_rows
        if str(row["avoidance_risk"] or "").lower() == "high"
    ]
    stale_wires = []
    for row in wire_rows:
        since = _parse_iso_date(None if row["since"] is None else str(row["since"]))
        if since is not None and since <= month_ago:
            stale_wires.append(
                {
                    "source": str(row["source_note"]),
                    "target": str(row["target_note"]),
                    "predicate": str(row["predicate"]),
                    "since": since.date().isoformat(),
                }
            )

    session_count = 0
    daily_count = 0
    for snapshot in note_snapshots:
        if snapshot["modified"] < week_ago:
            continue
        note_type = str(snapshot["type"])
        if note_type in {"agent-log", "session"}:
            session_count += 1
        if note_type == "daily":
            daily_count += 1

    wires_this_week = 0
    for row in wire_rows:
        since = _parse_iso_date(None if row["since"] is None else str(row["since"]))
        if since is not None and since >= week_ago:
            wires_this_week += 1

    status = index.status()
    last_rebuild = None if status["last_rebuild"] is None else datetime.fromtimestamp(status["last_rebuild"])
    coverage = embeddings_coverage(atlas_root)
    warnings: list[str] = []
    if missing_from_index:
        warnings.append(f"{len(missing_from_index)} notes not in index")
    if orphan_index_entries:
        warnings.append(f"{len(orphan_index_entries)} index entries point to missing files")
    if duplicate_ids:
        warnings.append(f"{len(duplicate_ids)} duplicate note id(s) detected")
    if wire_doctor["issue_count"]:
        warnings.append(f"{wire_doctor['issue_count']} wire integrity issue(s)")

    return {
        "summary": {
            "total_notes": len(note_rows),
            "total_wires": len(wire_rows),
            "daily_notes": note_type_counts.get("daily", 0),
        },
        "growth": {
            "by_type": dict(sorted(note_type_counts.items())),
            "notes_this_week": notes_this_week,
            "notes_this_month": notes_this_month,
            "growth_rate_per_day": growth_rate,
            "oldest_note": None if not note_snapshots else min(note_snapshots, key=lambda item: item["created"])["id"],
            "newest_note": None if not note_snapshots else max(note_snapshots, key=lambda item: item["created"])["id"],
            "created_range": {
                "oldest": None if not created_dates else created_dates[0].date().isoformat(),
                "newest": None if not created_dates else created_dates[-1].date().isoformat(),
            },
        },
        "connectivity": {
            "wire_predicates": dict(sorted(wire_predicates.items())),
            "average_wires_per_note": 0.0
            if not note_rows
            else round((sum(wire_degree.values()) / max(len(note_rows), 1)) / 2, 2),
            "orphan_notes": orphans,
            "orphan_percentage": 0.0
            if not note_rows
            else round((len(orphans) / len(note_rows)) * 100, 2),
            "most_connected": [
                {
                    "note_id": note_id,
                    "count": count,
                    "title": str(notes_by_id[note_id]["title"] or note_id),
                }
                for note_id, count in wire_degree.most_common(10)
            ],
            "most_isolated_type": {
                "type": isolated_type[0],
                "average_connectivity": round(isolated_type[1], 2),
            },
            "bridge_nodes": _bridge_nodes(adjacency),
        },
        "emotional_topology": {
            "valence_distribution": dict(sorted(valence_counts.items())),
            "high_avoidance_risk_count": len(high_avoidance),
            "high_avoidance_pairs": high_avoidance,
            "growth_edge_count": sum(1 for row in wire_rows if bool(row["growth_edge"])),
            "stale_wires": stale_wires,
        },
        "health": {
            "index_freshness": {
                "last_rebuild": None if last_rebuild is None else last_rebuild.isoformat(timespec="seconds"),
                "needs_rebuild": index.needs_rebuild(),
            },
            "notes_missing_from_index": missing_from_index,
            "orphan_index_entries": orphan_index_entries,
            "duplicate_note_ids": duplicate_ids,
            "wire_integrity": {
                "issue_count": int(wire_doctor["issue_count"]),
            },
            "embeddings": coverage,
        },
        "activity": {
            "sessions_this_week": session_count,
            "daily_notes_this_week": daily_count,
            "wires_created_this_week": wires_this_week,
        },
        "warnings": warnings,
    }


def render_stats_text(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    growth = payload["growth"]
    connectivity = payload["connectivity"]
    topology = payload["emotional_topology"]
    health = payload["health"]
    activity = payload["activity"]

    most_connected = ", ".join(
        f"{item['note_id']}({item['count']})"
        for item in connectivity["most_connected"][:3]
    ) or "none"
    bridge_nodes = ", ".join(connectivity["bridge_nodes"][:5]) or "none"
    warnings = payload.get("warnings", [])

    lines = [
        "cartographer - atlas stats",
        f"{summary['total_notes']} notes · {summary['total_wires']} wires · {summary['daily_notes']} daily notes",
        "",
        "growth",
        f"  notes this week: {growth['notes_this_week']}  |  this month: {growth['notes_this_month']}  |  rate: {growth['growth_rate_per_day']}/day",
        "  by type: "
        + " ".join(
            f"{note_type}({count})"
            for note_type, count in growth["by_type"].items()
        ),
        "",
        "connectivity",
        f"  avg wires/note: {connectivity['average_wires_per_note']}  |  orphan notes: {len(connectivity['orphan_notes'])} ({connectivity['orphan_percentage']}%)",
        f"  most connected: {most_connected}",
        f"  bridge nodes: {bridge_nodes}",
        "",
        "emotional topology",
        "  valence: "
        + " ".join(
            f"{key}({value})" for key, value in topology["valence_distribution"].items()
        ),
        f"  high-avoidance-risk: {topology['high_avoidance_risk_count']} wires",
        f"  growth edges: {topology['growth_edge_count']} wires",
        "",
        "health",
        f"  index freshness: {health['index_freshness']['last_rebuild'] or 'never'}",
        f"  embeddings: {round(health['embeddings']['coverage'] * 100, 1)}% coverage",
        "",
        "activity",
        f"  sessions this week: {activity['sessions_this_week']}  |  daily notes: {activity['daily_notes_this_week']}  |  wires created this week: {activity['wires_created_this_week']}",
    ]
    for warning in warnings:
        lines.append(f"  ! {warning}")
    return "\n".join(lines) + "\n"
