from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .atlas import slugify


def working_set_dir(atlas_root: Path) -> Path:
    return atlas_root / "working-set"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime | None:
    raw = value.strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _entry_path(atlas_root: Path, *, role: str, scope: str, entry_id: str) -> Path:
    return working_set_dir(atlas_root) / role / scope / f"{entry_id}.json"


def _read_entry(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_expired(entry: dict[str, Any], *, now: datetime | None = None) -> bool:
    if bool(entry.get("pinned")):
        return False
    expires_at = _parse_iso(str(entry.get("expires_at") or ""))
    if expires_at is None:
        return False
    return expires_at <= (now or datetime.now(timezone.utc))


def add_entry(
    atlas_root: Path,
    *,
    title: str,
    role: str,
    scope: str,
    body: str = "",
    provenance: list[str] | None = None,
    verification_needed: bool = False,
    pinned: bool = False,
    ttl_hours: int = 24,
) -> dict[str, Any]:
    created_at = datetime.now(timezone.utc)
    entry_id = f"{created_at.strftime('%Y%m%dT%H%M%SZ')}-{slugify(title)}"
    expires_at = None if pinned else (created_at + timedelta(hours=ttl_hours)).isoformat().replace("+00:00", "Z")
    entry = {
        "id": entry_id,
        "title": title.strip(),
        "role": role.strip().lower() or "intake",
        "scope": scope.strip().lower() or "general",
        "body": body,
        "provenance": [item for item in (provenance or []) if item],
        "verification_needed": bool(verification_needed),
        "pinned": bool(pinned),
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "updated_at": created_at.isoformat().replace("+00:00", "Z"),
        "expires_at": expires_at,
    }
    destination = _entry_path(
        atlas_root,
        role=entry["role"],
        scope=entry["scope"],
        entry_id=entry_id,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(entry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    entry["path"] = str(destination)
    return entry


def list_entries(
    atlas_root: Path,
    *,
    role: str | None = None,
    scope: str | None = None,
    include_expired: bool = False,
    delete_expired: bool = False,
) -> list[dict[str, Any]]:
    root = working_set_dir(atlas_root)
    if not root.exists():
        return []
    now = datetime.now(timezone.utc)
    entries: list[dict[str, Any]] = []
    for path in root.glob("*/*/*.json"):
        if not path.is_file():
            continue
        try:
            entry = _read_entry(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if role and str(entry.get("role") or "") != role:
            continue
        if scope and str(entry.get("scope") or "") != scope:
            continue
        expired = _is_expired(entry, now=now)
        if expired and delete_expired:
            path.unlink(missing_ok=True)
            continue
        if expired and not include_expired:
            continue
        entry["expired"] = expired
        entry["path"] = str(path)
        entries.append(entry)
    entries.sort(
        key=lambda item: (
            str(item.get("created_at") or ""),
            str(item.get("id") or ""),
        ),
        reverse=True,
    )
    return entries


def gc_entries(atlas_root: Path) -> dict[str, Any]:
    root = working_set_dir(atlas_root)
    if not root.exists():
        return {
            "path": str(root),
            "removed": [],
            "removed_count": 0,
            "remaining_count": 0,
        }
    removed: list[str] = []
    now = datetime.now(timezone.utc)
    for path in root.glob("*/*/*.json"):
        if not path.is_file():
            continue
        try:
            entry = _read_entry(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if _is_expired(entry, now=now):
            path.unlink(missing_ok=True)
            removed.append(str(path))
    remaining_count = len(list(root.glob("*/*/*.json")))
    return {
        "path": str(root),
        "removed": removed,
        "removed_count": len(removed),
        "remaining_count": remaining_count,
    }


def working_set_stats(atlas_root: Path) -> dict[str, Any]:
    root = working_set_dir(atlas_root)
    if not root.exists():
        return {
            "dir": str(root),
            "exists": False,
            "count": 0,
            "expired_count": 0,
            "pinned_count": 0,
            "roles": [],
        }
    entries = list_entries(atlas_root, include_expired=True, delete_expired=False)
    roles = sorted({str(entry.get("role") or "") for entry in entries if entry.get("role")})
    return {
        "dir": str(root),
        "exists": True,
        "count": len(entries),
        "expired_count": sum(1 for entry in entries if bool(entry.get("expired"))),
        "pinned_count": sum(1 for entry in entries if bool(entry.get("pinned"))),
        "roles": roles,
    }
