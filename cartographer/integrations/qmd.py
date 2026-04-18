"""Optional qmd integration helpers.

This module is intentionally best-effort:
- Missing qmd returns empty results.
- qmd failures return empty results.
- Callers should treat an empty result as "fall back to the existing path".
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


QMD_BIN = "qmd"
DEFAULT_TIMEOUT_SECONDS = 10
_COLLECTION_LINE = re.compile(r"^(?P<name>[A-Za-z0-9._-]+)\s+\(qmd://[^)]+\)\s*$")
_COLLECTION_PATH_LINE = re.compile(r"^\s*Path:\s+(?P<path>.+?)\s*$")
_QMD_URI = re.compile(r"^qmd://(?P<collection>[^/]+)/(?P<relative>.*)$")


@dataclass(slots=True)
class QmdHit:
    path: str
    docid: str
    score: float
    snippet: str
    collection: str | None = None


def is_available() -> bool:
    return shutil.which(QMD_BIN) is not None


def collection_names() -> list[str]:
    completed = _run_command([QMD_BIN, "collection", "list"])
    if completed is None or completed.returncode != 0:
        return []
    names: list[str] = []
    for line in completed.stdout.splitlines():
        match = _COLLECTION_LINE.match(line.strip())
        if match:
            names.append(match.group("name"))
    return names


def collection_path(name: str) -> Path | None:
    completed = _run_command([QMD_BIN, "collection", "show", name])
    if completed is None or completed.returncode != 0:
        return None
    for line in completed.stdout.splitlines():
        match = _COLLECTION_PATH_LINE.match(line)
        if match:
            return Path(match.group("path")).expanduser()
    return None


def collection_name_for_path(target: str | Path) -> str | None:
    wanted = Path(target).expanduser().resolve()
    for name in collection_names():
        root = collection_path(name)
        if root is not None and root.resolve() == wanted:
            return name
    return None


def ensure_collection(
    target: str | Path,
    *,
    preferred_name: str = "atlas",
) -> tuple[str | None, bool]:
    wanted = Path(target).expanduser().resolve()
    existing = collection_name_for_path(wanted)
    if existing is not None:
        return existing, False

    slug = re.sub(r"[^a-z0-9]+", "-", wanted.name.lower()).strip("-") or "atlas"
    candidates = [preferred_name]
    if slug != preferred_name:
        candidates.append(f"{preferred_name}-{slug}")

    for candidate in candidates:
        current_path = collection_path(candidate)
        if current_path is not None:
            if current_path.resolve() == wanted:
                return candidate, False
            continue
        if add_collection(wanted, candidate):
            return candidate, True

    suffix = 2
    while suffix < 100:
        candidate = f"{preferred_name}-{suffix}"
        if collection_path(candidate) is None and add_collection(wanted, candidate):
            return candidate, True
        suffix += 1
    return None, False


def query(
    text: str,
    *,
    collection: str | None = None,
    n: int = 10,
    min_score: float = 0.3,
    mode: str = "query",
) -> list[QmdHit]:
    """Query qmd in search, vsearch, or query mode.

    Returns an empty list when qmd is unavailable or any qmd call fails.
    """
    if mode not in {"search", "vsearch", "query"}:
        return []

    if not is_available():
        return []

    command = [
        QMD_BIN,
        mode,
        text,
        "--json",
        "-n",
        str(max(1, int(n))),
        "--min-score",
        str(float(min_score)),
    ]
    if collection:
        command.extend(["-c", collection])

    completed = _run_command(command)
    if completed is None:
        return []

    if completed.returncode != 0:
        return []

    try:
        payload = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError:
        return []

    hits = _extract_hits(payload)
    normalized_hits: list[QmdHit] = []
    for hit in hits:
        try:
            normalized_hits.append(QmdHit(**_normalize_hit(hit)))
        except (TypeError, ValueError):
            continue
    return normalized_hits


def embed_incremental() -> None:
    """Best-effort qmd re-index.

    Silent no-op when qmd is unavailable.
    """
    if not is_available():
        return

    try:
        subprocess.Popen(
            [QMD_BIN, "embed", "--incremental"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return


def embed_full() -> bool:
    if not is_available():
        return False
    completed = _run_command([QMD_BIN, "embed"], timeout=None)
    return completed is not None and completed.returncode == 0


def add_collection(target: str | Path, name: str) -> bool:
    if not is_available():
        return False
    completed = _run_command(
        [QMD_BIN, "collection", "add", str(Path(target).expanduser()), "--name", name]
    )
    return completed is not None and completed.returncode == 0


def add_context(target: str, description: str) -> bool:
    if not is_available():
        return False
    completed = _run_command([QMD_BIN, "context", "add", target, description])
    return completed is not None and completed.returncode == 0


def resolve_path(raw_path: str, *, fallback_root: str | Path | None = None) -> Path | None:
    value = raw_path.strip()
    if not value:
        return None

    match = _QMD_URI.match(value)
    if match:
        root = collection_path(match.group("collection"))
        if root is None:
            return None
        return root / Path(match.group("relative"))

    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    if fallback_root is not None:
        return Path(fallback_root).expanduser() / path
    return path


def _extract_hits(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if isinstance(payload, dict):
        for key in ("results", "hits", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]

    return []


def _normalize_hit(hit: dict[str, Any]) -> dict[str, Any]:
    snippet = hit.get("snippet")
    if not isinstance(snippet, str) or not snippet.strip():
        snippet = hit.get("content")
    if not isinstance(snippet, str):
        snippet = ""

    collection = hit.get("collection")
    if collection is not None:
        collection = str(collection).strip() or None

    return {
        "path": str(hit.get("path") or hit.get("file") or "").strip(),
        "docid": str(hit.get("docid") or hit.get("id") or "").strip(),
        "score": float(hit.get("score", 0.0)),
        "snippet": snippet[:400],
        "collection": collection,
    }


def _run_command(
    command: list[str],
    *,
    timeout: float | None = DEFAULT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str] | None:
    kwargs: dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "check": False,
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    try:
        return subprocess.run(command, **kwargs)
    except (subprocess.TimeoutExpired, OSError):
        return None
