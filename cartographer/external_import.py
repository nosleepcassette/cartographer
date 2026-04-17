# maps · cassette.help · MIT
# External session import parsers: ChatGPT and Claude.ai web exports
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .session_import import (
    ImportedSession,
    PROJECT_PATTERNS,
    ENTITY_PATTERNS,
    _detect_links,
    _truncate,
    _unique,
    _today_string,
    slugify,
)


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------

def _ts_to_date(ts: float | int | None) -> str:
    if ts is None:
        return _today_string()
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).date().isoformat()
    except Exception:
        return _today_string()


def _iso_to_date(iso: str | None) -> str:
    if not iso:
        return _today_string()
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).date().isoformat()
    except Exception:
        return iso[:10] if iso and len(iso) >= 10 else _today_string()


# ---------------------------------------------------------------------------
# ChatGPT export (conversations.json from Settings → Data Controls → Export)
# ---------------------------------------------------------------------------

def _walk_chatgpt_mapping(mapping: dict[str, Any]) -> list[dict[str, str]]:
    """Walk parent→children tree, return ordered user/assistant messages."""
    # find root: node whose parent is None or 'client-created-root'
    root_id: str | None = None
    for node_id, node in mapping.items():
        parent = node.get("parent")
        if parent is None or parent == "client-created-root":
            root_id = node_id
            break
    if root_id is None:
        return []

    messages: list[dict[str, str]] = []

    def walk(node_id: str) -> None:
        node = mapping.get(node_id)
        if not node:
            return
        msg = node.get("message")
        if msg:
            role = msg.get("author", {}).get("role", "")
            if role in ("user", "assistant"):
                content = msg.get("content", {})
                parts = content.get("parts", []) if isinstance(content, dict) else []
                text = ""
                for part in parts:
                    if isinstance(part, str) and part.strip():
                        text = part.strip()
                        break
                if text:
                    messages.append({"role": role, "text": text})
        for child_id in node.get("children", []):
            walk(child_id)

    walk(root_id)
    return messages


def _parse_chatgpt_conversation(conv: dict[str, Any]) -> ImportedSession:
    title_raw = str(conv.get("title") or "untitled")
    conv_id = str(conv.get("conversation_id") or conv.get("id") or slugify(title_raw))
    create_time = conv.get("create_time")
    update_time = conv.get("update_time")
    session_date = _ts_to_date(create_time)

    mapping = conv.get("mapping") or {}
    messages = _walk_chatgpt_mapping(mapping) if mapping else []

    user_msgs = _unique([m["text"] for m in messages if m["role"] == "user"])
    assistant_msgs = _unique([m["text"] for m in messages if m["role"] == "assistant"])

    summary_source = assistant_msgs[0] if assistant_msgs else (user_msgs[0] if user_msgs else "")
    summary = _truncate(summary_source or "summary unavailable", 320)

    combined = "\n".join(user_msgs[:10] + assistant_msgs[:5])
    projects = _detect_links(combined, PROJECT_PATTERNS)
    entities = _detect_links(combined, ENTITY_PATTERNS)

    slug = slugify(f"chatgpt-{session_date}-{conv_id[:16]}")
    title = f"ChatGPT: {title_raw}"

    return ImportedSession(
        source_type="chatgpt",
        agent="chatgpt",
        source_path=Path(conv_id),
        source_id=slug,
        session_date=session_date,
        title=title,
        summary=summary,
        requests=user_msgs[:20],
        touched_files=[],
        projects=projects,
        entities=entities,
        session_started=_ts_to_date(create_time),
        session_updated=_ts_to_date(update_time),
        model=str(conv.get("default_model_slug") or ""),
        source_excerpt=user_msgs[:8],
    )


def parse_chatgpt_export(path: Path) -> list[ImportedSession]:
    """Parse a ChatGPT conversations.json bulk export into ImportedSessions."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raise ValueError(f"expected JSON array, got {type(raw).__name__}")
    sessions: list[ImportedSession] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            sessions.append(_parse_chatgpt_conversation(item))
        except Exception:
            pass
    return sessions


# ---------------------------------------------------------------------------
# Claude.ai web export (conversations.json from Settings → Account → Export)
# ---------------------------------------------------------------------------

def _parse_claude_web_conversation(conv: dict[str, Any]) -> ImportedSession:
    name = str(conv.get("name") or conv.get("title") or "untitled")
    uuid = str(conv.get("uuid") or conv.get("id") or slugify(name))
    created_at = conv.get("created_at")
    updated_at = conv.get("updated_at")
    session_date = _iso_to_date(str(created_at) if created_at else None)

    chat_messages = conv.get("chat_messages") or []
    user_msgs: list[str] = []
    assistant_msgs: list[str] = []
    for msg in chat_messages:
        if not isinstance(msg, dict):
            continue
        sender = str(msg.get("sender") or msg.get("role") or "")
        text = str(msg.get("text") or msg.get("content") or "").strip()
        if not text:
            continue
        if sender in ("human", "user"):
            user_msgs.append(text)
        elif sender in ("assistant", "claude"):
            assistant_msgs.append(text)

    user_msgs = _unique(user_msgs)
    assistant_msgs = _unique(assistant_msgs)

    summary_source = assistant_msgs[0] if assistant_msgs else (user_msgs[0] if user_msgs else "")
    summary = _truncate(summary_source or "summary unavailable", 320)

    combined = "\n".join(user_msgs[:10] + assistant_msgs[:5])
    projects = _detect_links(combined, PROJECT_PATTERNS)
    entities = _detect_links(combined, ENTITY_PATTERNS)

    slug = slugify(f"claude-web-{session_date}-{uuid[:16]}")
    title = f"Claude.ai: {name}"

    return ImportedSession(
        source_type="claude-web",
        agent="claude-web",
        source_path=Path(uuid),
        source_id=slug,
        session_date=session_date,
        title=title,
        summary=summary,
        requests=user_msgs[:20],
        touched_files=[],
        projects=projects,
        entities=entities,
        session_started=_iso_to_date(str(created_at) if created_at else None),
        session_updated=_iso_to_date(str(updated_at) if updated_at else None),
        model=None,
        source_excerpt=user_msgs[:8],
    )


def parse_claude_web_export(path: Path) -> list[ImportedSession]:
    """Parse a Claude.ai conversations.json export into ImportedSessions."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raise ValueError(f"expected JSON array, got {type(raw).__name__}")
    sessions: list[ImportedSession] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            sessions.append(_parse_claude_web_conversation(item))
        except Exception:
            pass
    return sessions
