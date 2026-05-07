from __future__ import annotations

import json
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .config import load_config
from .index import Index
from .operating_truth import list_operating_truth


OPERATIONAL_KEYWORDS = {
    "working",
    "pending",
    "committed",
    "commitment",
    "next",
    "todo",
    "blocked",
    "doing",
}
PROFILE_KEYWORDS = {
    "my",
    "name",
    "prefer",
    "style",
    "identity",
    "who",
}
GRAPH_KEYWORDS = {
    "relationship",
    "relate",
    "status",
    "depends",
    "supports",
    "connected",
}
CORPUS_KEYWORDS = {
    "when",
    "recently",
    "history",
    "discuss",
    "happened",
    "yesterday",
}

INTENT_TYPE_BOOSTS = {
    "procedural": {"ref": 2.0, "guide": 1.5},
    "emotional": {"daily": 2.0, "therapy": 1.5},
    "factual": {"ref": 2.0, "entity": 1.5},
}
INTENT_TAG_BOOSTS = {
    "procedural": {"guide": 1.5},
    "emotional": {"therapy": 1.5, "reflection": 1.5},
    "factual": {"reference": 1.0},
}
RELATIONAL_STOPWORDS = {
    "who",
    "is",
    "are",
    "my",
    "the",
    "a",
    "an",
    "with",
    "relationship",
}


def _config(atlas_root: Path | str) -> dict[str, Any]:
    config = load_config(root=atlas_root)
    raw = config.get("query_routing", {}) if isinstance(config, dict) else {}
    return raw if isinstance(raw, dict) else {}


def _db_path(atlas_root: Path | str) -> Path:
    return Path(atlas_root).expanduser() / ".cartographer" / "index.db"


def _connect(atlas_root: Path | str) -> sqlite3.Connection:
    Index(Path(atlas_root).expanduser())
    connection = sqlite3.connect(str(_db_path(atlas_root)))
    connection.row_factory = sqlite3.Row
    return connection


@contextmanager
def _connection(atlas_root: Path | str):
    connection = _connect(atlas_root)
    try:
        yield connection
    finally:
        connection.close()


def analyze_query(query: str) -> list[str]:
    lowered = query.lower()
    tokens = set(re.findall(r"[a-z0-9_]+", lowered))
    shelves: list[str] = []
    if tokens & OPERATIONAL_KEYWORDS:
        shelves.append("operating-truth")
    if tokens & PROFILE_KEYWORDS and ("who am i" in lowered or "my " in lowered or "i prefer" in lowered):
        shelves.append("profile")
    if tokens & GRAPH_KEYWORDS:
        shelves.append("graph")
    if tokens & CORPUS_KEYWORDS:
        shelves.append("corpus")
    if not shelves:
        return ["operating-truth", "profile", "graph", "corpus"]
    ordered = []
    for shelf in shelves + ["graph", "corpus", "profile", "operating-truth"]:
        if shelf not in ordered:
            ordered.append(shelf)
    return ordered


def detect_intent(query: str) -> str:
    """Returns one of: procedural, emotional, relational, factual, general."""
    q = query.lower().strip()
    if q.startswith("how") or any(
        word in q for word in ("steps", "setup", "install", "configure", "command")
    ):
        return "procedural"
    if any(
        word in q
        for word in ("feel", "feeling", "emotion", "why do i", "i keep", "overwhelm")
    ):
        return "emotional"
    if q.startswith("who") or "relationship with" in q or "my relationship" in q:
        return "relational"
    if q.startswith("what is") or q.startswith("define") or "definition" in q:
        return "factual"
    return "general"


def _compact(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 1)].rstrip() + "..."


def _term_score(text: str, query: str) -> float:
    if not text:
        return 0.0
    lowered = text.lower()
    tokens = [token for token in re.findall(r"[a-z0-9_]+", query.lower()) if len(token) >= 2]
    if not tokens:
        return 0.0
    score = 0.0
    for token in tokens:
        score += lowered.count(token)
    return score


def _intent_boost(note_type: str, tags: list[str], intent: str) -> float:
    score = INTENT_TYPE_BOOSTS.get(intent, {}).get(note_type, 0.0)
    tag_boosts = INTENT_TAG_BOOSTS.get(intent, {})
    normalized_tags = {tag.lower().strip() for tag in tags}
    for tag, boost in tag_boosts.items():
        if tag in normalized_tags:
            score += boost
    return score


def _retrieve_operating_truth(atlas_root: Path, query: str, budget: int) -> list[dict[str, Any]]:
    items = list_operating_truth(atlas_root)
    ranked = sorted(
        items,
        key=lambda item: (_term_score(item["content"], query), item["priority"], item["updated_at"]),
        reverse=True,
    )
    results: list[dict[str, Any]] = []
    remaining = budget
    for item in ranked:
        text = f"{item['type']}: {item['content']}"
        if _term_score(text, query) <= 0 and "operating-truth" not in analyze_query(query):
            continue
        snippet = _compact(text, min(remaining, 220))
        if not snippet:
            continue
        results.append(
            {
                "id": item["id"],
                "shelf": "operating-truth",
                "kind": "operating_truth",
                "label": item["type"],
                "score": _term_score(text, query) + 10.0,
                "text": snippet,
                "path": None,
            }
        )
        remaining -= len(snippet)
        if remaining <= 0:
            break
    return results


def _profile_sources(atlas_root: Path) -> list[tuple[str, Path]]:
    candidates = [
        ("claude", atlas_root / "CLAUDE.md"),
        ("soul", atlas_root / "SOUL.md"),
        ("config", atlas_root / ".cartographer" / "config.toml"),
    ]
    return [(name, path) for name, path in candidates if path.exists()]


def _retrieve_profile(atlas_root: Path, query: str, budget: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    remaining = budget
    for name, path in _profile_sources(atlas_root):
        text = path.read_text(encoding="utf-8")
        score = _term_score(text, query)
        if score <= 0 and "profile" not in analyze_query(query):
            continue
        snippet = _compact(text, min(remaining, 320))
        results.append(
            {
                "id": name,
                "shelf": "profile",
                "kind": "profile",
                "label": path.name,
                "score": score + 5.0,
                "text": snippet,
                "path": str(path),
            }
        )
        remaining -= len(snippet)
        if remaining <= 0:
            break
    return results


def _search_notes(
    atlas_root: Path,
    query: str,
    *,
    allowed_types: set[str],
    budget: int,
    shelf: str,
    recent_days: int | None = None,
    intent: str = "general",
) -> list[dict[str, Any]]:
    params: list[Any] = []
    having_clause = ""
    if recent_days is not None:
        cutoff = time.time() - (max(recent_days, 0) * 86400)
        having_clause = "HAVING MAX(a.accessed_at) >= ?"
        params.append(cutoff)
    with _connection(atlas_root) as connection:
        rows = connection.execute(
            f"""
            SELECT
                n.id,
                n.path,
                n.title,
                n.type,
                n.tags,
                n.body,
                n.modified,
                MAX(a.accessed_at) AS last_accessed,
                COUNT(a.note_id) AS access_count
            FROM notes n
            LEFT JOIN access_log a ON a.note_id = n.id
            GROUP BY n.id
            {having_clause}
            ORDER BY n.modified DESC
            """,
            params,
        ).fetchall()
    ranked: list[dict[str, Any]] = []
    for row in rows:
        note_type = str(row["type"] or "note")
        if allowed_types and note_type not in allowed_types:
            continue
        text = f"{row['title'] or row['id']}\n\n{row['body'] or ''}"
        score = _term_score(text, query)
        if score <= 0:
            continue
        access_count = int(row["access_count"] or 0)
        last_accessed = None if row["last_accessed"] is None else float(row["last_accessed"])
        access_boost = min(access_count, 10) * 0.3
        recency_boost = 0.0
        if last_accessed is not None:
            days_ago = (time.time() - last_accessed) / 86400
            recency_boost = max(0.0, 2.0 - (days_ago / 30))
        try:
            tags = json.loads(str(row["tags"] or "[]"))
        except json.JSONDecodeError:
            tags = []
        if not isinstance(tags, list):
            tags = []
        normalized_tags = [str(tag) for tag in tags]
        score += access_boost + recency_boost + _intent_boost(note_type, normalized_tags, intent)
        ranked.append(
            {
                "id": str(row["id"]),
                "shelf": shelf,
                "kind": "note",
                "label": str(row["title"] or row["id"]),
                "score": score,
                "text": _compact(text, min(budget, 420)),
                "path": str(row["path"]),
                "note_type": note_type,
                "tags": normalized_tags,
                "access_count": access_count,
                "last_accessed": last_accessed,
            }
        )
    ranked.sort(key=lambda item: (item["score"], item["label"]), reverse=True)
    packed: list[dict[str, Any]] = []
    remaining = budget
    for item in ranked:
        if remaining <= 0:
            break
        snippet = _compact(str(item["text"]), min(remaining, len(str(item["text"]))))
        item = dict(item)
        item["text"] = snippet
        packed.append(item)
        remaining -= len(snippet)
    return packed


def _retrieve_graph(
    atlas_root: Path,
    query: str,
    budget: int,
    *,
    recent_days: int | None = None,
    intent: str = "general",
) -> list[dict[str, Any]]:
    if intent == "relational":
        return _search_wires_by_note_title(atlas_root, query, budget)
    return _search_notes(
        atlas_root,
        query,
        allowed_types={"entity", "project", "note", "index"},
        budget=budget,
        shelf="graph",
        recent_days=recent_days,
        intent=intent,
    )


def _retrieve_corpus(
    atlas_root: Path,
    query: str,
    budget: int,
    *,
    recent_days: int | None = None,
    intent: str = "general",
) -> list[dict[str, Any]]:
    return _search_notes(
        atlas_root,
        query,
        allowed_types={"agent-log", "daily", "ref", "task-list", "note"},
        budget=budget,
        shelf="corpus",
        recent_days=recent_days,
        intent=intent,
    )


def _relational_terms(query: str) -> list[str]:
    terms = []
    for token in re.findall(r"[a-z0-9_]+", query.lower()):
        if len(token) < 3 or token in RELATIONAL_STOPWORDS:
            continue
        terms.append(token)
    return terms


def _search_wires_by_note_title(
    atlas_root: Path,
    query: str,
    budget: int,
) -> list[dict[str, Any]]:
    terms = _relational_terms(query)
    if not terms:
        return []
    clauses: list[str] = []
    params: list[Any] = []
    for term in terms:
        clauses.append(
            """
            (
                LOWER(COALESCE(sn.title, sn.id, '')) LIKE ?
                OR LOWER(COALESCE(tn.title, tn.id, '')) LIKE ?
            )
            """
        )
        params.extend([f"%{term}%", f"%{term}%"])
    with _connection(atlas_root) as connection:
        rows = connection.execute(
            f"""
            SELECT
                w.source_note,
                w.source_block,
                w.target_note,
                w.target_block,
                w.predicate,
                w.weight,
                w.bidirectional,
                w.emotional_valence,
                w.energy_impact,
                w.avoidance_risk,
                w.current_state,
                w.path,
                w.line,
                sn.title AS source_title,
                sn.path AS source_path,
                tn.title AS target_title,
                tn.path AS target_path
            FROM wires w
            LEFT JOIN notes sn ON sn.id = w.source_note
            LEFT JOIN notes tn ON tn.id = w.target_note
            WHERE {" OR ".join(clauses)}
            ORDER BY w.path ASC, w.line ASC
            """,
            params,
        ).fetchall()

    results: list[dict[str, Any]] = []
    remaining = budget
    for row in rows:
        if remaining <= 0:
            break
        source_label = str(row["source_title"] or row["source_note"])
        target_label = str(row["target_title"] or row["target_note"])
        arrow = "<->" if bool(row["bidirectional"]) else f"--{row['predicate']}-->"
        label = f"{source_label} {arrow} {target_label}"
        metadata = []
        for key, rendered in (
            ("emotional_valence", "valence"),
            ("energy_impact", "energy"),
            ("avoidance_risk", "avoidance"),
            ("current_state", "state"),
        ):
            if row[key] is not None:
                metadata.append(f"{rendered}={row[key]}")
        text = label
        if metadata:
            text += " [" + ", ".join(metadata) + "]"
        snippet = _compact(text, min(remaining, 320))
        results.append(
            {
                "id": f"{row['source_note']}->{row['target_note']}:{row['predicate']}:{row['line']}",
                "shelf": "graph",
                "kind": "wire",
                "label": label,
                "score": 20.0 + _term_score(label, query),
                "text": snippet,
                "path": str(row["path"]),
                "source_note": str(row["source_note"]),
                "source_title": source_label,
                "source_path": None if row["source_path"] is None else str(row["source_path"]),
                "target_note": str(row["target_note"]),
                "target_title": target_label,
                "target_path": None if row["target_path"] is None else str(row["target_path"]),
                "predicate": str(row["predicate"]),
                "bidirectional": bool(row["bidirectional"]),
                "emotional_valence": None
                if row["emotional_valence"] is None
                else str(row["emotional_valence"]),
                "energy_impact": None if row["energy_impact"] is None else str(row["energy_impact"]),
                "avoidance_risk": None
                if row["avoidance_risk"] is None
                else str(row["avoidance_risk"]),
                "current_state": None if row["current_state"] is None else str(row["current_state"]),
            }
        )
        remaining -= len(snippet)
    return results


def _seed_notes(
    connection: sqlite3.Connection,
    seed_query: str,
    *,
    limit: int = 5,
) -> list[sqlite3.Row]:
    rows = connection.execute(
        """
        SELECT id, title, path, body
        FROM notes
        ORDER BY modified DESC
        """
    ).fetchall()
    scored = [
        (_term_score(f"{row['title'] or row['id']}\n\n{row['body'] or ''}", seed_query), row)
        for row in rows
    ]
    matches = [(score, row) for score, row in scored if score > 0]
    matches.sort(key=lambda item: (item[0], str(item[1]["title"] or item[1]["id"])), reverse=True)
    return [row for _score, row in matches[:limit]]


def traverse_via(atlas_root: Path | str, seed_query: str, predicate: str) -> list[dict[str, Any]]:
    atlas_root = Path(atlas_root).expanduser()
    with _connection(atlas_root) as connection:
        seed_rows = _seed_notes(connection, seed_query, limit=5)
        results: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, int]] = set()
        for seed in seed_rows:
            seed_id = str(seed["id"])
            rows = connection.execute(
                """
                SELECT
                    w.source_note,
                    w.source_block,
                    w.target_note,
                    w.target_block,
                    w.predicate,
                    w.bidirectional,
                    w.emotional_valence,
                    w.energy_impact,
                    w.avoidance_risk,
                    w.current_state,
                    w.path AS wire_path,
                    w.line,
                    sn.title AS source_title,
                    sn.path AS source_path,
                    tn.title AS target_title,
                    tn.path AS target_path
                FROM wires w
                LEFT JOIN notes sn ON sn.id = w.source_note
                LEFT JOIN notes tn ON tn.id = w.target_note
                WHERE (w.source_note = ? OR w.target_note = ?)
                  AND w.predicate = ?
                ORDER BY w.path ASC, w.line ASC
                """,
                (seed_id, seed_id, predicate),
            ).fetchall()
            seed_title = str(seed["title"] or seed_id)
            for row in rows:
                direction = "outbound" if str(row["source_note"]) == seed_id else "inbound"
                connected_id = (
                    str(row["target_note"]) if direction == "outbound" else str(row["source_note"])
                )
                key = (seed_id, connected_id, str(row["predicate"]), int(row["line"]))
                if key in seen:
                    continue
                seen.add(key)
                connected_title = (
                    str(row["target_title"] or row["target_note"])
                    if direction == "outbound"
                    else str(row["source_title"] or row["source_note"])
                )
                if direction == "outbound":
                    connected_path = None if row["target_path"] is None else str(row["target_path"])
                else:
                    connected_path = None if row["source_path"] is None else str(row["source_path"])
                results.append(
                    {
                        "id": f"{seed_id}:{connected_id}:{row['predicate']}:{row['line']}",
                        "seed_id": seed_id,
                        "seed_title": seed_title,
                        "seed_path": str(seed["path"]),
                        "label": connected_title,
                        "path": connected_path,
                        "connected_note": connected_id,
                        "predicate": str(row["predicate"]),
                        "direction": direction,
                        "bidirectional": bool(row["bidirectional"]),
                        "valence": None
                        if row["emotional_valence"] is None
                        else str(row["emotional_valence"]),
                        "emotional_valence": None
                        if row["emotional_valence"] is None
                        else str(row["emotional_valence"]),
                        "energy_impact": None
                        if row["energy_impact"] is None
                        else str(row["energy_impact"]),
                        "avoidance_risk": None
                        if row["avoidance_risk"] is None
                        else str(row["avoidance_risk"]),
                        "current_state": None
                        if row["current_state"] is None
                        else str(row["current_state"]),
                        "wire_path": str(row["wire_path"]),
                        "line": int(row["line"]),
                    }
                )
    return results


def reciprocal_rank_fusion(
    shelf_results: dict[str, list[dict[str, Any]]],
    *,
    k: int = 60,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for shelf, items in shelf_results.items():
        for rank, item in enumerate(items, start=1):
            key = f"{item['shelf']}::{item['id']}"
            payload = merged.setdefault(key, dict(item))
            payload.setdefault("rrf_score", 0.0)
            payload["rrf_score"] += 1.0 / float(k + rank)
            payload.setdefault("routes", [])
            if shelf not in payload["routes"]:
                payload["routes"].append(shelf)
    return sorted(
        merged.values(),
        key=lambda item: (float(item.get("rrf_score", 0.0)), float(item.get("score", 0.0))),
        reverse=True,
    )


def _pack_budget(items: list[dict[str, Any]], total_budget: int) -> list[dict[str, Any]]:
    packed: list[dict[str, Any]] = []
    remaining = max(0, total_budget)
    for item in items:
        if remaining <= 0:
            break
        text = str(item["text"])
        snippet = _compact(text, min(len(text), remaining))
        payload = dict(item)
        payload["text"] = snippet
        packed.append(payload)
        remaining -= len(snippet)
    return packed


def _budget_mode(output_budget: int | None) -> str:
    if output_budget is None or output_budget >= 2000:
        return "full"
    if output_budget >= 500:
        return "summary"
    return "title"


def _estimated_render_size(item: dict[str, Any], mode: str) -> int:
    if mode == "title":
        return len(str(item.get("label") or "")) + 1
    if mode == "summary":
        return (
            len(str(item.get("shelf") or ""))
            + len(str(item.get("label") or ""))
            + len(str(item.get("text") or ""))
            + 8
        )
    return (
        len(str(item.get("shelf") or ""))
        + len(str(item.get("label") or ""))
        + len(str(item.get("path") or ""))
        + len(str(item.get("text") or ""))
        + 8
    )


def _limit_items_for_budget(
    items: list[dict[str, Any]],
    output_budget: int | None,
    mode: str,
) -> list[dict[str, Any]]:
    if output_budget is None:
        return items
    packed: list[dict[str, Any]] = []
    remaining = max(0, output_budget)
    for item in items:
        estimated = _estimated_render_size(item, mode)
        if packed and estimated > remaining:
            break
        packed.append(item)
        remaining -= estimated
        if remaining <= 0:
            break
    return packed


def _format_for_budget(
    items: list[dict[str, Any]],
    output_budget: int | None,
) -> list[dict[str, Any]]:
    mode = _budget_mode(output_budget)
    if mode == "full":
        return _limit_items_for_budget(items, output_budget, mode)

    packed: list[dict[str, Any]] = []
    for item in items:
        if mode == "summary":
            payload = dict(item)
            payload["text"] = _compact(str(payload.get("text") or ""), 120)
            payload.pop("path", None)
        else:
            payload = {
                "id": item["id"],
                "label": item["label"],
                "shelf": item["shelf"],
            }
        packed.append(payload)
    return _limit_items_for_budget(packed, output_budget, mode)


def route_query(
    atlas_root: Path | str,
    query: str,
    *,
    output_budget: int | None = None,
    recent_days: int | None = None,
) -> dict[str, Any]:
    atlas_root = Path(atlas_root).expanduser()
    settings = _config(atlas_root)
    routes = analyze_query(query)
    intent = detect_intent(query)
    if intent == "relational":
        routes = ["graph", *[route for route in routes if route != "graph"]]
    if recent_days is not None:
        routes = [route for route in routes if route in {"graph", "corpus"}]
        if not routes:
            routes = ["graph", "corpus"]
    budgets = {
        "operating-truth": int(settings.get("operating_truth_budget", 500) or 500),
        "profile": int(settings.get("profile_budget", 500) or 500),
        "graph": int(settings.get("graph_budget", 2000) or 2000),
        "corpus": int(settings.get("corpus_budget", 1000) or 1000),
    }
    total_budget = int(settings.get("default_total_budget", 4000) or 4000)
    if output_budget is not None:
        total_budget = min(total_budget, max(output_budget, 0))
    rrf_k = int(settings.get("rrf_k", 60) or 60)

    shelf_results: dict[str, list[dict[str, Any]]] = {}
    for route in routes:
        if route == "operating-truth":
            shelf_results[route] = _retrieve_operating_truth(atlas_root, query, budgets[route])
        elif route == "profile":
            shelf_results[route] = _retrieve_profile(atlas_root, query, budgets[route])
        elif route == "graph":
            shelf_results[route] = _retrieve_graph(
                atlas_root,
                query,
                budgets[route],
                recent_days=recent_days,
                intent=intent,
            )
        elif route == "corpus":
            shelf_results[route] = _retrieve_corpus(
                atlas_root,
                query,
                budgets[route],
                recent_days=recent_days,
                intent=intent,
            )
        else:
            shelf_results[route] = []

    merged = reciprocal_rank_fusion(shelf_results, k=rrf_k)
    packed = _pack_budget(merged, total_budget)
    formatted = _format_for_budget(packed, output_budget)
    return {
        "query": query,
        "routes": routes,
        "budgets": budgets,
        "total_budget": total_budget,
        "output_budget": output_budget,
        "output_mode": _budget_mode(output_budget),
        "recent_days": recent_days,
        "intent": intent,
        "results": formatted,
    }
