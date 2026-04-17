from __future__ import annotations

import json
import shlex
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import load_config
from .notes import Note, extract_wikilinks


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
    body TEXT
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

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(id, title, body);
"""


def _slugify_note_id(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-") or "note"


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


class Index:
    def __init__(self, root: Path):
        self.root = root
        self.db_path = root / ".cartographer" / "index.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.fts_enabled = True
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(SCHEMA)
            try:
                connection.executescript(FTS_SCHEMA)
            except sqlite3.OperationalError:
                self.fts_enabled = False

    def _ignored(self, path: Path) -> bool:
        config = load_config(self.root)
        ignore = config.get("ignore", {})
        ignored_dirs = set(ignore.get("dirs", [])) if isinstance(ignore, dict) else set()
        ignored_extensions = (
            set(ignore.get("extensions", [])) if isinstance(ignore, dict) else set()
        )
        return any(part in ignored_dirs for part in path.parts) or path.suffix in ignored_extensions

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
        with self._connection() as connection:
            connection.executescript(
                """
                DELETE FROM notes;
                DELETE FROM blocks;
                DELETE FROM block_refs;
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
                links = [str(link) for link in links if isinstance(link, (str, int, float))]
                modified = path.stat().st_mtime
                word_count = len(note.body.split())

                connection.execute(
                    """
                    INSERT OR REPLACE INTO notes
                    (id, path, title, type, status, tags, links, modified, word_count, body)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    refs.add((target_note, target_block))
                for target_note, target_block in refs:
                    connection.execute(
                        """
                        INSERT INTO block_refs (from_note, from_block, to_note, to_block)
                        VALUES (?, NULL, ?, ?)
                        """,
                        (note_id, target_note, target_block),
                    )
                    ref_count += 1
                note_count += 1

            connection.execute(
                "INSERT INTO meta (key, value) VALUES ('last_rebuild', ?)",
                (str(time.time()),),
            )
        return {"notes": note_count, "blocks": block_count, "refs": ref_count}

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

    def status(self) -> dict[str, Any]:
        with self._connection() as connection:
            note_row = connection.execute("SELECT COUNT(*) AS count FROM notes").fetchone()
            block_row = connection.execute(
                "SELECT COUNT(*) AS count FROM blocks"
            ).fetchone()
        return {
            "notes": 0 if note_row is None else int(note_row["count"]),
            "blocks": 0 if block_row is None else int(block_row["count"]),
            "last_rebuild": self.last_rebuild(),
        }
