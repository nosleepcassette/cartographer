from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .config import load_config, save_config
from .index import Index

if TYPE_CHECKING:
    from .notes import Note


SECRET_PATTERNS = [
    r"(?:api[_-]?key|apikey)\s*[=:]\s*[\"']?[\w-]{20,}",
    r"(?:auth[_-]?token|bearer)\s*[=:]\s*[\"']?[\w-]{20,}",
    r"(?:password|passwd|pwd)\s*[=:]\s*[\"']?[\w-]{8,}",
    r"(?:secret[_-]?key|private[_-]?key)\s*[=:]\s*[\"']?[\w-]{20,}",
    r"(?:account[_-]?sid)\s*[=:]\s*[\"']?AC[\w]{32}",
    r"(?:client[_-]?secret)\s*[=:]\s*[\"']?[\w-]{20,}",
    r"-----BEGIN (?:RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----",
    r"mongodb://[^:\s]+:[^@\s]+@",
    r"postgres(?:ql)?://[^:\s]+:[^@\s]+@",
    r"sk-[A-Za-z0-9]{16,}",
]

STACK_TRACE_PATTERNS = [
    r"Traceback \(most recent call last\):",
    r'File ".*?", line \d+, in ',
    r"^\s+at [\w.$<>]+\(",
    r"Exception in thread ",
]

CODE_FENCE_PATTERN = re.compile(r"```[^\n]*\n(?P<body>.*?)```", re.DOTALL)


class GuardrailRejectError(RuntimeError):
    pass


def _guardrail_config(atlas_root: Path | str) -> dict[str, Any]:
    config = load_config(root=atlas_root)
    raw = config.get("guardrails", {}) if isinstance(config, dict) else {}
    return raw if isinstance(raw, dict) else {}


def _db_path(atlas_root: Path | str) -> Path:
    return Path(atlas_root).expanduser() / ".cartographer" / "index.db"


def atlas_root_for_path(path: Path) -> Path | None:
    current = path.expanduser().resolve()
    candidates = [current] + list(current.parents)
    for candidate in candidates:
        if (candidate / ".cartographer" / "config.toml").exists():
            return candidate
    return None


def _violation_id(note_id: str, violation_type: str, detail: str) -> str:
    payload = f"{note_id}|{violation_type}|{detail}"
    return "gv-" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def _record_violations(
    atlas_root: Path | str,
    note_id: str,
    violations: list[dict[str, Any]],
) -> None:
    if not violations:
        return
    Index(Path(atlas_root).expanduser())
    connection = sqlite3.connect(str(_db_path(atlas_root)))
    try:
        for item in violations:
            violation_id = _violation_id(note_id, item["type"], item.get("detail", ""))
            connection.execute(
                """
                INSERT OR REPLACE INTO guardrail_violations
                (id, note_id, violation_type, severity, detected_at, resolved)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                (
                    violation_id,
                    note_id,
                    item["type"],
                    item["severity"],
                    time.time(),
                ),
            )
        connection.commit()
    finally:
        connection.close()


def _duplicate_warning(
    atlas_root: Path,
    note_id: str,
    title: str,
    note_type: str,
    *,
    current_path: Path,
) -> dict[str, Any] | None:
    db_path = _db_path(atlas_root)
    if not db_path.exists():
        return None
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            """
            SELECT id, path
            FROM notes
            WHERE title = ? AND type = ? AND id != ?
            LIMIT 1
            """,
            (title, note_type, note_id),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        return None
    if Path(str(row["path"])).expanduser().resolve() == current_path.resolve():
        return None
    return {
        "type": "duplicate_check",
        "severity": "warn",
        "detail": f"duplicate title/type: {title} ({note_type})",
    }


def detect_guardrail_violations(
    note: "Note",
    atlas_root: Path | str,
) -> list[dict[str, Any]]:
    atlas_root = Path(atlas_root).expanduser()
    settings = _guardrail_config(atlas_root)
    title = str(note.frontmatter.get("title") or note.path.stem)
    note_type = str(note.frontmatter.get("type") or "note")
    note_id = str(note.frontmatter.get("id") or note.path.stem)
    rendered = title + "\n\n" + note.body
    violations: list[dict[str, Any]] = []

    if bool(settings.get("reject_secrets", True)):
        for pattern in SECRET_PATTERNS:
            match = re.search(pattern, rendered, flags=re.IGNORECASE | re.MULTILINE)
            if match:
                violations.append(
                    {
                        "type": "secret_patterns",
                        "severity": "reject",
                        "detail": match.group(0)[:80],
                    }
                )
                break

    if bool(settings.get("flag_stack_traces", True)):
        for pattern in STACK_TRACE_PATTERNS:
            if re.search(pattern, note.body, flags=re.IGNORECASE | re.MULTILINE):
                violations.append(
                    {
                        "type": "stack_trace",
                        "severity": "skip",
                        "detail": "stack trace detected",
                    }
                )
                break

    if bool(settings.get("warn_large_code", True)) and note_type != "code":
        try:
            max_code_lines = int(settings.get("max_code_lines", 50))
        except (TypeError, ValueError):
            max_code_lines = 50
        for match in CODE_FENCE_PATTERN.finditer(note.body):
            code_lines = [line for line in match.group("body").splitlines()]
            if len(code_lines) > max_code_lines:
                violations.append(
                    {
                        "type": "raw_code_blob",
                        "severity": "warn",
                        "detail": f"{len(code_lines)} code lines without type: code",
                    }
                )
                break

    if bool(settings.get("warn_duplicates", True)):
        duplicate = _duplicate_warning(
            atlas_root,
            note_id,
            title,
            note_type,
            current_path=note.path,
        )
        if duplicate is not None:
            violations.append(duplicate)

    return violations


def guardrails_pre_write(note: "Note") -> list[dict[str, Any]]:
    atlas_root = atlas_root_for_path(note.path)
    if atlas_root is None:
        return []
    settings = _guardrail_config(atlas_root)
    if not bool(settings.get("enabled", True)):
        return []
    violations = detect_guardrail_violations(note, atlas_root)
    if not violations:
        return []

    note_id = str(note.frontmatter.get("id") or note.path.stem)
    _record_violations(atlas_root, note_id, violations)

    warnings = [item for item in violations if item["severity"] == "warn"]
    for item in warnings:
        detail = item.get("detail", item["type"])
        print(f"guardrails warning [{item['type']}]: {detail}", file=sys.stderr)
    if warnings:
        flags = note.frontmatter.get("guardrail_flags") or []
        if not isinstance(flags, list):
            flags = []
        for item in warnings:
            if item["type"] not in flags:
                flags.append(item["type"])
        note.frontmatter["guardrail_flags"] = flags

    if any(item["type"] == "stack_trace" for item in violations):
        original_type = str(note.frontmatter.get("type") or "note")
        if original_type != "debug-dump":
            note.frontmatter["original_type"] = original_type
        note.frontmatter["type"] = "debug-dump"

    rejects = [item for item in violations if item["severity"] == "reject"]
    if rejects:
        summary = ", ".join(item["type"] for item in rejects)
        raise GuardrailRejectError(f"write rejected by guardrails: {summary}")

    return violations


def scan_atlas(atlas_root: Path | str) -> dict[str, Any]:
    atlas_root = Path(atlas_root).expanduser()
    index = Index(atlas_root)
    findings: list[dict[str, Any]] = []
    connection = sqlite3.connect(str(_db_path(atlas_root)))
    try:
        connection.execute("DELETE FROM guardrail_violations")
        connection.commit()
    finally:
        connection.close()
    from .notes import Note

    for path in index.iter_note_paths():
        try:
            note = Note.from_file(path)
        except Exception:
            continue
        violations = detect_guardrail_violations(note, atlas_root)
        if not violations:
            continue
        note_id = str(note.frontmatter.get("id") or path.stem)
        _record_violations(atlas_root, note_id, violations)
        findings.extend(
            {
                "note_id": note_id,
                "path": str(path),
                "type": item["type"],
                "severity": item["severity"],
                "detail": item.get("detail"),
            }
            for item in violations
        )
    return {
        "count": len(findings),
        "violations": findings,
    }


def guardrails_status(atlas_root: Path | str) -> dict[str, Any]:
    atlas_root = Path(atlas_root).expanduser()
    settings = _guardrail_config(atlas_root)
    return {
        "enabled": bool(settings.get("enabled", True)),
        "config": settings,
    }


def set_guardrails_enabled(atlas_root: Path | str, enabled: bool) -> dict[str, Any]:
    atlas_root = Path(atlas_root).expanduser()
    config = load_config(root=atlas_root)
    section = config.setdefault("guardrails", {})
    if not isinstance(section, dict):
        section = {}
        config["guardrails"] = section
    section["enabled"] = bool(enabled)
    save_config(config, root=atlas_root)
    return guardrails_status(atlas_root)
