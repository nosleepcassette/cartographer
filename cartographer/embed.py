from __future__ import annotations

from array import array
import math
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

from .config import load_config
from .index import Index


DEFAULT_EMBED_MODEL = "intfloat/multilingual-e5-large"


def _embedding_config(atlas_root: Path | str) -> dict[str, Any]:
    config = load_config(root=atlas_root)
    raw = config.get("embed", {}) if isinstance(config, dict) else {}
    return raw if isinstance(raw, dict) else {}


def is_fastembed_available() -> bool:
    try:
        from fastembed import TextEmbedding  # noqa: F401
    except Exception:
        return False
    return True


def _vector_to_list(values: Iterable[float]) -> list[float]:
    if hasattr(values, "tolist"):
        converted = values.tolist()
        if isinstance(converted, list):
            return [float(item) for item in converted]
    return [float(item) for item in values]


def _encode_embedding(embedding: Iterable[float]) -> bytes:
    return array("f", _vector_to_list(embedding)).tobytes()


def _decode_embedding(raw: bytes) -> list[float]:
    values = array("f")
    values.frombytes(raw)
    return list(values)


def _vector_similarity(vec_a: Iterable[float], vec_b: Iterable[float]) -> float:
    left = _vector_to_list(vec_a)
    right = _vector_to_list(vec_b)
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


class EmbedBackend:
    """Lazy fastembed wrapper that stays import-safe when the dependency is absent."""

    def __init__(self, model_name: str = DEFAULT_EMBED_MODEL) -> None:
        self.model_name = model_name
        self.model: Any | None = None
        self.dim: int | None = None

    def _lazy_init(self) -> None:
        if self.model is not None:
            return
        from fastembed import TextEmbedding

        self.model = TextEmbedding(self.model_name)

    def embed(self, text: str) -> list[float]:
        self._lazy_init()
        assert self.model is not None
        result = next(iter(self.model.embed([text])))
        vector = _vector_to_list(result)
        self.dim = len(vector)
        return vector

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self._lazy_init()
        assert self.model is not None
        results = [_vector_to_list(item) for item in self.model.embed(texts)]
        if results:
            self.dim = len(results[0])
        return results

    def similarity(self, vec_a: Iterable[float], vec_b: Iterable[float]) -> float:
        return _vector_similarity(vec_a, vec_b)


def configured_backend(
    atlas_root: Path | str,
    *,
    model_name: str | None = None,
) -> EmbedBackend:
    settings = _embedding_config(atlas_root)
    selected_model = (
        model_name
        or str(settings.get("model") or DEFAULT_EMBED_MODEL).strip()
        or DEFAULT_EMBED_MODEL
    )
    return EmbedBackend(selected_model)


def _db_path(atlas_root: Path | str) -> Path:
    return Path(atlas_root).expanduser() / ".cartographer" / "index.db"


def store_embedding(
    db_path: Path | str,
    note_id: str,
    embedding: Iterable[float],
    model_name: str,
) -> None:
    encoded = _encode_embedding(embedding)
    dim = len(_vector_to_list(embedding))
    connection = sqlite3.connect(str(Path(db_path).expanduser()))
    try:
        connection.execute(
            """
            INSERT OR REPLACE INTO embeddings (note_id, embedding, model, dim, computed_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (note_id, encoded, model_name, dim, time.time()),
        )
        connection.commit()
    finally:
        connection.close()


def get_embedding(
    db_path: Path | str,
    note_id: str,
    model_name: str | None = None,
) -> list[float] | None:
    connection = sqlite3.connect(str(Path(db_path).expanduser()))
    try:
        query = "SELECT embedding FROM embeddings WHERE note_id = ?"
        params: list[Any] = [note_id]
        if model_name:
            query += " AND model = ?"
            params.append(model_name)
        row = connection.execute(query, params).fetchone()
    finally:
        connection.close()
    if row is None:
        return None
    return _decode_embedding(row[0])


def _note_text(title: str | None, body: str | None) -> str:
    title_text = (title or "").strip()
    body_text = (body or "").strip()
    if title_text and body_text:
        return f"{title_text}\n\n{body_text}"
    return title_text or body_text


def embed_note(
    atlas_root: Path | str,
    note_id: str,
    backend: EmbedBackend | None = None,
) -> bool:
    if not is_fastembed_available():
        return False
    atlas_root = Path(atlas_root).expanduser()
    backend = backend or configured_backend(atlas_root)
    connection = sqlite3.connect(str(_db_path(atlas_root)))
    try:
        row = connection.execute(
            "SELECT title, body FROM notes WHERE id = ?",
            (note_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        return False
    text = _note_text(row[0], row[1])
    if not text.strip():
        return False
    store_embedding(_db_path(atlas_root), note_id, backend.embed(text), backend.model_name)
    return True


def embed_all_notes(
    atlas_root: Path | str,
    *,
    backend: EmbedBackend | None = None,
    force: bool = False,
) -> int:
    if not is_fastembed_available():
        return 0

    atlas_root = Path(atlas_root).expanduser()
    backend = backend or configured_backend(atlas_root)
    db_path = _db_path(atlas_root)
    connection = sqlite3.connect(str(db_path))
    try:
        rows = connection.execute(
            """
            SELECT
                n.id,
                n.title,
                n.body,
                n.modified,
                e.computed_at
            FROM notes n
            LEFT JOIN embeddings e
                ON e.note_id = n.id
               AND e.model = ?
            ORDER BY n.id ASC
            """,
            (backend.model_name,),
        ).fetchall()
    finally:
        connection.close()

    pending: list[tuple[str, str]] = []
    for row in rows:
        note_id = str(row[0])
        title = None if row[1] is None else str(row[1])
        body = None if row[2] is None else str(row[2])
        modified = float(row[3] or 0.0)
        computed_at = None if row[4] is None else float(row[4])
        if not force and computed_at is not None and computed_at >= modified:
            continue
        text = _note_text(title, body)
        if not text.strip():
            continue
        pending.append((note_id, text))

    if not pending:
        return 0

    embeddings = backend.embed_batch([text for _, text in pending])
    connection = sqlite3.connect(str(db_path))
    try:
        for (note_id, _), embedding in zip(pending, embeddings):
            connection.execute(
                """
                INSERT OR REPLACE INTO embeddings (note_id, embedding, model, dim, computed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    note_id,
                    _encode_embedding(embedding),
                    backend.model_name,
                    len(embedding),
                    time.time(),
                ),
            )
        connection.commit()
    finally:
        connection.close()
    return len(pending)


def has_embeddings(
    atlas_root: Path | str,
    *,
    model_name: str | None = None,
) -> bool:
    db_path = _db_path(atlas_root)
    if not db_path.exists():
        return False
    connection = sqlite3.connect(str(db_path))
    try:
        if model_name:
            row = connection.execute(
                "SELECT COUNT(*) FROM embeddings WHERE model = ?",
                (model_name,),
            ).fetchone()
        else:
            row = connection.execute("SELECT COUNT(*) FROM embeddings").fetchone()
    finally:
        connection.close()
    return bool(row and int(row[0]) > 0)


def embeddings_coverage(
    atlas_root: Path | str,
    *,
    model_name: str | None = None,
) -> dict[str, Any]:
    connection = sqlite3.connect(str(_db_path(atlas_root)))
    try:
        total_row = connection.execute("SELECT COUNT(*) FROM notes").fetchone()
        if model_name:
            embedded_row = connection.execute(
                """
                SELECT COUNT(*)
                FROM notes n
                JOIN embeddings e ON e.note_id = n.id
                WHERE e.model = ?
                """,
                (model_name,),
            ).fetchone()
        else:
            embedded_row = connection.execute(
                """
                SELECT COUNT(DISTINCT n.id)
                FROM notes n
                JOIN embeddings e ON e.note_id = n.id
                """
            ).fetchone()
    finally:
        connection.close()

    total = 0 if total_row is None else int(total_row[0])
    embedded = 0 if embedded_row is None else int(embedded_row[0])
    coverage = 0.0 if total == 0 else embedded / total
    return {"embedded": embedded, "total": total, "coverage": coverage}


def cosine_search(
    db_path: Path | str,
    query_embedding: Iterable[float],
    *,
    top_k: int = 10,
    model_name: str | None = None,
) -> list[dict[str, Any]]:
    connection = sqlite3.connect(str(Path(db_path).expanduser()))
    try:
        query = """
            SELECT e.note_id, e.embedding, n.path, n.title
            FROM embeddings e
            JOIN notes n ON n.id = e.note_id
        """
        params: list[Any] = []
        if model_name:
            query += " WHERE e.model = ?"
            params.append(model_name)
        rows = connection.execute(query, params).fetchall()
    finally:
        connection.close()

    results: list[dict[str, Any]] = []
    for note_id, embedding_bytes, path, title in rows:
        similarity = _vector_similarity(query_embedding, _decode_embedding(embedding_bytes))
        results.append(
            {
                "note_id": str(note_id),
                "path": str(path),
                "title": str(title or note_id),
                "similarity": similarity,
            }
        )
    results.sort(key=lambda item: (-float(item["similarity"]), str(item["path"])))
    return results[:top_k]


def semantic_query_paths(
    atlas_root: Path | str,
    expression: str,
    *,
    top_k: int = 20,
) -> list[str]:
    if not expression.strip() or not is_fastembed_available():
        return []

    atlas_root = Path(atlas_root).expanduser()
    settings = _embedding_config(atlas_root)
    backend_name = str(settings.get("backend") or "fastembed").strip().lower()
    if backend_name != "fastembed":
        return []

    backend = configured_backend(atlas_root)
    if not has_embeddings(atlas_root, model_name=backend.model_name):
        return []

    try:
        threshold = float(settings.get("similarity_threshold", 0.7))
    except (TypeError, ValueError):
        threshold = 0.7

    query_embedding = backend.embed(expression)
    semantic_results = cosine_search(
        _db_path(atlas_root),
        query_embedding,
        top_k=top_k,
        model_name=backend.model_name,
    )
    index = Index(atlas_root)
    fts_paths = index.query(expression)
    fts_rank = {
        str(Path(path)): max(0.0, 1.0 - (position / max(len(fts_paths), 1)))
        for position, path in enumerate(fts_paths)
    }

    combined: dict[str, float] = {}
    for result in semantic_results:
        path = str(result["path"])
        semantic_score = float(result["similarity"])
        if semantic_score < threshold and path not in fts_rank:
            continue
        combined[path] = max(combined.get(path, 0.0), semantic_score + (0.2 * fts_rank.get(path, 0.0)))
    for path, rank_score in fts_rank.items():
        combined[path] = max(combined.get(path, 0.0), 0.2 * rank_score)

    return [
        path
        for path, _score in sorted(
            combined.items(),
            key=lambda item: (-item[1], item[0]),
        )[:top_k]
    ]
