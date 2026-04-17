from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .index import Index
from .notes import Note, parse_link_target


TRANSCLUSION_PATTERN = re.compile(r"!\[\[([^\]]+)\]\]")
MAX_DEPTH = 3


def parse_transclusion_target(target: str) -> tuple[str, str | None]:
    return parse_link_target(target)


def resolve_transclusion(
    note_id: str,
    block_id: str | None,
    index: Index,
    visited: set[tuple[str, str | None]],
    depth: int,
) -> str | None:
    if depth > MAX_DEPTH:
        return None
    key = (note_id, block_id)
    if key in visited:
        return None
    visited.add(key)
    note_path = index.find_note_path(note_id)
    if note_path is None or not note_path.exists():
        return None
    try:
        note = Note.from_file(note_path)
    except Exception:
        return None
    if block_id:
        for block in note.blocks:
            if block.id == block_id:
                content = block.content.strip()
                if not content:
                    return None
                resolved = _resolve_transclusions_in_text(
                    content, index, visited, depth + 1
                )
                return resolved
        return None
    resolved_body = _resolve_transclusions_in_text(note.body, index, visited, depth + 1)
    return resolved_body


def _resolve_transclusions_in_text(
    text: str,
    index: Index,
    visited: set[tuple[str, str | None]],
    depth: int,
) -> str:
    def replace_transclusion(match: re.Match[str]) -> str:
        target = match.group(1).strip()
        note_id, block_id = parse_transclusion_target(target)
        if not note_id:
            return match.group(0)
        resolved = resolve_transclusion(note_id, block_id, index, visited, depth)
        if resolved is None:
            return match.group(0)
        return resolved

    return TRANSCLUSION_PATTERN.sub(replace_transclusion, text)


def resolve_note_transclusions(
    note_id: str,
    index: Index,
    max_depth: int = MAX_DEPTH,
) -> tuple[str, list[str]]:
    note_path = index.find_note_path(note_id)
    if note_path is None or not note_path.exists():
        return "", [f"note not found: {note_id}"]
    try:
        note = Note.from_file(note_path)
    except Exception as e:
        return "", [f"failed to read note: {e}"]
    visited: set[tuple[str, str | None]] = set()
    resolved_body = _resolve_transclusions_in_text(note.body, index, visited, 0)
    return resolved_body, []


def export_note_with_transclusions(
    note_id: str,
    atlas_root: Path,
    output_format: str = "markdown",
) -> dict[str, Any]:
    index = Index(atlas_root)
    resolved_body, errors = resolve_note_transclusions(note_id, index)
    if errors:
        return {"success": False, "errors": errors}
    note_path = index.find_note_path(note_id)
    if note_path is None:
        return {"success": False, "errors": [f"note not found: {note_id}"]}
    note = Note.from_file(note_path)
    frontmatter = note.frontmatter.copy()
    body = resolved_body
    if output_format == "html":
        html_body = _markdown_to_html(body)
        body = html_body
    return {
        "success": True,
        "note_id": note_id,
        "title": frontmatter.get("title") or note_id,
        "frontmatter": frontmatter,
        "body": body,
        "format": output_format,
    }


def _markdown_to_html(text: str) -> str:
    html = text
    html = re.sub(r"^### (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
    html = re.sub(r"^## (.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
    html = re.sub(r"^# (.+)$", r"<h1>\1</h1>", html, flags=re.MULTILINE)
    html = re.sub(r"^- \[ \] (.+)$", r"<li>\1</li>", html)
    html = re.sub(r"^- \[x\] (.+)$", r"<li><del>\1</del></li>", html)
    html = re.sub(r"^- (.+)$", r"<li>\1</li>", html)
    html = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", html)
    html = re.sub(r"`([^`]+)`", r"<code>\1</code>", html)
    lines = html.split("\n")
    in_ul = False
    result_lines = []
    for line in lines:
        if line.startswith("<li>"):
            if not in_ul:
                result_lines.append("<ul>")
                in_ul = True
        else:
            if in_ul and not line.startswith("<li>"):
                result_lines.append("</ul>")
                in_ul = False
        result_lines.append(line)
    if in_ul:
        result_lines.append("</ul>")
    return "\n".join(result_lines)
