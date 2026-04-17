from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .notes import Note
from .templates import render_template


DEFAULT_SESSION_ROOTS = {
    "claude": Path.home() / ".claude" / "session-data",
    "hermes": Path.home() / ".hermes" / "sessions",
}

SESSION_GLOBS = {
    "claude": "*.tmp",
    "hermes": "*.json",
}

PROJECT_PATTERNS = {
    "cartographer": {
        "title": "cartographer",
        "patterns": [r"\bcartographer\b", r"\batlas\b"],
    },
    "mapsos": {
        "title": "mapsOS",
        "patterns": [r"\bmapsos\b"],
    },
    "hopeagent": {
        "title": "HopeAgent",
        "patterns": [r"\bhopeagent\b"],
    },
    "voicetape": {
        "title": "voicetape",
        "patterns": [r"\bvoicetape\b"],
    },
    "openclaw": {
        "title": "OpenClaw",
        "patterns": [r"\bopenclaw\b"],
    },
    "hermetica": {
        "title": "Hermetica",
        "patterns": [r"\bhermetica\b"],
    },
    "skinwalker": {
        "title": "skinwalker",
        "patterns": [r"\bskinwalker\b"],
    },
    "grove": {
        "title": "grove",
        "patterns": [r"\bgrove\b"],
    },
}

ENTITY_PATTERNS = {
    "chris": {"title": "Chris", "patterns": [r"\bchris\b"]},
    "maggie": {"title": "Maggie", "patterns": [r"\bmaggie\b"]},
    "sarah": {"title": "Sarah", "patterns": [r"\bsarah\b"]},
    "emma-x": {"title": "emma-x", "patterns": [r"\bemma(?:-x)?\b"]},
    "irene": {"title": "Irene", "patterns": [r"\birene\b"]},
    "karl": {"title": "Karl", "patterns": [r"\bkarl\b"]},
}

ENTITY_IMPORT_BLOCK_PATTERN = re.compile(
    r"<!-- cart:session-import-[^\n]+ start -->\n"
    r"## Imported Session [^\n]+\n\n"
    r"(?P<body>.*?)"
    r"<!-- cart:session-import-[^\n]+ end -->\n?",
    re.DOTALL,
)
SESSIONS_SECTION_PATTERN = re.compile(
    r"^## Sessions\n(?P<body>.*?)(?=^## |\Z)",
    re.MULTILINE | re.DOTALL,
)
SESSION_LINK_LINE_PATTERN = re.compile(
    r"^- \[\[(?P<session>[^\]]+)\]\](?: \((?P<date>\d{4}-\d{2}-\d{2})\))?$"
)


@dataclass(slots=True)
class ImportedSession:
    source_type: str
    agent: str
    source_path: Path
    source_id: str
    session_date: str
    title: str
    summary: str
    requests: list[str]
    touched_files: list[str]
    projects: list[str]
    entities: list[str]
    session_started: str | None = None
    session_updated: str | None = None
    model: str | None = None
    source_excerpt: list[str] | None = None

    @property
    def note_slug(self) -> str:
        return slugify(self.source_id)

    @property
    def note_id(self) -> str:
        return f"{self.agent}-session-{self.note_slug}"

    @property
    def relative_session_path(self) -> Path:
        return Path("agents") / self.agent / "sessions" / f"{self.note_slug}.md"

    @property
    def session_note_name(self) -> str:
        return self.relative_session_path.stem


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "session"


def _today_string() -> str:
    return date.today().isoformat()


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        stripped = item.strip()
        if not stripped or stripped in seen:
            continue
        seen.add(stripped)
        ordered.append(stripped)
    return ordered


def _truncate(value: str, limit: int = 240) -> str:
    compact = re.sub(r"\s+", " ", value).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _extract_markdown_field(text: str, label: str) -> str | None:
    match = re.search(
        rf"^\*\*{re.escape(label)}:\*\*\s*(?P<value>.+?)\s*$",
        text,
        re.MULTILINE,
    )
    if not match:
        return None
    value = match.group("value").strip()
    return value or None


def _extract_markdown_section(text: str, heading: str) -> str | None:
    match = re.search(
        rf"^### {re.escape(heading)}\n(?P<body>.*?)(?=^### |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        return None
    body = match.group("body").strip()
    return body or None


def _extract_bullets(section: str | None) -> list[str]:
    if not section:
        return []
    bullets: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            bullets.append(stripped[2:].strip())
    return _unique(bullets)


def _section_between_markers(text: str, start_marker: str, end_marker: str) -> str | None:
    if start_marker not in text or end_marker not in text:
        return None
    _, _, remainder = text.partition(start_marker)
    section, _, _ = remainder.partition(end_marker)
    section = section.strip()
    return section or None


def _detect_links(text: str, catalog: dict[str, dict[str, list[str] | str]]) -> list[str]:
    lowered = text.lower()
    matches: list[str] = []
    for slug, metadata in catalog.items():
        patterns = metadata.get("patterns", [])
        if not isinstance(patterns, list):
            continue
        if any(re.search(pattern, lowered, re.IGNORECASE) for pattern in patterns):
            matches.append(slug)
    return matches


def _session_note_link(imported: ImportedSession) -> str:
    return f"[[{imported.session_note_name}]]"


def _upsert_managed_section(body: str, section_id: str, heading: str, content: str) -> str:
    start = f"<!-- cart:{section_id} start -->"
    end = f"<!-- cart:{section_id} end -->"
    block = f"{start}\n## {heading}\n\n{content.strip()}\n{end}"
    pattern = re.compile(
        rf"{re.escape(start)}.*?{re.escape(end)}",
        re.DOTALL,
    )
    if pattern.search(body):
        updated = pattern.sub(block, body)
    else:
        updated = body.rstrip()
        if updated:
            updated += "\n\n"
        updated += block + "\n"
    if not updated.endswith("\n"):
        updated += "\n"
    return updated


def _extract_entity_session_refs(body: str) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    for match in ENTITY_IMPORT_BLOCK_PATTERN.finditer(body):
        block_body = match.group("body")
        session_match = re.search(r"- session:\s+\[\[(?P<session>[^\]]+)\]\]", block_body)
        date_match = re.search(r"- date:\s+(?P<date>\d{4}-\d{2}-\d{2})", block_body)
        if session_match:
            refs.append(
                (
                    session_match.group("session").strip(),
                    date_match.group("date").strip() if date_match else "",
                )
            )
    section_match = SESSIONS_SECTION_PATTERN.search(body)
    if section_match:
        for raw_line in section_match.group("body").splitlines():
            line = raw_line.strip()
            parsed = SESSION_LINK_LINE_PATTERN.match(line)
            if not parsed:
                continue
            refs.append((parsed.group("session").strip(), (parsed.group("date") or "").strip()))
    unique: list[tuple[str, str]] = []
    seen: set[str] = set()
    for session_name, session_date in refs:
        if not session_name or session_name in seen:
            continue
        seen.add(session_name)
        unique.append((session_name, session_date))
    return sorted(unique, key=lambda item: (item[1] or "", item[0]), reverse=True)


def _strip_entity_session_import_blocks(body: str) -> str:
    stripped = ENTITY_IMPORT_BLOCK_PATTERN.sub("", body)
    stripped = re.sub(r"\n{3,}", "\n\n", stripped)
    return stripped.rstrip() + "\n" if stripped.strip() else ""


def _upsert_sessions_section(body: str, refs: list[tuple[str, str]]) -> str:
    lines = [
        f"- [[{session_name}]]" + (f" ({session_date})" if session_date else "")
        for session_name, session_date in refs
    ] or ["- none yet"]
    section = "## Sessions\n\n" + "\n".join(lines) + "\n"
    if SESSIONS_SECTION_PATTERN.search(body):
        updated = SESSIONS_SECTION_PATTERN.sub(section, body, count=1)
    else:
        updated = body.rstrip()
        if updated:
            updated += "\n\n"
        updated += section
    updated = re.sub(r"\n{3,}", "\n\n", updated)
    return updated.rstrip() + "\n"


def _ensure_note(
    root: Path,
    relative_path: Path,
    *,
    title: str,
    note_type: str,
    note_id: str,
    body: str,
    tags: list[str] | None = None,
    links: list[str] | None = None,
    extra_frontmatter: dict[str, Any] | None = None,
) -> Note:
    path = root / relative_path
    today = _today_string()
    if path.exists():
        note = Note.from_file(path)
    else:
        note = Note(
            path=path,
            frontmatter={
                "id": note_id,
                "title": title,
                "type": note_type,
                "tags": tags or [],
                "links": links or [],
                "created": today,
                "modified": today,
            },
            body=body,
        )
    note.frontmatter["id"] = note_id
    note.frontmatter["title"] = title
    note.frontmatter["type"] = note_type
    note.frontmatter["modified"] = today
    if "created" not in note.frontmatter:
        note.frontmatter["created"] = today
    if tags is not None:
        note.frontmatter["tags"] = tags
    if links is not None:
        note.frontmatter["links"] = links
    if extra_frontmatter:
        note.frontmatter.update(extra_frontmatter)
    return note


def _ensure_daily_note(root: Path, session_date: str) -> Note:
    relative_path = Path("daily") / f"{session_date}.md"
    path = root / relative_path
    if path.exists():
        return Note.from_file(path)
    yesterday = None
    try:
        yesterday_date = datetime.fromisoformat(session_date).date()
        yesterday = (yesterday_date.fromordinal(yesterday_date.toordinal() - 1)).isoformat()
    except ValueError:
        yesterday = None
    content = render_template(
        "daily",
        {
            "id": f"daily-{session_date}",
            "title": session_date,
            "date": session_date,
            "yesterday": yesterday,
        },
        atlas_root=root,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return Note.from_file(path)


def _render_session_body(imported: ImportedSession) -> str:
    lines = [
        f"# {imported.title}",
        "",
        "## summary",
        "",
        imported.summary,
        "",
        "## surfaced tasks",
        "",
    ]
    if imported.requests:
        lines.extend(f"- {item}" for item in imported.requests)
    else:
        lines.append("- none surfaced")
    lines.extend(["", "## source metadata", ""])
    lines.append(f"- source: `{imported.source_path}`")
    lines.append(f"- source_type: {imported.source_type}")
    if imported.session_started:
        lines.append(f"- started: {imported.session_started}")
    if imported.session_updated:
        lines.append(f"- updated: {imported.session_updated}")
    if imported.model:
        lines.append(f"- model: {imported.model}")
    if imported.projects:
        lines.append(
            "- projects: "
            + ", ".join(f"[[{project_slug}]]" for project_slug in imported.projects)
        )
    if imported.entities:
        lines.append(
            "- entities: "
            + ", ".join(f"[[{entity_slug}]]" for entity_slug in imported.entities)
        )
    if imported.touched_files:
        lines.extend(["", "## files", ""])
        lines.extend(f"- `{path}`" for path in imported.touched_files[:20])
    if imported.source_excerpt:
        lines.extend(["", "## excerpts", ""])
        lines.extend(f"- {item}" for item in imported.source_excerpt[:12])
    return "\n".join(lines).rstrip() + "\n"


def parse_claude_session(path: Path) -> ImportedSession:
    text = path.read_text(encoding="utf-8")
    session_date = (
        _extract_markdown_field(text, "Date")
        or re.search(r"(\d{4}-\d{2}-\d{2})", path.stem).group(1)
    )
    summary_block = _section_between_markers(
        text,
        "<!-- ECC:SUMMARY:START -->",
        "<!-- ECC:SUMMARY:END -->",
    ) or text
    requests = _extract_bullets(_extract_markdown_section(summary_block, "Tasks"))
    touched_files = _extract_bullets(_extract_markdown_section(summary_block, "Files Modified"))
    summary = (
        _truncate(
            " ; ".join(requests[:3]),
            320,
        )
        if requests
        else _truncate(summary_block, 320)
    )
    link_text = "\n".join([summary_block, "\n".join(touched_files)])
    projects = _detect_links(link_text, PROJECT_PATTERNS)
    entities = _detect_links(link_text, ENTITY_PATTERNS)
    title = f"Claude session {path.stem}"
    return ImportedSession(
        source_type="claude",
        agent="claude",
        source_path=path,
        source_id=path.stem,
        session_date=session_date,
        title=title,
        summary=summary,
        requests=requests[:20],
        touched_files=touched_files[:20],
        projects=projects,
        entities=entities,
        session_started=_extract_markdown_field(text, "Started"),
        session_updated=_extract_markdown_field(text, "Last Updated"),
        source_excerpt=requests[:8],
    )


def _message_strings(raw_messages: Any, role: str) -> list[str]:
    messages: list[str] = []
    if not isinstance(raw_messages, list):
        return messages
    for item in raw_messages:
        if not isinstance(item, dict) or item.get("role") != role:
            continue
        content = item.get("content")
        if isinstance(content, str) and content.strip():
            messages.append(content.strip())
    return messages


def parse_hermes_session(path: Path) -> ImportedSession:
    payload = json.loads(path.read_text(encoding="utf-8"))
    user_messages = _unique(_message_strings(payload.get("messages"), "user"))
    assistant_messages = _unique(_message_strings(payload.get("messages"), "assistant"))
    summary_source = assistant_messages[-1] if assistant_messages else (user_messages[0] if user_messages else "")
    summary = _truncate(summary_source or "summary unavailable", 320)
    session_start = payload.get("session_start")
    last_updated = payload.get("last_updated")
    session_date = None
    for candidate in (session_start, last_updated):
        if isinstance(candidate, str) and len(candidate) >= 10:
            session_date = candidate[:10]
            break
    if session_date is None:
        match = re.search(r"(\d{8})", path.stem)
        if match:
            raw_date = match.group(1)
            session_date = f"{raw_date[0:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
        else:
            session_date = _today_string()
    combined_text = "\n".join(user_messages[:20] + assistant_messages[-5:])
    projects = _detect_links(combined_text, PROJECT_PATTERNS)
    entities = _detect_links(combined_text, ENTITY_PATTERNS)
    title = f"Hermes session {path.stem}"
    return ImportedSession(
        source_type="hermes",
        agent="hermes",
        source_path=path,
        source_id=path.stem,
        session_date=session_date,
        title=title,
        summary=summary,
        requests=user_messages[:20],
        touched_files=[],
        projects=projects,
        entities=entities,
        session_started=None if not isinstance(session_start, str) else session_start,
        session_updated=None if not isinstance(last_updated, str) else last_updated,
        model=None if not isinstance(payload.get("model"), str) else str(payload.get("model")),
        source_excerpt=user_messages[:8],
    )


def parse_session_file(source_type: str, path: Path) -> ImportedSession:
    if source_type == "claude":
        return parse_claude_session(path)
    if source_type == "hermes":
        return parse_hermes_session(path)
    raise ValueError(f"unsupported session source: {source_type}")


def default_session_paths(source_type: str, *, latest: int | None = None) -> list[Path]:
    if source_type not in DEFAULT_SESSION_ROOTS:
        raise ValueError(f"unsupported session source: {source_type}")
    root = DEFAULT_SESSION_ROOTS[source_type]
    if not root.exists():
        return []
    paths = sorted(root.glob(SESSION_GLOBS[source_type]), key=lambda item: item.stat().st_mtime)
    if latest is None:
        return paths
    if latest <= 0:
        return []
    return paths[-latest:]


def _update_session_note(root: Path, imported: ImportedSession) -> Path:
    relative_path = imported.relative_session_path
    note = _ensure_note(
        root,
        relative_path,
        title=imported.title,
        note_type="agent-log",
        note_id=imported.note_id,
        body=_render_session_body(imported),
        tags=[imported.agent, "session", "imported"],
        links=sorted(imported.projects + imported.entities),
        extra_frontmatter={
            "agent": imported.agent,
            "source": str(imported.source_path),
            "source_type": imported.source_type,
            "summary_preview": imported.summary,
            "date": imported.session_date,
            "session_started": imported.session_started or "",
            "session_updated": imported.session_updated or "",
            "model": imported.model or "",
        },
    )
    note.body = _render_session_body(imported)
    note.path.parent.mkdir(parents=True, exist_ok=True)
    note.write()
    return note.path


def _session_summary_line(imported: ImportedSession) -> str:
    return f"- {_session_note_link(imported)} — {imported.session_date} — {imported.summary}"


def _update_agent_summary(root: Path, imported: ImportedSession, session_note: Path) -> Path:
    relative_path = Path("agents") / imported.agent / "SUMMARY.md"
    note = _ensure_note(
        root,
        relative_path,
        title=f"{imported.agent} summary",
        note_type="agent-summary",
        note_id=f"{imported.agent}-summary",
        body=f"# {imported.agent} summary\n",
        tags=[imported.agent, "summary"],
        links=[session_note.stem],
        extra_frontmatter={"agent": imported.agent},
    )
    session_directory = root / "agents" / imported.agent / "sessions"
    session_lines: list[str] = []
    for path in sorted(session_directory.glob("*.md"))[-12:]:
        session_note_payload = Note.from_file(path)
        summary_preview = str(session_note_payload.frontmatter.get("summary_preview") or path.stem)
        session_date = str(session_note_payload.frontmatter.get("date") or path.stem)
        session_lines.append(f"- [[{path.stem}]] — {session_date} — {summary_preview}")
    content_lines = [
        f"Last import: {_session_note_link(imported)}",
        "",
        imported.summary,
        "",
        "Recent sessions:",
    ]
    if session_lines:
        content_lines.extend(session_lines)
    else:
        content_lines.append("- none yet")
    note.body = _upsert_managed_section(
        note.body,
        "session-import-summary",
        "Imported Sessions",
        "\n".join(content_lines),
    )
    existing_links = note.frontmatter.get("links", [])
    if not isinstance(existing_links, list):
        existing_links = []
    note.frontmatter["links"] = _unique(
        [str(item) for item in existing_links if isinstance(item, str)] + [session_note.stem]
    )
    note.write()
    return note.path


def _update_daily_surface(root: Path, imported: ImportedSession, session_note: Path) -> Path:
    note = _ensure_daily_note(root, imported.session_date)
    lines = [
        f"- session: [[{session_note.stem}]]",
        f"- source: `{imported.source_path}`",
        f"- summary: {imported.summary}",
    ]
    if imported.requests:
        lines.append("- surfaced tasks:")
        lines.extend(f"  - {item}" for item in imported.requests[:8])
    if imported.projects:
        lines.append(
            "- projects: " + ", ".join(f"[[{project_slug}]]" for project_slug in imported.projects)
        )
    if imported.entities:
        lines.append(
            "- entities: " + ", ".join(f"[[{entity_slug}]]" for entity_slug in imported.entities)
        )
    note.body = _upsert_managed_section(
        note.body,
        f"session-import-{imported.note_slug}",
        f"Imported Session {imported.source_id}",
        "\n".join(lines),
    )
    existing_links = note.frontmatter.get("links", [])
    link_values = [str(item) for item in existing_links if isinstance(item, str)]
    note.frontmatter["links"] = _unique(
        link_values + [f"daily-{imported.session_date}"] + imported.projects + imported.entities
    )
    note.write()
    return note.path


def _ensure_project_note(root: Path, project_slug: str) -> Note:
    title = str(PROJECT_PATTERNS[project_slug]["title"])
    relative_path = Path("projects") / f"{project_slug}.md"
    path = root / relative_path
    if path.exists():
        note = Note.from_file(path)
        note.frontmatter["type"] = "project"
        note.frontmatter["title"] = title
        note.frontmatter["id"] = project_slug
        if "status" not in note.frontmatter:
            note.frontmatter["status"] = "active"
        if "tags" not in note.frontmatter:
            note.frontmatter["tags"] = ["project"]
        return note
    content = render_template(
        "project",
        {
            "id": project_slug,
            "title": title,
            "date": _today_string(),
        },
        atlas_root=root,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return Note.from_file(path)


def _update_project_surfaces(root: Path, imported: ImportedSession, session_note: Path) -> list[Path]:
    written: list[Path] = []
    for project_slug in imported.projects:
        note = _ensure_project_note(root, project_slug)
        note.body = _upsert_managed_section(
            note.body,
            f"session-import-{imported.note_slug}",
            f"Imported Session {imported.source_id}",
            "\n".join(
                [
                    f"- session: [[{session_note.stem}]]",
                    f"- date: {imported.session_date}",
                    f"- summary: {imported.summary}",
                ]
            ),
        )
        existing_links = note.frontmatter.get("links", [])
        link_values = [str(item) for item in existing_links if isinstance(item, str)]
        note.frontmatter["links"] = _unique(link_values + [session_note.stem] + imported.entities)
        note.write()
        written.append(note.path)
    return written


def _ensure_entity_note(root: Path, entity_slug: str) -> Note:
    title = str(ENTITY_PATTERNS[entity_slug]["title"])
    relative_path = Path("entities") / f"{entity_slug}.md"
    note = _ensure_note(
        root,
        relative_path,
        title=title,
        note_type="entity",
        note_id=entity_slug,
        body=f"# {title}\n",
        tags=["entity"],
        links=[],
    )
    return note


def _update_entity_surfaces(root: Path, imported: ImportedSession, session_note: Path) -> list[Path]:
    written: list[Path] = []
    for entity_slug in imported.entities:
        note = _ensure_entity_note(root, entity_slug)
        refs = _extract_entity_session_refs(note.body)
        refs.append((session_note.stem, imported.session_date))
        note.body = _upsert_sessions_section(_strip_entity_session_import_blocks(note.body), refs)
        existing_links = note.frontmatter.get("links", [])
        link_values = [str(item) for item in existing_links if isinstance(item, str)]
        note.frontmatter["links"] = _unique(link_values + [session_note.stem] + imported.projects)
        note.write()
        written.append(note.path)
    return written


def clean_entity_imports(root: Path) -> dict[str, Any]:
    entity_dir = root / "entities"
    if not entity_dir.exists():
        return {"updated": 0, "paths": []}
    updated_paths: list[Path] = []
    for path in sorted(entity_dir.glob("*.md")):
        note = Note.from_file(path)
        if str(note.frontmatter.get("type") or "") != "entity":
            continue
        refs = _extract_entity_session_refs(note.body)
        cleaned_body = _upsert_sessions_section(_strip_entity_session_import_blocks(note.body), refs)
        if cleaned_body == note.body:
            continue
        note.body = cleaned_body
        note.frontmatter["modified"] = _today_string()
        existing_links = note.frontmatter.get("links", [])
        link_values = [str(item) for item in existing_links if isinstance(item, str)]
        note.frontmatter["links"] = _unique(link_values + [session_name for session_name, _ in refs])
        note.write()
        updated_paths.append(path)
    return {"updated": len(updated_paths), "paths": [str(path) for path in updated_paths]}


def _update_task_surface(root: Path, imported: ImportedSession, session_note: Path) -> Path:
    relative_path = Path("tasks") / "session-imports.md"
    note = _ensure_note(
        root,
        relative_path,
        title="Session Imports",
        note_type="task-intake",
        note_id="session-imports",
        body="# Session Imports\n",
        tags=["tasks", "session-import"],
        links=[],
    )
    lines = [
        f"- session: [[{session_note.stem}]]",
        "- surfaced tasks:",
    ]
    if imported.requests:
        lines.extend(f"  - {item}" for item in imported.requests[:12])
    else:
        lines.append("  - none surfaced")
    lines.append("- note: imported session requests are captured here before manual promotion into `cart todo`.")
    note.body = _upsert_managed_section(
        note.body,
        f"session-import-{imported.note_slug}",
        f"Imported Session {imported.source_id}",
        "\n".join(lines),
    )
    existing_links = note.frontmatter.get("links", [])
    link_values = [str(item) for item in existing_links if isinstance(item, str)]
    note.frontmatter["links"] = _unique(link_values + [session_note.stem] + imported.projects + imported.entities)
    note.write()
    return note.path


def import_session(root: Path, source_type: str, path: Path) -> dict[str, Any]:
    imported = parse_session_file(source_type, path)
    session_note = _update_session_note(root, imported)
    summary_note = _update_agent_summary(root, imported, session_note)
    daily_note = _update_daily_surface(root, imported, session_note)
    task_surface = _update_task_surface(root, imported, session_note)
    project_paths = _update_project_surfaces(root, imported, session_note)
    entity_paths = _update_entity_surfaces(root, imported, session_note)
    written = [session_note, summary_note, daily_note, task_surface] + project_paths + entity_paths
    return {
        "source": str(path),
        "agent": imported.agent,
        "session_note": str(session_note),
        "written": [str(item) for item in written],
        "projects": imported.projects,
        "entities": imported.entities,
        "request_count": len(imported.requests),
        "summary": imported.summary,
    }


def import_sessions(root: Path, source_type: str, paths: list[Path]) -> dict[str, Any]:
    imported_results: list[dict[str, Any]] = []
    written: list[str] = []
    for path in paths:
        result = import_session(root, source_type, path)
        imported_results.append(result)
        written.extend(result["written"])
    return {
        "count": len(imported_results),
        "written": _unique(written),
        "sessions": imported_results,
    }
