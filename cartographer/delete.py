from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .atlas import Atlas
from .index import Index
from .notes import Note
from .operating_truth import remove_operating_truth_for_note


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


def _resolve_note(atlas_root: Path | str, note_id: str) -> tuple[str, Path]:
    index = Index(Path(atlas_root).expanduser())
    canonical = index.canonicalize_note_ref(note_id) or note_id
    path = index.find_note_path(canonical)
    if path is None:
        raise ValueError(f"note not found: {note_id}")
    return canonical, path


def delete_impact(atlas_root: Path | str, note_id: str) -> dict[str, Any]:
    canonical, path = _resolve_note(atlas_root, note_id)
    with _connection(atlas_root) as connection:
        incoming_wires = connection.execute(
            "SELECT COUNT(*) AS count FROM wires WHERE target_note = ?",
            (canonical,),
        ).fetchone()
        outgoing_wires = connection.execute(
            "SELECT COUNT(*) AS count FROM wires WHERE source_note = ?",
            (canonical,),
        ).fetchone()
        block_refs = connection.execute(
            "SELECT COUNT(*) AS count FROM block_refs WHERE to_note = ?",
            (canonical,),
        ).fetchone()
        frontmatter_links = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM notes
            WHERE id != ? AND links LIKE ?
            """,
            (canonical, f'%"{canonical}"%'),
        ).fetchone()
        embeddings = connection.execute(
            "SELECT COUNT(*) AS count FROM embeddings WHERE note_id = ?",
            (canonical,),
        ).fetchone()
        operating_truth_refs = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM operating_truth
            WHERE content LIKE ? OR COALESCE(metadata_json, '') LIKE ?
            """,
            (f"%{canonical}%", f"%{canonical}%"),
        ).fetchone()
    return {
        "note_id": canonical,
        "path": str(path),
        "incoming_wires": int(incoming_wires["count"]),
        "outgoing_wires": int(outgoing_wires["count"]),
        "block_refs": int(block_refs["count"]),
        "frontmatter_links": int(frontmatter_links["count"]),
        "embeddings": int(embeddings["count"]),
        "operating_truth_refs": int(operating_truth_refs["count"]),
    }


def _cleanup_frontmatter_links(atlas_root: Path, note_id: str) -> int:
    index = Index(atlas_root)
    cleaned = 0
    with _connection(atlas_root) as connection:
        rows = connection.execute(
            """
            SELECT path
            FROM notes
            WHERE id != ? AND links LIKE ?
            """,
            (note_id, f'%"{note_id}"%'),
        ).fetchall()
    for row in rows:
        path = Path(str(row["path"]))
        note = Note.from_file(path)
        links = note.frontmatter.get("links") or []
        if not isinstance(links, list):
            continue
        filtered = [item for item in links if str(item) != note_id]
        if len(filtered) == len(links):
            continue
        note.frontmatter["links"] = filtered
        note.frontmatter["modified"] = datetime.now().date().isoformat()
        note.write(ensure_blocks=True)
        cleaned += 1
    index.rebuild()
    return cleaned


def delete_note(
    atlas_root: Path | str,
    note_id: str,
    *,
    cascade: bool = True,
    archive: bool = False,
) -> dict[str, Any]:
    atlas_root = Path(atlas_root).expanduser()
    canonical, path = _resolve_note(atlas_root, note_id)
    impact = delete_impact(atlas_root, canonical)
    archive_path: str | None = None
    if archive:
        archive_dir = atlas_root / ".cartographer" / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        destination = archive_dir / path.name
        if destination.exists():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            destination = archive_dir / f"{path.stem}-{stamp}{path.suffix}"
        shutil.move(str(path), str(destination))
        archive_path = str(destination)
    else:
        path.unlink()

    cleaned_links = 0
    if cascade:
        cleaned_links = _cleanup_frontmatter_links(atlas_root, canonical)

    removed_operating_truth = remove_operating_truth_for_note(atlas_root, canonical)
    with _connection(atlas_root) as connection:
        connection.execute("DELETE FROM notes WHERE id = ?", (canonical,))
        connection.execute("DELETE FROM blocks WHERE note_id = ?", (canonical,))
        connection.execute(
            "DELETE FROM block_refs WHERE from_note = ? OR to_note = ?",
            (canonical, canonical),
        )
        connection.execute(
            "DELETE FROM wires WHERE source_note = ? OR target_note = ?",
            (canonical, canonical),
        )
        connection.execute("DELETE FROM embeddings WHERE note_id = ?", (canonical,))
        try:
            connection.execute("DELETE FROM notes_fts WHERE id = ?", (canonical,))
        except sqlite3.OperationalError:
            pass
        connection.execute("DELETE FROM guardrail_violations WHERE note_id = ?", (canonical,))
        connection.commit()
    Atlas(atlas_root).refresh_index()
    return {
        "deleted": canonical,
        "path": str(path),
        "archived": archive,
        "archive_path": archive_path,
        "cascade": cascade,
        "cleaned_links": cleaned_links,
        "removed_operating_truth": removed_operating_truth,
        "impact": impact,
    }
