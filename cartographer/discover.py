from __future__ import annotations

from collections import Counter
from datetime import date
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from .atlas import Atlas
from .config import load_config
from .notes import Note
from .wires import insert_wire_comment, parse_wire_comments, render_wire_comment


_WORD_RE = re.compile(r"[a-z0-9]{3,}", re.IGNORECASE)
_STOP_WORDS = {
    "about",
    "after",
    "again",
    "agent",
    "atlas",
    "because",
    "been",
    "being",
    "between",
    "build",
    "built",
    "cart",
    "cartographer",
    "could",
    "daily",
    "from",
    "have",
    "into",
    "just",
    "knowledge",
    "local",
    "memory",
    "more",
    "note",
    "notes",
    "project",
    "really",
    "same",
    "session",
    "should",
    "some",
    "that",
    "their",
    "them",
    "there",
    "these",
    "they",
    "this",
    "through",
    "very",
    "what",
    "when",
    "where",
    "with",
    "your",
}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _simple_frontmatter(note: Note) -> dict[str, str]:
    allowed: dict[str, str] = {}
    for key, value in note.frontmatter.items():
        if key in {"id", "title", "created", "modified", "links", "tags"}:
            continue
        if isinstance(value, (str, int, float, bool)):
            rendered = str(value).strip()
            if rendered:
                allowed[str(key)] = rendered
    return allowed


def _keywords(title: str, body: str, *, limit: int = 10) -> set[str]:
    counts: Counter[str] = Counter()
    for match in _WORD_RE.finditer(f"{title}\n{body}"):
        word = match.group(0).lower()
        if word in _STOP_WORDS:
            continue
        counts[word] += 1
    return {word for word, _count in counts.most_common(limit)}


def _note_payload(atlas_root: Path) -> list[dict[str, Any]]:
    connection = sqlite3.connect(str(atlas_root / ".cartographer" / "index.db"))
    try:
        rows = connection.execute(
            "SELECT id, path, title, type, tags, links, body FROM notes ORDER BY id ASC"
        ).fetchall()
    finally:
        connection.close()

    payload: list[dict[str, Any]] = []
    for row in rows:
        path = Path(str(row[1]))
        note = Note.from_file(path)
        try:
            tags = {
                str(item).strip().lower()
                for item in json.loads(row[4] or "[]")
                if str(item).strip()
            }
        except Exception:
            tags = set()
        try:
            links = {
                str(item).strip().lower()
                for item in json.loads(row[5] or "[]")
                if str(item).strip()
            }
        except Exception:
            links = set()
        title = str(row[2] or row[0])
        body = str(row[6] or "")
        payload.append(
            {
                "id": str(row[0]),
                "path": path,
                "title": title,
                "type": str(row[3] or "note"),
                "tags": tags,
                "links": links,
                "keywords": _keywords(title, body),
                "frontmatter": _simple_frontmatter(note),
            }
        )
    return payload


def _existing_wire_pairs(atlas_root: Path) -> set[frozenset[str]]:
    connection = sqlite3.connect(str(atlas_root / ".cartographer" / "index.db"))
    try:
        rows = connection.execute(
            "SELECT source_note, target_note FROM wires"
        ).fetchall()
    finally:
        connection.close()
    return {frozenset((str(source), str(target))) for source, target in rows}


def _frontmatter_overlap(left: dict[str, str], right: dict[str, str]) -> set[str]:
    return {
        key
        for key in left.keys() & right.keys()
        if left[key] == right[key]
    }


def _proposal_reasons(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    shared_tags = sorted(left["tags"] & right["tags"])
    shared_links = sorted(left["links"] & right["links"])
    shared_keywords = sorted(left["keywords"] & right["keywords"])
    shared_frontmatter = sorted(_frontmatter_overlap(left["frontmatter"], right["frontmatter"]))
    return {
        "tags": shared_tags,
        "links": shared_links,
        "keywords": shared_keywords,
        "frontmatter": shared_frontmatter,
        "type_match": left["type"] == right["type"],
    }


def _similarity(left: dict[str, Any], right: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    reasons = _proposal_reasons(left, right)
    score = 0.0
    score += 0.3 * _jaccard(left["tags"], right["tags"])
    score += 0.2 * _jaccard(left["links"], right["links"])
    score += 0.3 * _jaccard(left["keywords"], right["keywords"])
    if reasons["type_match"]:
        score += 0.1
    if left["frontmatter"] and right["frontmatter"]:
        overlap = len(reasons["frontmatter"])
        union = len(set(left["frontmatter"]) | set(right["frontmatter"]))
        score += 0.1 * (0.0 if union == 0 else overlap / union)
    return round(score, 6), reasons


def configured_discover_settings(atlas_root: Path | str) -> dict[str, Any]:
    config = load_config(root=atlas_root)
    raw = config.get("discover", {}) if isinstance(config, dict) else {}
    return raw if isinstance(raw, dict) else {}


def discover_bridges(
    atlas_root: Path | str,
    *,
    threshold: float = 0.6,
    max_proposals: int | None = None,
) -> list[dict[str, Any]]:
    atlas_root = Path(atlas_root).expanduser()
    notes = _note_payload(atlas_root)
    existing_pairs = _existing_wire_pairs(atlas_root)

    proposals: list[dict[str, Any]] = []
    for index, left in enumerate(notes):
        for right in notes[index + 1 :]:
            pair_key = frozenset((left["id"], right["id"]))
            if pair_key in existing_pairs:
                continue
            score, reasons = _similarity(left, right)
            if score <= threshold:
                continue
            proposals.append(
                {
                    "score": score,
                    "left_id": left["id"],
                    "left_title": left["title"],
                    "left_type": left["type"],
                    "right_id": right["id"],
                    "right_title": right["title"],
                    "right_type": right["type"],
                    "reasons": reasons,
                }
            )

    proposals.sort(
        key=lambda item: (
            -float(item["score"]),
            str(item["left_id"]),
            str(item["right_id"]),
        )
    )
    if max_proposals is not None:
        proposals = proposals[:max(0, max_proposals)]
    return proposals


def accept_bridge_proposals(
    atlas_root: Path | str,
    proposals: list[dict[str, Any]],
) -> int:
    atlas_root = Path(atlas_root).expanduser()
    if not proposals:
        return 0
    atlas = Atlas(root=atlas_root)
    created = 0
    touched_paths: set[Path] = set()

    for proposal in proposals:
        source_id, target_id = sorted(
            (str(proposal["left_id"]), str(proposal["right_id"]))
        )
        source_path = atlas.resolve_note_path(source_id)
        if source_path is None:
            continue
        note = Note.from_file(source_path)
        note_id = str(note.frontmatter.get("id") or source_path.stem)
        existing_wires, _ = parse_wire_comments(note.body, note_id=note_id, path=source_path)
        if any(
            wire.target_note == target_id and wire.predicate == "relates_to"
            for wire in existing_wires
        ):
            continue
        comment = render_wire_comment(
            target_note=target_id,
            target_block=None,
            predicate="relates_to",
            relationship="relates_to",
            bidirectional=True,
        )
        insert_wire_comment(note, source_block=None, comment=comment)
        note.frontmatter["modified"] = date.today().isoformat()
        note.write()
        touched_paths.add(source_path)
        created += 1

    if touched_paths:
        atlas.refresh_index()
    return created
