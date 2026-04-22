from __future__ import annotations

import json
import random
import shlex
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import load_config
from .notes import Note, extract_wikilinks
from .profiles import profile_payload
from .wires import (
    VALID_AVOIDANCE_RISKS,
    VALID_CURRENT_STATES,
    VALID_EMOTIONAL_VALENCES,
    VALID_ENERGY_IMPACTS,
    VALID_WIRE_CONFIDENCE,
    VALID_WIRE_METHODS,
    VALID_WIRE_PREDICATES,
    parse_wire_comments,
)


MAX_RETRIES = 5
BASE_DELAY = 0.05
MAX_DELAY = 5.0


def _retry_with_backoff(operation: str, func: callable) -> Any:
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            return func()
        except sqlite3.OperationalError as e:
            last_error = e
            if "database is locked" not in str(e).lower():
                raise
            delay = min(BASE_DELAY * (2**attempt) + random.uniform(0, 0.1), MAX_DELAY)
            time.sleep(delay)
        except Exception:
            raise
    raise sqlite3.OperationalError(
        f"database locked after {MAX_RETRIES} retries: {operation}"
    ) from last_error


SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    title TEXT,
    type TEXT,
    status TEXT,
    tags TEXT,
    links TEXT,
    modified REAL,
    word_count INTEGER,
    body TEXT,
    valid_from TEXT,
    valid_to TEXT,
    supersedes TEXT,
    superseded_by TEXT,
    is_current INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS blocks (
    block_id TEXT NOT NULL,
    note_id TEXT NOT NULL,
    content TEXT,
    type TEXT
);

CREATE TABLE IF NOT EXISTS block_refs (
    from_note TEXT NOT NULL,
    from_block TEXT,
    to_note TEXT NOT NULL,
    to_block TEXT
);

CREATE TABLE IF NOT EXISTS wires (
    source_note TEXT NOT NULL,
    source_block TEXT,
    target_note TEXT NOT NULL,
    target_block TEXT,
    predicate TEXT NOT NULL,
    weight REAL,
    bidirectional INTEGER NOT NULL DEFAULT 0,
    relationship TEXT,
    emotional_valence TEXT,
    energy_impact TEXT,
    avoidance_risk TEXT,
    growth_edge INTEGER,
    current_state TEXT,
    since TEXT,
    until TEXT,
    valence_note TEXT,
    author TEXT,
    method TEXT,
    reviewed INTEGER,
    reviewed_by TEXT,
    reviewed_at TEXT,
    review_duration_s REAL,
    confidence TEXT,
    note TEXT,
    path TEXT NOT NULL,
    line INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS wire_issues (
    path TEXT NOT NULL,
    line INTEGER NOT NULL,
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    raw TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS embeddings (
    note_id TEXT NOT NULL,
    embedding BLOB NOT NULL,
    model TEXT NOT NULL DEFAULT 'intfloat/multilingual-e5-large',
    dim INTEGER NOT NULL DEFAULT 1024,
    computed_at REAL NOT NULL,
    PRIMARY KEY (note_id, model)
);

CREATE TABLE IF NOT EXISTS access_log (
    note_id TEXT NOT NULL,
    accessed_at REAL NOT NULL,
    access_type TEXT NOT NULL DEFAULT 'query'
);

CREATE TABLE IF NOT EXISTS dream_log (
    id TEXT PRIMARY KEY,
    phase TEXT NOT NULL,
    started_at REAL NOT NULL,
    completed_at REAL,
    stats_json TEXT
);

CREATE TABLE IF NOT EXISTS operating_truth (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL CHECK(type IN ('active_work', 'open_decision', 'current_commitment', 'next_step', 'external_owner')),
    content TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 1,
    source TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    expires_at REAL,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS guardrail_violations (
    id TEXT PRIMARY KEY,
    note_id TEXT NOT NULL,
    violation_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'warn',
    detected_at REAL NOT NULL,
    resolved INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS pattern_cache (
    id TEXT PRIMARY KEY,
    signal_a TEXT NOT NULL,
    signal_b TEXT NOT NULL,
    lead_hours INTEGER NOT NULL,
    correlation REAL NOT NULL,
    p_value REAL NOT NULL,
    significant INTEGER NOT NULL DEFAULT 0,
    n_buckets INTEGER NOT NULL,
    computed_at REAL NOT NULL,
    description TEXT
);
"""

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(id, title, body);
"""

WIRE_OPTIONAL_COLUMNS = {
    "weight": "REAL",
    "relationship": "TEXT",
    "emotional_valence": "TEXT",
    "energy_impact": "TEXT",
    "avoidance_risk": "TEXT",
    "growth_edge": "INTEGER",
    "current_state": "TEXT",
    "since": "TEXT",
    "until": "TEXT",
    "valence_note": "TEXT",
    "author": "TEXT",
    "method": "TEXT",
    "reviewed": "INTEGER",
    "reviewed_by": "TEXT",
    "reviewed_at": "TEXT",
    "review_duration_s": "REAL",
    "confidence": "TEXT",
    "note": "TEXT",
}

NOTE_OPTIONAL_COLUMNS = {
    "valid_from": "TEXT",
    "valid_to": "TEXT",
    "supersedes": "TEXT",
    "superseded_by": "TEXT",
    "is_current": "INTEGER DEFAULT 1",
}

WIRE_SELECT_COLUMNS = """
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
    path,
    line
"""


def _slugify_note_id(value: str) -> str:
    return (
        "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")
        or "note"
    )


def _canonical_note_id(note: Note, path: Path) -> str:
    note_type = str(note.frontmatter.get("type") or "note")
    agent = note.frontmatter.get("agent")
    if note_type == "master-summary":
        return "master-summary"
    if note_type == "agent-summary" and isinstance(agent, str) and agent.strip():
        return f"{_slugify_note_id(agent)}-summary"
    raw_id = note.frontmatter.get("id")
    if raw_id is not None and str(raw_id).strip():
        return str(raw_id)
    return path.stem


def _alias_variants(root: Path, note_id: str, raw_path: str) -> tuple[str, list[str]]:
    exact = note_id
    weaker: list[str] = []
    if raw_path:
        path = Path(raw_path)
        try:
            relative = path.resolve().relative_to(root.resolve())
        except ValueError:
            relative = path
        weaker.append(relative.with_suffix("").as_posix())
        weaker.append(path.stem)
    deduped: list[str] = []
    seen: set[str] = {exact}
    for alias in weaker:
        normalized = alias.strip().removesuffix(".md").strip("/")
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return exact, deduped


def _normalize_note_ref(value: str) -> str:
    return value.strip().removesuffix(".md").strip("/")


def _row_to_wire_payload(row: sqlite3.Row, *, note_id: str | None = None, block_id: str | None = None) -> dict[str, Any]:
    source_note = str(row["source_note"])
    source_block = None if row["source_block"] is None else str(row["source_block"])
    target_note = str(row["target_note"])
    target_block = None if row["target_block"] is None else str(row["target_block"])
    if note_id is None:
        current_direction = "outgoing"
    else:
        current_direction = (
            "incoming"
            if target_note == note_id and target_block == block_id
            else "outgoing"
        )
    return {
        "direction": current_direction,
        "source_note": source_note,
        "source_block": source_block,
        "target_note": target_note,
        "target_block": target_block,
        "predicate": str(row["predicate"]),
        "weight": None if row["weight"] is None else float(row["weight"]),
        "relationship": None if row["relationship"] is None else str(row["relationship"]),
        "bidirectional": bool(row["bidirectional"]),
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
        "path": str(row["path"]),
        "line": int(row["line"]),
    }


class Index:
    def __init__(self, root: Path):
        self.root = root
        self.db_path = root / ".cartographer" / "index.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.fts_enabled = True
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    @contextmanager
    def _connection(self):
        def get_connection():
            return self._connect()

        connection = _retry_with_backoff("connect", get_connection)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(SCHEMA)
            self._migrate(connection)
            try:
                connection.executescript(FTS_SCHEMA)
            except sqlite3.OperationalError:
                self.fts_enabled = False

    def _migrate(self, connection: sqlite3.Connection) -> None:
        note_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(notes)").fetchall()
        }
        for column_name, column_type in NOTE_OPTIONAL_COLUMNS.items():
            if column_name in note_columns:
                continue
            connection.execute(
                f"ALTER TABLE notes ADD COLUMN {column_name} {column_type}"
            )
        wire_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(wires)").fetchall()
        }
        for column_name, column_type in WIRE_OPTIONAL_COLUMNS.items():
            if column_name in wire_columns:
                continue
            connection.execute(
                f"ALTER TABLE wires ADD COLUMN {column_name} {column_type}"
            )

    def _ignored(self, path: Path) -> bool:
        config = load_config(self.root)
        ignore = config.get("ignore", {})
        ignored_dirs = (
            set(ignore.get("dirs", [])) if isinstance(ignore, dict) else set()
        )
        ignored_extensions = (
            set(ignore.get("extensions", [])) if isinstance(ignore, dict) else set()
        )
        return (
            any(part in ignored_dirs for part in path.parts)
            or path.suffix in ignored_extensions
        )

    def iter_note_paths(self) -> list[Path]:
        note_paths: list[Path] = []
        if not self.root.exists():
            return note_paths
        for path in self.root.rglob("*.md"):
            if self._ignored(path.relative_to(self.root)):
                continue
            note_paths.append(path)
        return sorted(note_paths)

    def rebuild(self) -> dict[str, Any]:
        note_count = 0
        block_count = 0
        ref_count = 0
        wire_count = 0
        wire_issue_count = 0
        parsed_notes: list[dict[str, Any]] = []
        with self._connection() as connection:
            connection.executescript(
                """
                DELETE FROM notes;
                DELETE FROM blocks;
                DELETE FROM block_refs;
                DELETE FROM wires;
                DELETE FROM wire_issues;
                DELETE FROM meta;
                """
            )
            if self.fts_enabled:
                connection.execute("DELETE FROM notes_fts")

            for path in self.iter_note_paths():
                try:
                    note = Note.from_file(path)
                except Exception:
                    continue
                note_id = _canonical_note_id(note, path)
                title = str(note.frontmatter.get("title") or path.stem)
                note_type = str(note.frontmatter.get("type") or "note")
                status = note.frontmatter.get("status")
                tags = note.frontmatter.get("tags") or []
                links = note.frontmatter.get("links") or []
                if not isinstance(tags, list):
                    tags = []
                if not isinstance(links, list):
                    links = []
                links = [
                    str(link) for link in links if isinstance(link, (str, int, float))
                ]
                modified = path.stat().st_mtime
                word_count = len(note.body.split())
                valid_from = note.frontmatter.get("valid_from")
                valid_to = note.frontmatter.get("valid_to")
                supersedes = note.frontmatter.get("supersedes")
                superseded_by = note.frontmatter.get("superseded_by")
                raw_is_current = note.frontmatter.get("is_current", True)
                is_current = 0 if raw_is_current in {False, "false", "False", 0, "0"} else 1
                parsed_notes.append(
                    {
                        "path": path,
                        "note": note,
                        "note_id": note_id,
                        "title": title,
                        "note_type": note_type,
                        "status": None if status is None else str(status),
                        "tags": tags,
                        "links": links,
                        "modified": modified,
                        "word_count": word_count,
                        "valid_from": None if valid_from in {None, ""} else str(valid_from),
                        "valid_to": None if valid_to in {None, ""} else str(valid_to),
                        "supersedes": None if supersedes in {None, ""} else str(supersedes),
                        "superseded_by": None
                        if superseded_by in {None, ""}
                        else str(superseded_by),
                        "is_current": is_current,
                    }
                )

            aliases: dict[str, str] = {}
            for item in parsed_notes:
                note_id = str(item["note_id"])
                exact, weaker = _alias_variants(self.root, note_id, str(item["path"]))
                aliases[exact] = note_id
                for alias in weaker:
                    aliases.setdefault(alias, note_id)

            for item in parsed_notes:
                path = Path(item["path"])
                note = item["note"]
                note_id = str(item["note_id"])
                title = str(item["title"])
                note_type = str(item["note_type"])
                status = item["status"]
                tags = item["tags"]
                links = [
                    aliases.get(str(link).strip().removesuffix(".md").strip("/"), str(link))
                    for link in item["links"]
                ]
                modified = float(item["modified"])
                word_count = int(item["word_count"])
                valid_from = item["valid_from"]
                valid_to = item["valid_to"]
                supersedes = item["supersedes"]
                superseded_by = item["superseded_by"]
                is_current = int(item["is_current"])

                connection.execute(
                    """
                    INSERT OR REPLACE INTO notes
                    (
                        id,
                        path,
                        title,
                        type,
                        status,
                        tags,
                        links,
                        modified,
                        word_count,
                        body,
                        valid_from,
                        valid_to,
                        supersedes,
                        superseded_by,
                        is_current
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        note_id,
                        str(path),
                        title,
                        note_type,
                        None if status is None else str(status),
                        json.dumps(tags),
                        json.dumps(links),
                        modified,
                        word_count,
                        note.body,
                        valid_from,
                        valid_to,
                        supersedes,
                        superseded_by,
                        is_current,
                    ),
                )
                if self.fts_enabled:
                    connection.execute(
                        "INSERT INTO notes_fts (id, title, body) VALUES (?, ?, ?)",
                        (note_id, title, note.body),
                    )

                for block in note.blocks:
                    connection.execute(
                        """
                        INSERT INTO blocks (block_id, note_id, content, type)
                        VALUES (?, ?, ?, ?)
                        """,
                        (block.id, note_id, block.content, block.type),
                    )
                    block_count += 1

                refs: set[tuple[str, str | None]] = set()
                for link in links:
                    refs.add((link, None))
                for target_note, target_block in extract_wikilinks(note.body):
                    normalized_target = aliases.get(
                        target_note.strip().removesuffix(".md").strip("/"),
                        target_note,
                    )
                    refs.add((normalized_target, target_block))
                for target_note, target_block in refs:
                    connection.execute(
                        """
                        INSERT INTO block_refs (from_note, from_block, to_note, to_block)
                        VALUES (?, NULL, ?, ?)
                        """,
                        (note_id, target_note, target_block),
                    )
                    ref_count += 1

                wires, wire_issues = parse_wire_comments(
                    note.body,
                    note_id=note_id,
                    path=path,
                )
                for wire in wires:
                    normalized_target = aliases.get(
                        wire.target_note.strip().removesuffix(".md").strip("/"),
                        wire.target_note,
                    )
                    connection.execute(
                        """
                        INSERT INTO wires
                        (
                            source_note,
                            source_block,
                            target_note,
                            target_block,
                            predicate,
                            weight,
                            bidirectional,
                            relationship,
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
                            path,
                            line
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            wire.source_note,
                            wire.source_block,
                            normalized_target,
                            wire.target_block,
                            wire.predicate,
                            wire.weight,
                            1 if wire.bidirectional else 0,
                            wire.relationship,
                            wire.emotional_valence,
                            wire.energy_impact,
                            wire.avoidance_risk,
                            None if wire.growth_edge is None else (1 if wire.growth_edge else 0),
                            wire.current_state,
                            wire.since,
                            wire.until,
                            wire.valence_note,
                            wire.author,
                            wire.method,
                            None if wire.reviewed is None else (1 if wire.reviewed else 0),
                            wire.reviewed_by,
                            wire.reviewed_at,
                            wire.review_duration_s,
                            wire.confidence,
                            wire.note,
                            wire.path,
                            wire.line,
                        ),
                    )
                    wire_count += 1
                for issue in wire_issues:
                    connection.execute(
                        """
                        INSERT INTO wire_issues (path, line, code, message, raw)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (issue.path, issue.line, issue.code, issue.message, issue.raw),
                    )
                    wire_issue_count += 1
                note_count += 1

            connection.execute(
                "INSERT INTO meta (key, value) VALUES ('last_rebuild', ?)",
                (str(time.time()),),
            )
        return {
            "notes": note_count,
            "blocks": block_count,
            "refs": ref_count,
            "wires": wire_count,
            "wire_issues": wire_issue_count,
        }

    def update(self, _note: Note) -> dict[str, Any]:
        return self.rebuild()

    def last_rebuild(self) -> float | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM meta WHERE key = 'last_rebuild'"
            ).fetchone()
        if row is None:
            return None
        return float(row["value"])

    def needs_rebuild(self) -> bool:
        last_rebuild = self.last_rebuild()
        if last_rebuild is None:
            return True
        for path in self.iter_note_paths():
            if path.stat().st_mtime > last_rebuild:
                return True
        return False

    def query(self, expression: str) -> list[str]:
        tokens = shlex.split(expression) if expression else []
        sql = ["SELECT DISTINCT n.path FROM notes n"]
        clauses: list[str] = []
        params: list[Any] = []
        fts_terms: list[str] = []
        block_ref: tuple[str, str | None] | None = None

        for token in tokens:
            if token.startswith("tag:"):
                clauses.append("n.tags LIKE ?")
                params.append(f'%"{token.partition(":")[2]}"%')
            elif token.startswith("status:"):
                clauses.append("n.status = ?")
                params.append(token.partition(":")[2])
            elif token.startswith("type:"):
                clauses.append("n.type = ?")
                params.append(token.partition(":")[2])
            elif token.startswith("links:"):
                clauses.append("n.links LIKE ?")
                params.append(f'%"{token.partition(":")[2]}"%')
            elif token.startswith("modified:>"):
                date_value = token.partition(">")[2]
                try:
                    epoch = datetime.fromisoformat(date_value).timestamp()
                except ValueError:
                    continue
                clauses.append("n.modified > ?")
                params.append(epoch)
            elif token.startswith("text:"):
                fts_terms.append(token.partition(":")[2])
            elif token.startswith("block-ref:"):
                target = token.partition(":")[2]
                if "#" in target:
                    block_ref = tuple(target.split("#", 1))  # type: ignore[assignment]
                else:
                    block_ref = (target, None)
            else:
                fts_terms.append(token)

        if block_ref is not None:
            sql.append("JOIN block_refs br ON br.from_note = n.id")
            clauses.append("br.to_note = ?")
            params.append(block_ref[0])
            if block_ref[1] is not None:
                clauses.append("br.to_block = ?")
                params.append(block_ref[1])

        if fts_terms:
            if self.fts_enabled:
                sql.append("JOIN notes_fts f ON f.id = n.id")
                clauses.append("notes_fts MATCH ?")
                params.append(" AND ".join(fts_terms))
            else:
                for term in fts_terms:
                    clauses.append("(n.title LIKE ? OR n.body LIKE ?)")
                    params.extend([f"%{term}%", f"%{term}%"])

        statement = " ".join(sql)
        if clauses:
            statement += " WHERE " + " AND ".join(clauses)
        statement += " ORDER BY n.path ASC"

        with self._connection() as connection:
            rows = connection.execute(statement, params).fetchall()
        return [str(row["path"]) for row in rows]

    def record_accesses(
        self,
        note_ids: list[str] | tuple[str, ...],
        *,
        access_type: str = "query",
        timestamp: float | None = None,
    ) -> None:
        ids = [str(note_id).strip() for note_id in note_ids if str(note_id).strip()]
        if not ids:
            return
        when = time.time() if timestamp is None else float(timestamp)
        with self._connection() as connection:
            connection.executemany(
                """
                INSERT INTO access_log (note_id, accessed_at, access_type)
                VALUES (?, ?, ?)
                """,
                [(note_id, when, access_type) for note_id in ids],
            )

    def backlinks(self, note_id: str) -> list[str]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT n.path
                FROM notes n
                JOIN block_refs br ON br.from_note = n.id
                WHERE br.to_note = ?
                ORDER BY n.path ASC
                """,
                (note_id,),
            ).fetchall()
        return [str(row["path"]) for row in rows]

    def block_backlinks(self, note_id: str, block_id: str) -> list[str]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT n.path
                FROM notes n
                JOIN block_refs br ON br.from_note = n.id
                WHERE br.to_note = ? AND br.to_block = ?
                ORDER BY n.path ASC
                """,
                (note_id, block_id),
            ).fetchall()
        return [str(row["path"]) for row in rows]

    def find_note_path(self, note_id: str) -> Path | None:
        canonical_note_id = self.canonicalize_note_ref(note_id)
        if canonical_note_id is not None:
            note_id = canonical_note_id
        with self._connection() as connection:
            row = connection.execute(
                "SELECT path FROM notes WHERE id = ? LIMIT 1",
                (note_id,),
            ).fetchone()
        if row is not None:
            return Path(str(row["path"]))
        for path in self.iter_note_paths():
            if path.stem == note_id:
                return path
        return None

    def canonicalize_note_ref(self, note_ref: str) -> str | None:
        clean_ref = _normalize_note_ref(note_ref)
        if not clean_ref:
            return None
        with self._connection() as connection:
            rows = connection.execute("SELECT id, path FROM notes").fetchall()
        aliases: dict[str, str] = {}
        for row in rows:
            note_id = str(row["id"])
            exact, weaker = _alias_variants(self.root, note_id, str(row["path"]))
            aliases[exact] = note_id
            for alias in weaker:
                aliases.setdefault(alias, note_id)
        return aliases.get(clean_ref)

    def block_exists(self, note_id: str, block_id: str) -> bool:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM blocks
                WHERE note_id = ? AND block_id = ?
                LIMIT 1
                """,
                (note_id, block_id),
            ).fetchone()
        return row is not None

    def list_wires(
        self,
        *,
        note_id: str,
        block_id: str | None = None,
        direction: str = "both",
        predicate: str | None = None,
    ) -> list[dict[str, Any]]:
        if direction not in {"incoming", "outgoing", "both"}:
            raise ValueError(f"unsupported wire direction: {direction}")
        clauses: list[str] = []
        params: list[Any] = []
        if direction in {"outgoing", "both"}:
            clauses.append(
                "(source_note = ? AND (? IS NULL OR source_block = ?))"
            )
            params.extend([note_id, block_id, block_id])
        if direction in {"incoming", "both"}:
            clauses.append(
                "(target_note = ? AND (? IS NULL OR target_block = ?))"
            )
            params.extend([note_id, block_id, block_id])
        if not clauses:
            return []
        statement = (
            """
            SELECT
            """
            + WIRE_SELECT_COLUMNS
            + """
            FROM wires
            WHERE (
            """
            + " OR ".join(clauses)
            + ")"
        )
        if predicate is not None:
            statement += " AND predicate = ?"
            params.append(predicate)
        statement += " ORDER BY path ASC, line ASC"
        with self._connection() as connection:
            rows = connection.execute(statement, params).fetchall()

        return [
            _row_to_wire_payload(row, note_id=note_id, block_id=block_id)
            for row in rows
        ]

    def query_wires(
        self,
        *,
        note_id: str | None = None,
        predicate: str | None = None,
        relationship: str | None = None,
        emotional_valence: str | None = None,
        energy_impact: str | None = None,
        avoidance_risk: str | None = None,
        growth_edge: bool | None = None,
        current_state: str | None = None,
        method: str | None = None,
        reviewed: bool | None = None,
        pending_review: bool = False,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if note_id is not None:
            clauses.append("(source_note = ? OR target_note = ?)")
            params.extend([note_id, note_id])
        if predicate is not None:
            clauses.append("predicate = ?")
            params.append(predicate)
        if relationship is not None:
            clauses.append("(relationship = ? OR predicate = ?)")
            params.extend([relationship, relationship])
        if emotional_valence is not None:
            clauses.append("emotional_valence = ?")
            params.append(emotional_valence)
        if energy_impact is not None:
            clauses.append("energy_impact = ?")
            params.append(energy_impact)
        if avoidance_risk is not None:
            clauses.append("avoidance_risk = ?")
            params.append(avoidance_risk)
        if growth_edge is not None:
            clauses.append("growth_edge = ?")
            params.append(1 if growth_edge else 0)
        if current_state is not None:
            clauses.append("current_state = ?")
            params.append(current_state)
        if method is not None:
            clauses.append("method = ?")
            params.append(method)
        if reviewed is not None:
            clauses.append("reviewed = ?")
            params.append(1 if reviewed else 0)
        if pending_review:
            clauses.append(
                "((method IN ('agent', 'interactive') AND (reviewed IS NULL OR reviewed = 0)) OR (reviewed = 0))"
            )

        statement = """
            SELECT
        """ + WIRE_SELECT_COLUMNS + """
            FROM wires
        """
        if clauses:
            statement += " WHERE " + " AND ".join(clauses)
        statement += " ORDER BY path ASC, line ASC"

        with self._connection() as connection:
            rows = connection.execute(statement, params).fetchall()
        return [_row_to_wire_payload(row) for row in rows]

    def wire_doctor(self) -> dict[str, Any]:
        issues: list[dict[str, Any]] = []
        profile = profile_payload(self.root, config=load_config(self.root))
        valid_predicates = set(profile.get("default_predicates") or VALID_WIRE_PREDICATES)
        metadata_fields = set(profile.get("metadata_fields") or [])
        with self._connection() as connection:
            malformed_rows = connection.execute(
                """
                SELECT path, line, code, message, raw
                FROM wire_issues
                ORDER BY path ASC, line ASC
                """
            ).fetchall()
            wire_rows = connection.execute(
                """
                SELECT
                """
                + WIRE_SELECT_COLUMNS
                + """
                FROM wires
                ORDER BY path ASC, line ASC
                """
            ).fetchall()

        valid_valences = set(VALID_EMOTIONAL_VALENCES)
        valid_impacts = set(VALID_ENERGY_IMPACTS)
        valid_risks = set(VALID_AVOIDANCE_RISKS)
        valid_states = set(VALID_CURRENT_STATES)
        for row in malformed_rows:
            issues.append(
                {
                    "path": str(row["path"]),
                    "line": int(row["line"]),
                    "code": str(row["code"]),
                    "message": str(row["message"]),
                    "raw": str(row["raw"]),
                }
            )

        for row in wire_rows:
            source_note = str(row["source_note"])
            target_note = str(row["target_note"])
            target_block = None if row["target_block"] is None else str(row["target_block"])
            predicate = str(row["predicate"])
            path = str(row["path"])
            line = int(row["line"])
            weight = None if row["weight"] is None else float(row["weight"])
            emotional_valence = None if row["emotional_valence"] is None else str(row["emotional_valence"])
            energy_impact = None if row["energy_impact"] is None else str(row["energy_impact"])
            avoidance_risk = None if row["avoidance_risk"] is None else str(row["avoidance_risk"])
            current_state = None if row["current_state"] is None else str(row["current_state"])
            method = None if row["method"] is None else str(row["method"])
            confidence = None if row["confidence"] is None else str(row["confidence"])
            if predicate not in valid_predicates:
                issues.append(
                    {
                        "path": path,
                        "line": line,
                        "code": "invalid_predicate",
                        "message": f"invalid wire predicate: {predicate}",
                        "raw": "",
                        "source_note": source_note,
                        "source_block": None if row["source_block"] is None else str(row["source_block"]),
                        "target_note": target_note,
                        "target_block": target_block,
                        "predicate": predicate,
                    }
                )
                continue
            if weight is not None and not 0.0 <= weight <= 1.0:
                issues.append(
                    {
                        "path": path,
                        "line": line,
                        "code": "invalid_weight",
                        "message": f"wire weight must be between 0.0 and 1.0: {weight}",
                        "raw": "",
                    }
                )
            if emotional_valence is not None and emotional_valence not in valid_valences:
                issues.append(
                    {
                        "path": path,
                        "line": line,
                        "code": "invalid_emotional_valence",
                        "message": f"invalid emotional valence: {emotional_valence}",
                        "raw": "",
                    }
                )
            if energy_impact is not None and energy_impact not in valid_impacts:
                issues.append(
                    {
                        "path": path,
                        "line": line,
                        "code": "invalid_energy_impact",
                        "message": f"invalid energy impact: {energy_impact}",
                        "raw": "",
                    }
                )
            if avoidance_risk is not None and avoidance_risk not in valid_risks:
                issues.append(
                    {
                        "path": path,
                        "line": line,
                        "code": "invalid_avoidance_risk",
                        "message": f"invalid avoidance risk: {avoidance_risk}",
                        "raw": "",
                    }
                )
            if current_state is not None and current_state not in valid_states:
                issues.append(
                    {
                        "path": path,
                        "line": line,
                        "code": "invalid_current_state",
                        "message": f"invalid current state: {current_state}",
                        "raw": "",
                    }
                )
            if method is not None and method not in VALID_WIRE_METHODS:
                issues.append(
                    {
                        "path": path,
                        "line": line,
                        "code": "invalid_method",
                        "message": f"invalid wire method: {method}",
                        "raw": "",
                    }
                )
            if confidence is not None and confidence not in VALID_WIRE_CONFIDENCE:
                issues.append(
                    {
                        "path": path,
                        "line": line,
                        "code": "invalid_confidence",
                        "message": f"invalid wire confidence: {confidence}",
                        "raw": "",
                    }
                )
            for field_name in (
                "emotional_valence",
                "energy_impact",
                "avoidance_risk",
                "growth_edge",
                "current_state",
                "since",
                "until",
                "valence_note",
                "author",
                "method",
                "reviewed",
                "reviewed_by",
                "reviewed_at",
                "review_duration_s",
                "confidence",
                "note",
            ):
                if row[field_name] is None:
                    continue
                if field_name in metadata_fields or field_name == "weight" or field_name == "relationship":
                    continue
                issues.append(
                    {
                        "path": path,
                        "line": line,
                        "code": "unsupported_metadata_field",
                        "message": f"{field_name} is not enabled by the active wire profile",
                        "raw": "",
                    }
                )
            target_exists = self.find_note_path(target_note) is not None
            if not target_exists:
                issues.append(
                    {
                        "path": path,
                        "line": line,
                        "code": "orphan_target_note",
                        "message": f"wire target note does not exist: {target_note}",
                        "raw": "",
                        "source_note": source_note,
                        "source_block": None if row["source_block"] is None else str(row["source_block"]),
                        "target_note": target_note,
                        "target_block": target_block,
                        "predicate": predicate,
                    }
                )
                continue
            if target_block is not None and not self.block_exists(target_note, target_block):
                issues.append(
                    {
                        "path": path,
                        "line": line,
                        "code": "orphan_target_block",
                        "message": f"wire target block does not exist: {target_note}#{target_block}",
                        "raw": "",
                        "source_note": source_note,
                        "source_block": None if row["source_block"] is None else str(row["source_block"]),
                        "target_note": target_note,
                        "target_block": target_block,
                        "predicate": predicate,
                    }
                )

        return {
            "valid": not issues,
            "issue_count": len(issues),
            "issues": issues,
        }

    def traverse_wires(
        self,
        *,
        start_note: str,
        depth: int = 2,
        predicate: str | None = None,
    ) -> dict[str, Any]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT
                """
                + WIRE_SELECT_COLUMNS
                + """
                FROM wires
                """
            ).fetchall()
        adjacency: dict[str, list[dict[str, Any]]] = {}
        valid_predicates = set(
            profile_payload(self.root, config=load_config(self.root)).get("default_predicates")
            or VALID_WIRE_PREDICATES
        )
        for row in rows:
            predicate_value = str(row["predicate"])
            if predicate_value not in valid_predicates:
                continue
            if predicate is not None and predicate_value != predicate:
                continue
            source = str(row["source_note"])
            target = str(row["target_note"])
            edge = {
                "source_note": source,
                "source_block": None if row["source_block"] is None else str(row["source_block"]),
                "target_note": target,
                "target_block": None if row["target_block"] is None else str(row["target_block"]),
                "predicate": predicate_value,
                "weight": None if row["weight"] is None else float(row["weight"]),
                "relationship": None if row["relationship"] is None else str(row["relationship"]),
                "bidirectional": bool(row["bidirectional"]),
                "emotional_valence": None
                if row["emotional_valence"] is None
                else str(row["emotional_valence"]),
                "energy_impact": None if row["energy_impact"] is None else str(row["energy_impact"]),
                "avoidance_risk": None
                if row["avoidance_risk"] is None
                else str(row["avoidance_risk"]),
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
            }
            adjacency.setdefault(source, []).append(edge)
            if bool(row["bidirectional"]):
                reverse = {
                    **edge,
                    "source_note": target,
                    "source_block": None,
                    "target_note": source,
                    "target_block": None,
                }
                adjacency.setdefault(target, []).append(reverse)

        visited = {start_note}
        frontier = {start_note}
        traversed: list[dict[str, Any]] = []
        for current_depth in range(1, max(depth, 0) + 1):
            next_frontier: set[str] = set()
            for node in sorted(frontier):
                for edge in adjacency.get(node, []):
                    target = str(edge["target_note"])
                    traversed.append({**edge, "depth": current_depth})
                    if target not in visited:
                        visited.add(target)
                        next_frontier.add(target)
            frontier = next_frontier
            if not frontier:
                break
        return {
            "start_note": start_note,
            "depth": depth,
            "predicate": predicate,
            "visited": sorted(visited),
            "edge_count": len(traversed),
            "edges": traversed,
        }

    def status(self) -> dict[str, Any]:
        with self._connection() as connection:
            note_row = connection.execute(
                "SELECT COUNT(*) AS count FROM notes"
            ).fetchone()
            block_row = connection.execute(
                "SELECT COUNT(*) AS count FROM blocks"
            ).fetchone()
            wire_row = connection.execute(
                "SELECT COUNT(*) AS count FROM wires"
            ).fetchone()
            wire_issue_row = connection.execute(
                "SELECT COUNT(*) AS count FROM wire_issues"
            ).fetchone()
        return {
            "notes": 0 if note_row is None else int(note_row["count"]),
            "blocks": 0 if block_row is None else int(block_row["count"]),
            "wires": 0 if wire_row is None else int(wire_row["count"]),
            "wire_issues": 0 if wire_issue_row is None else int(wire_issue_row["count"]),
            "last_rebuild": self.last_rebuild(),
        }
