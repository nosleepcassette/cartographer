from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .config import load_config
from .index import Index


VALID_OPERATING_TYPES = {
    "active_work",
    "open_decision",
    "current_commitment",
    "next_step",
    "external_owner",
}

TYPE_ALIASES = {
    "commitment": "current_commitment",
    "current_commitment": "current_commitment",
}

DISPLAY_LABELS = {
    "active_work": "active",
    "open_decision": "open decisions",
    "current_commitment": "commitments",
    "next_step": "next steps",
    "external_owner": "external",
}


def _db_path(atlas_root: Path | str) -> Path:
    return Path(atlas_root).expanduser() / ".cartographer" / "index.db"


def _normalize_type(entry_type: str) -> str:
    normalized = TYPE_ALIASES.get(entry_type.strip(), entry_type.strip())
    if normalized not in VALID_OPERATING_TYPES:
        raise ValueError(f"unsupported operating truth type: {entry_type}")
    return normalized


def _config(atlas_root: Path | str) -> dict[str, Any]:
    config = load_config(root=atlas_root)
    raw = config.get("operating_truth", {}) if isinstance(config, dict) else {}
    return raw if isinstance(raw, dict) else {}


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


def _encode_metadata(metadata: dict[str, Any] | None) -> str:
    return json.dumps(metadata or {}, sort_keys=True, ensure_ascii=True)


def _decode_metadata(raw: Any) -> dict[str, Any]:
    if raw in {None, ""}:
        return {}
    try:
        decoded = json.loads(str(raw))
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _entry_id(entry_type: str, content: str) -> str:
    key = f"{entry_type}|{content}|{time.time()}"
    return "ot-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _row_payload(row: sqlite3.Row) -> dict[str, Any]:
    metadata = _decode_metadata(row["metadata_json"])
    return {
        "id": str(row["id"]),
        "type": str(row["type"]),
        "content": str(row["content"]),
        "priority": int(row["priority"]),
        "source": None if row["source"] is None else str(row["source"]),
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
        "expires_at": None if row["expires_at"] is None else float(row["expires_at"]),
        "metadata": metadata,
        "status": str(metadata.get("status") or "active"),
    }


def list_operating_truth(
    atlas_root: Path | str,
    *,
    entry_type: str | None = None,
    include_history: bool = False,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if entry_type is not None:
        clauses.append("type = ?")
        params.append(_normalize_type(entry_type))
    statement = "SELECT * FROM operating_truth"
    if clauses:
        statement += " WHERE " + " AND ".join(clauses)
    statement += " ORDER BY priority DESC, updated_at DESC"
    with _connection(atlas_root) as connection:
        rows = connection.execute(statement, params).fetchall()
    payload = [_row_payload(row) for row in rows]
    if include_history:
        return payload
    return [item for item in payload if item["status"] == "active"]


def _dedupe_existing(
    connection: sqlite3.Connection,
    *,
    entry_type: str,
    content: str,
    source: str | None,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT *
        FROM operating_truth
        WHERE type = ? AND content = ? AND COALESCE(source, '') = COALESCE(?, '')
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (entry_type, content, source),
    ).fetchone()


def _archive_active_work(
    connection: sqlite3.Connection,
    *,
    source: str | None = None,
) -> None:
    rows = connection.execute(
        """
        SELECT id, metadata_json
        FROM operating_truth
        WHERE type = 'active_work'
        """
    ).fetchall()
    now = time.time()
    for row in rows:
        metadata = _decode_metadata(row["metadata_json"])
        if str(metadata.get("status") or "active") != "active":
            continue
        metadata["status"] = "archived"
        if source:
            metadata["replaced_by_source"] = source
        connection.execute(
            """
            UPDATE operating_truth
            SET updated_at = ?, expires_at = ?, metadata_json = ?
            WHERE id = ?
            """,
            (now, now, _encode_metadata(metadata), str(row["id"])),
        )


def _upsert_entry(
    connection: sqlite3.Connection,
    *,
    entry_id: str,
    entry_type: str,
    content: str,
    priority: int,
    source: str | None,
    created_at: float,
    updated_at: float,
    expires_at: float | None,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    connection.execute(
        """
        INSERT OR REPLACE INTO operating_truth
        (id, type, content, priority, source, created_at, updated_at, expires_at, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry_id,
            entry_type,
            content,
            priority,
            source,
            created_at,
            updated_at,
            expires_at,
            _encode_metadata(metadata),
        ),
    )
    row = connection.execute(
        "SELECT * FROM operating_truth WHERE id = ? LIMIT 1",
        (entry_id,),
    ).fetchone()
    assert row is not None
    return _row_payload(row)


def add_operating_truth(
    atlas_root: Path | str,
    entry_type: str,
    content: str,
    *,
    priority: int = 1,
    source: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_type = _normalize_type(entry_type)
    now = time.time()
    metadata = dict(metadata or {})
    metadata.setdefault("status", "active")
    with _connection(atlas_root) as connection:
        existing = _dedupe_existing(
            connection,
            entry_type=normalized_type,
            content=content,
            source=source,
        )
        if normalized_type == "active_work":
            _archive_active_work(connection, source=source)
        if existing is not None:
            previous_metadata = _decode_metadata(existing["metadata_json"])
            previous_metadata.update(metadata)
            payload = _upsert_entry(
                connection,
                entry_id=str(existing["id"]),
                entry_type=normalized_type,
                content=content,
                priority=priority,
                source=source,
                created_at=float(existing["created_at"]),
                updated_at=now,
                expires_at=None,
                metadata=previous_metadata,
            )
        else:
            payload = _upsert_entry(
                connection,
                entry_id=_entry_id(normalized_type, content),
                entry_type=normalized_type,
                content=content,
                priority=priority,
                source=source,
                created_at=now,
                updated_at=now,
                expires_at=None,
                metadata=metadata,
            )
        connection.commit()
    return payload


def set_operating_truth(
    atlas_root: Path | str,
    entry_type: str,
    content: str,
    *,
    priority: int = 1,
    source: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_type = _normalize_type(entry_type)
    if normalized_type != "active_work":
        raise ValueError("set is currently only supported for active_work")
    return add_operating_truth(
        atlas_root,
        normalized_type,
        content,
        priority=priority,
        source=source,
        metadata=metadata,
    )


def mark_operating_truth_status(
    atlas_root: Path | str,
    entry_id: str,
    *,
    status: str,
) -> dict[str, Any]:
    if status not in {"completed", "expired", "archived"}:
        raise ValueError(f"unsupported operating truth status: {status}")
    now = time.time()
    with _connection(atlas_root) as connection:
        row = connection.execute(
            "SELECT * FROM operating_truth WHERE id = ? LIMIT 1",
            (entry_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"operating truth entry not found: {entry_id}")
        metadata = _decode_metadata(row["metadata_json"])
        metadata["status"] = status
        payload = _upsert_entry(
            connection,
            entry_id=str(row["id"]),
            entry_type=str(row["type"]),
            content=str(row["content"]),
            priority=int(row["priority"]),
            source=None if row["source"] is None else str(row["source"]),
            created_at=float(row["created_at"]),
            updated_at=now,
            expires_at=now,
            metadata=metadata,
        )
        connection.commit()
    return payload


def operating_truth_history(atlas_root: Path | str) -> list[dict[str, Any]]:
    max_days = _config(atlas_root).get("max_history_days", 90)
    try:
        cutoff = time.time() - (float(max_days) * 86400.0)
    except (TypeError, ValueError):
        cutoff = 0.0
    items = list_operating_truth(atlas_root, include_history=True)
    return [
        item
        for item in items
        if item["status"] != "active" and (item["updated_at"] >= cutoff or cutoff <= 0)
    ]


def _format_group(items: list[dict[str, Any]]) -> str:
    return ", ".join(item["content"] for item in items) if items else "none"


def operating_truth_brief_section(atlas_root: Path | str) -> list[str]:
    items = list_operating_truth(atlas_root)
    grouped: dict[str, list[dict[str, Any]]] = {key: [] for key in VALID_OPERATING_TYPES}
    for item in items:
        grouped[item["type"]].append(item)
    return [
        "## operating truth",
        f"active: {_format_group(grouped['active_work'])}",
        f"open decisions: {_format_group(grouped['open_decision'])}",
        f"commitments: {_format_group(grouped['current_commitment'])}",
        f"next steps: {_format_group(grouped['next_step'])}",
        f"external: {_format_group(grouped['external_owner'])}",
    ]


def remove_operating_truth_for_note(
    atlas_root: Path | str,
    note_id: str,
) -> int:
    pattern = f"%{note_id}%"
    with _connection(atlas_root) as connection:
        rows = connection.execute(
            """
            SELECT id
            FROM operating_truth
            WHERE content LIKE ? OR COALESCE(metadata_json, '') LIKE ?
            """,
            (pattern, pattern),
        ).fetchall()
        for row in rows:
            connection.execute(
                "DELETE FROM operating_truth WHERE id = ?",
                (str(row["id"]),),
            )
        connection.commit()
    return len(rows)
