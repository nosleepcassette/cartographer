from __future__ import annotations

import re
import sqlite3
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
) -> list[dict[str, Any]]:
    with _connection(atlas_root) as connection:
        rows = connection.execute(
            """
            SELECT id, path, title, type, body, modified
            FROM notes
            ORDER BY modified DESC
            """
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


def _retrieve_graph(atlas_root: Path, query: str, budget: int) -> list[dict[str, Any]]:
    return _search_notes(
        atlas_root,
        query,
        allowed_types={"entity", "project", "note", "index"},
        budget=budget,
        shelf="graph",
    )


def _retrieve_corpus(atlas_root: Path, query: str, budget: int) -> list[dict[str, Any]]:
    return _search_notes(
        atlas_root,
        query,
        allowed_types={"agent-log", "daily", "ref", "task-list", "note"},
        budget=budget,
        shelf="corpus",
    )


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


def route_query(atlas_root: Path | str, query: str) -> dict[str, Any]:
    atlas_root = Path(atlas_root).expanduser()
    settings = _config(atlas_root)
    routes = analyze_query(query)
    budgets = {
        "operating-truth": int(settings.get("operating_truth_budget", 500) or 500),
        "profile": int(settings.get("profile_budget", 500) or 500),
        "graph": int(settings.get("graph_budget", 2000) or 2000),
        "corpus": int(settings.get("corpus_budget", 1000) or 1000),
    }
    total_budget = int(settings.get("default_total_budget", 4000) or 4000)
    rrf_k = int(settings.get("rrf_k", 60) or 60)

    shelf_results: dict[str, list[dict[str, Any]]] = {}
    for route in routes:
        if route == "operating-truth":
            shelf_results[route] = _retrieve_operating_truth(atlas_root, query, budgets[route])
        elif route == "profile":
            shelf_results[route] = _retrieve_profile(atlas_root, query, budgets[route])
        elif route == "graph":
            shelf_results[route] = _retrieve_graph(atlas_root, query, budgets[route])
        elif route == "corpus":
            shelf_results[route] = _retrieve_corpus(atlas_root, query, budgets[route])
        else:
            shelf_results[route] = []

    merged = reciprocal_rank_fusion(shelf_results, k=rrf_k)
    packed = _pack_budget(merged, total_budget)
    return {
        "query": query,
        "routes": routes,
        "budgets": budgets,
        "total_budget": total_budget,
        "results": packed,
    }
