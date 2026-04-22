from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any

from .config import load_config
from .index import Index
from .notes import Note


POSITIVE_VALENCE = {"positive", "energizing", "supportive"}
NEGATIVE_VALENCE = {"negative", "draining", "harmful"}


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


def _index(atlas_root: Path | str) -> Index:
    return Index(Path(atlas_root).expanduser())


def _today() -> str:
    return date.today().isoformat()


def _temporal_config(atlas_root: Path | str) -> dict[str, Any]:
    config = load_config(root=atlas_root)
    raw = config.get("temporal", {}) if isinstance(config, dict) else {}
    return raw if isinstance(raw, dict) else {}


def _resolve_note_path(atlas_root: Path | str, note_id: str) -> Path:
    path = _index(atlas_root).find_note_path(note_id)
    if path is None:
        raise ValueError(f"note not found: {note_id}")
    return path


def _normalize_frontmatter(note: Note) -> None:
    note.frontmatter.setdefault("valid_from", "")
    note.frontmatter.setdefault("valid_to", "")
    note.frontmatter.setdefault("supersedes", "")
    note.frontmatter.setdefault("superseded_by", "")
    note.frontmatter.setdefault("is_current", True)


def supersede_notes(
    atlas_root: Path | str,
    old_note_id: str,
    new_note_id: str,
) -> dict[str, Any]:
    old_path = _resolve_note_path(atlas_root, old_note_id)
    new_path = _resolve_note_path(atlas_root, new_note_id)
    old_note = Note.from_file(old_path)
    new_note = Note.from_file(new_path)
    now = _today()

    _normalize_frontmatter(old_note)
    _normalize_frontmatter(new_note)

    old_note.frontmatter["superseded_by"] = new_note_id
    old_note.frontmatter["valid_to"] = now
    old_note.frontmatter["is_current"] = False
    old_note.frontmatter.setdefault("valid_from", old_note.frontmatter.get("created", now) or now)
    old_note.frontmatter["modified"] = now

    new_note.frontmatter["supersedes"] = old_note_id
    new_note.frontmatter["valid_from"] = now
    new_note.frontmatter["valid_to"] = ""
    new_note.frontmatter["superseded_by"] = ""
    new_note.frontmatter["is_current"] = True
    new_note.frontmatter["modified"] = now

    old_note.write(ensure_blocks=True)
    new_note.write(ensure_blocks=True)
    _index(atlas_root).rebuild()
    return {
        "old_note": str(old_note.frontmatter.get("id") or old_path.stem),
        "new_note": str(new_note.frontmatter.get("id") or new_path.stem),
        "old_path": str(old_path),
        "new_path": str(new_path),
    }


def temporal_history(atlas_root: Path | str, note_id: str) -> list[dict[str, Any]]:
    with _connection(atlas_root) as connection:
        rows = connection.execute(
            """
            SELECT id, title, type, valid_from, valid_to, supersedes, superseded_by, is_current
            FROM notes
            """
        ).fetchall()
    notes = {str(row["id"]): row for row in rows}
    if note_id not in notes:
        canonical = _index(atlas_root).canonicalize_note_ref(note_id)
        if canonical is not None:
            note_id = canonical
    if note_id not in notes:
        raise ValueError(f"note not found: {note_id}")

    current = note_id
    while current in notes:
        previous = notes[current]["supersedes"]
        if previous is None or str(previous).strip() == "":
            break
        current = str(previous)

    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    while current in notes and current not in seen:
        seen.add(current)
        row = notes[current]
        chain.append(
            {
                "id": str(row["id"]),
                "title": str(row["title"] or row["id"]),
                "type": str(row["type"] or "note"),
                "valid_from": None if row["valid_from"] in {None, ""} else str(row["valid_from"]),
                "valid_to": None if row["valid_to"] in {None, ""} else str(row["valid_to"]),
                "supersedes": None if row["supersedes"] in {None, ""} else str(row["supersedes"]),
                "superseded_by": None
                if row["superseded_by"] in {None, ""}
                else str(row["superseded_by"]),
                "is_current": bool(row["is_current"]),
            }
        )
        next_id = row["superseded_by"]
        if next_id is None or str(next_id).strip() == "":
            break
        current = str(next_id)
    return chain


def find_conflicts(atlas_root: Path | str) -> list[dict[str, Any]]:
    with _connection(atlas_root) as connection:
        notes = connection.execute(
            """
            SELECT id, title, type, status, is_current
            FROM notes
            WHERE COALESCE(is_current, 1) = 1
            ORDER BY title ASC, id ASC
            """
        ).fetchall()
        wires = connection.execute(
            """
            SELECT source_note, target_note, emotional_valence
            FROM wires
            WHERE emotional_valence IS NOT NULL
            """
        ).fetchall()
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in notes:
        title = str(row["title"] or row["id"]).strip().lower()
        if not title:
            continue
        grouped.setdefault(title, []).append(row)

    conflicts: list[dict[str, Any]] = []
    wire_map: dict[tuple[str, str], set[str]] = {}
    for row in wires:
        value = str(row["emotional_valence"]).strip().lower()
        wire_map.setdefault((str(row["source_note"]), str(row["target_note"])), set()).add(value)

    for title, rows in grouped.items():
        if len(rows) < 2:
            continue
        statuses = {
            str(row["status"]).strip().lower()
            for row in rows
            if row["status"] is not None and str(row["status"]).strip()
        }
        note_ids = [str(row["id"]) for row in rows]
        if len(statuses) > 1:
            conflicts.append(
                {
                    "group": title,
                    "type": "status_conflict",
                    "notes": note_ids,
                    "statuses": sorted(statuses),
                }
            )
        targets: dict[str, set[str]] = {}
        for note_id in note_ids:
            for (source_note, target_note), valences in wire_map.items():
                if source_note != note_id:
                    continue
                targets.setdefault(target_note, set()).update(valences)
        for target_note, valences in targets.items():
            lowered = {item.lower() for item in valences}
            if lowered & POSITIVE_VALENCE and lowered & NEGATIVE_VALENCE:
                conflicts.append(
                    {
                        "group": title,
                        "type": "wire_valence_conflict",
                        "notes": note_ids,
                        "target_note": target_note,
                        "valences": sorted(lowered),
                    }
                )
    return conflicts


def find_stale_notes(
    atlas_root: Path | str,
    *,
    threshold_days: int | None = None,
) -> list[dict[str, Any]]:
    config = _temporal_config(atlas_root)
    if threshold_days is None:
        try:
            threshold_days = int(config.get("stale_threshold_days", 60))
        except (TypeError, ValueError):
            threshold_days = 60
    cutoff = time.time() - (threshold_days * 86400.0)
    with _connection(atlas_root) as connection:
        rows = connection.execute(
            """
            SELECT id, path, title, type, modified
            FROM notes
            WHERE COALESCE(is_current, 1) = 1 AND modified < ?
            ORDER BY modified ASC
            """,
            (cutoff,),
        ).fetchall()
    return [
        {
            "id": str(row["id"]),
            "path": str(row["path"]),
            "title": str(row["title"] or row["id"]),
            "type": str(row["type"] or "note"),
            "modified": float(row["modified"]),
        }
        for row in rows
    ]
