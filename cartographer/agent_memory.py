from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .blocks import BLOCK_PATTERN, generate_block_id, parse_block_attrs
from .notes import Note, parse_frontmatter, render


@dataclass(slots=True)
class LearningItem:
    topic: str
    text: str
    confidence: float = 0.85
    confirmed: int = 0
    source: str = "manual"
    date: str = ""
    entity: str | None = None


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "note"


def today_string() -> str:
    return date.today().isoformat()


def agent_root(root: Path, agent: str) -> Path:
    return root / "agents" / agent


def session_dir(root: Path, agent: str) -> Path:
    return agent_root(root, agent) / "sessions"


def learnings_dir(root: Path, agent: str) -> Path:
    return agent_root(root, agent) / "learnings"


def summary_path(root: Path, agent: str) -> Path:
    return agent_root(root, agent) / "SUMMARY.md"


def _load_note_from_text(path: Path, text: str) -> Note:
    frontmatter, body = parse_frontmatter(text)
    return Note(path=path, frontmatter=frontmatter, body=body)


def _ensure_note(
    root: Path,
    relative_path: str,
    overlay: dict[str, str],
    *,
    title: str,
    note_type: str,
    extra_frontmatter: dict[str, Any] | None = None,
    heading: str | None = None,
) -> Note:
    if relative_path in overlay:
        return _load_note_from_text(root / relative_path, overlay[relative_path])
    path = root / relative_path
    if path.exists():
        return Note.from_file(path)
    today = today_string()
    frontmatter: dict[str, Any] = {
        "id": slugify(Path(relative_path).stem),
        "title": title,
        "type": note_type,
        "created": today,
        "modified": today,
    }
    if extra_frontmatter:
        frontmatter.update(extra_frontmatter)
    body = f"# {heading or title}\n"
    return Note(path=path, frontmatter=frontmatter, body=body)


def _set_overlay(root: Path, relative_path: str, note: Note, overlay: dict[str, str]) -> None:
    note.frontmatter["modified"] = today_string()
    overlay[relative_path] = render(note.frontmatter, note.body)


def render_attr_block(block_id: str, content: str, attrs: dict[str, Any]) -> str:
    attr_text = "".join(
        f' {key}="{value}"'
        for key, value in attrs.items()
        if key != "id" and value is not None
    )
    return (
        f'<!-- cart:block id="{block_id}"{attr_text} -->\n'
        f"{content.strip()}\n"
        "<!-- /cart:block -->"
    )


def normalize_learning_item(
    item: str | dict[str, Any],
    *,
    default_topic: str = "general",
    default_source: str = "manual",
    default_date: str | None = None,
) -> LearningItem | None:
    item_date = default_date or today_string()
    if isinstance(item, str):
        text = item.strip()
        return None if not text else LearningItem(topic=default_topic, text=text, source=default_source, date=item_date)
    text = (
        item.get("text")
        or item.get("fact")
        or item.get("content")
        or item.get("learning")
        or item.get("summary")
    )
    if not text:
        return None
    confidence = item.get("confidence", 0.85)
    try:
        confidence_value = float(confidence)
    except (TypeError, ValueError):
        confidence_value = 0.85
    confirmed = item.get("confirmed", 0)
    try:
        confirmed_value = int(confirmed)
    except (TypeError, ValueError):
        confirmed_value = 0
    return LearningItem(
        topic=str(item.get("topic") or item.get("category") or default_topic),
        text=str(text).strip(),
        confidence=confidence_value,
        confirmed=confirmed_value,
        source=str(item.get("source") or default_source),
        date=str(item.get("date") or item_date),
        entity=None if item.get("entity") is None else str(item["entity"]),
    )


def extract_summary(session_data: Any) -> str:
    if isinstance(session_data, dict):
        for key in ("summary", "brief", "overview", "result"):
            value = session_data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        messages = session_data.get("messages")
        if isinstance(messages, list):
            for message in reversed(messages):
                if not isinstance(message, dict):
                    continue
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()[:600]
    if isinstance(session_data, list):
        for item in reversed(session_data):
            if isinstance(item, dict) and isinstance(item.get("content"), str):
                return str(item["content"]).strip()[:600]
    return "summary unavailable"


def extract_learning_items(session_data: Any, *, source: str) -> list[LearningItem]:
    items: list[LearningItem] = []
    item_date = today_string()
    if isinstance(session_data, dict):
        for key, topic in (("learnings", None), ("facts", "facts"), ("remember", "general")):
            value = session_data.get(key)
            if isinstance(value, list):
                for raw in value:
                    learning = normalize_learning_item(
                        raw,
                        default_topic=topic or "general",
                        default_source=source,
                        default_date=item_date,
                    )
                    if learning is not None:
                        items.append(learning)
            elif isinstance(value, str):
                learning = normalize_learning_item(
                    value,
                    default_topic=topic or "general",
                    default_source=source,
                    default_date=item_date,
                )
                if learning is not None:
                    items.append(learning)
    return items


def extract_entities(session_data: Any, learnings: list[LearningItem]) -> list[str]:
    entities: set[str] = set()
    if isinstance(session_data, dict):
        raw_entities = session_data.get("entities")
        if isinstance(raw_entities, list):
            for entry in raw_entities:
                if isinstance(entry, str) and entry.strip():
                    entities.add(entry.strip())
                elif isinstance(entry, dict):
                    name = entry.get("name") or entry.get("entity")
                    if isinstance(name, str) and name.strip():
                        entities.add(name.strip())
    for learning in learnings:
        if learning.entity:
            entities.add(learning.entity.strip())
    return sorted(entity for entity in entities if entity)


def next_session_relative_path(root: Path, agent: str, session_date: str) -> str:
    directory = session_dir(root, agent)
    directory.mkdir(parents=True, exist_ok=True)
    existing = sorted(directory.glob(f"{session_date}_*.md"))
    sequence = len(existing) + 1
    return str(Path("agents") / agent / "sessions" / f"{session_date}_{sequence:03d}.md")


def build_session_note_write(
    root: Path,
    agent: str,
    source_path: str,
    session_data: Any,
    learnings: list[LearningItem],
    entities: list[str],
) -> tuple[str, str]:
    session_date = today_string()
    relative_path = next_session_relative_path(root, agent, session_date)
    sequence = Path(relative_path).stem.split("_")[-1]
    session_id = f"{agent}-session-{session_date}_{sequence}"
    summary = extract_summary(session_data)
    links = [slugify(entity) for entity in entities]
    note = Note(
        path=root / relative_path,
        frontmatter={
            "id": session_id,
            "title": f"{agent} session {session_date}_{sequence}",
            "type": "agent-log",
            "agent": agent,
            "date": session_date,
            "source": source_path,
            "links": links,
            "tags": [agent, "session"],
            "created": session_date,
            "modified": session_date,
            "auto_blocks": True,
        },
        body=(
            f"# {agent} session {session_date}_{sequence}\n\n"
            "## summary\n\n"
            f"{summary}\n\n"
            "## learnings\n\n"
            + ("\n".join(f"- [{item.topic}] {item.text}" for item in learnings) if learnings else "- none extracted")
            + "\n\n## raw\n\n```json\n"
            + json.dumps(session_data, indent=2, ensure_ascii=True)
            + "\n```\n"
        ),
    )
    note.write(ensure_blocks=True)
    return relative_path, note.path.read_text(encoding="utf-8")


def append_learning_overlay(
    root: Path,
    overlay: dict[str, str],
    *,
    agent: str,
    item: LearningItem,
) -> str:
    relative_path = str(Path("agents") / agent / "learnings" / f"{slugify(item.topic)}.md")
    note = _ensure_note(
        root,
        relative_path,
        overlay,
        title=item.topic,
        note_type="learning-topic",
        extra_frontmatter={
            "agent": agent,
            "tags": [agent, "learning", slugify(item.topic)],
        },
    )
    block = render_attr_block(
        generate_block_id("l"),
        item.text,
        {
            "type": "learning",
            "confidence": f"{item.confidence:.2f}",
            "source": item.source,
            "date": item.date,
            "confirmed": str(item.confirmed),
            "entity": None if item.entity is None else slugify(item.entity),
        },
    )
    note.body = note.body.rstrip() + "\n\n" + block + "\n"
    _set_overlay(root, relative_path, note, overlay)
    return relative_path


def update_entity_overlay(
    root: Path,
    overlay: dict[str, str],
    *,
    entity_name: str,
    session_reference: str,
    summary: str,
    session_date: str,
) -> str:
    entity_slug = slugify(entity_name)
    relative_path = str(Path("entities") / f"{entity_slug}.md")
    note = _ensure_note(
        root,
        relative_path,
        overlay,
        title=entity_name,
        note_type="entity",
        extra_frontmatter={"tags": ["entity"], "links": []},
    )
    if "## sessions" not in note.body:
        note.body = note.body.rstrip() + "\n\n## sessions\n"
    session_line = f"- {session_date} — [[{Path(session_reference).stem}]] — {summary[:160]}"
    if session_line not in note.body:
        note.body = note.body.rstrip() + "\n" + session_line + "\n"
    _set_overlay(root, relative_path, note, overlay)
    return relative_path


def update_summary_overlay(
    root: Path,
    overlay: dict[str, str],
    *,
    agent: str,
    session_reference: str,
    summary_text: str,
    learnings: list[LearningItem],
) -> str:
    relative_path = str(Path("agents") / agent / "SUMMARY.md")
    note = _ensure_note(
        root,
        relative_path,
        overlay,
        title=f"{agent} summary",
        note_type="agent-summary",
        extra_frontmatter={"agent": agent, "tags": [agent, "summary"]},
    )
    sessions = sorted((session_dir(root, agent)).glob("*.md"))
    session_names = [path.stem for path in sessions[-4:]] + [Path(session_reference).stem]
    unique_session_names = list(dict.fromkeys(session_names))
    topic_preview = "\n".join(
        f"- {item.topic}: {item.text[:120]}" for item in learnings[:8]
    ) or "- no learnings yet"
    note.body = (
        f"# {agent} summary\n\n"
        "## latest\n\n"
        f"Source: [[{Path(session_reference).stem}]]\n\n"
        f"{summary_text}\n\n"
        "## recent learnings\n\n"
        f"{topic_preview}\n\n"
        "## recent sessions\n\n"
        + "\n".join(f"- [[{name}]]" for name in unique_session_names)
        + "\n"
    )
    _set_overlay(root, relative_path, note, overlay)
    return relative_path


def build_agent_ingest_result(root: Path, agent: str, source_path: str, session_data: Any) -> dict[str, Any]:
    learnings = extract_learning_items(session_data, source=f"{agent}-session")
    entities = extract_entities(session_data, learnings)
    session_reference, session_content = build_session_note_write(
        root,
        agent,
        source_path,
        session_data,
        learnings,
        entities,
    )
    overlay: dict[str, str] = {session_reference: session_content}
    summary_text = extract_summary(session_data)
    for item in learnings:
        append_learning_overlay(root, overlay, agent=agent, item=item)
    for entity_name in entities:
        update_entity_overlay(
            root,
            overlay,
            entity_name=entity_name,
            session_reference=session_reference,
            summary=summary_text,
            session_date=today_string(),
        )
    update_summary_overlay(
        root,
        overlay,
        agent=agent,
        session_reference=session_reference,
        summary_text=summary_text,
        learnings=learnings,
    )
    writes = [{"path": path, "content": content} for path, content in overlay.items()]
    return {
        "output": (
            f"ingested {source_path} -> {session_reference} "
            f"({len(learnings)} learnings, {len(entities)} entities)"
        ),
        "writes": writes,
        "errors": [],
    }


def append_learning(
    root: Path,
    *,
    agent: str,
    topic: str,
    text: str,
    confidence: float = 0.85,
    source: str = "manual",
    confirmed: int = 0,
    entity: str | None = None,
) -> dict[str, Any]:
    overlay: dict[str, str] = {}
    append_learning_overlay(
        root,
        overlay,
        agent=agent,
        item=LearningItem(
            topic=topic,
            text=text,
            confidence=confidence,
            source=source,
            confirmed=confirmed,
            date=today_string(),
            entity=entity,
        ),
    )
    return {"writes": [{"path": path, "content": content} for path, content in overlay.items()]}


@dataclass(slots=True)
class LearningBlockInfo:
    path: Path
    block_id: str
    content: str
    attrs: dict[str, str]


def iter_learning_blocks(root: Path, agent: str | None = None) -> list[LearningBlockInfo]:
    paths: list[Path] = []
    if agent is None:
        for learnings_path in (root / "agents").glob("*/learnings/*.md"):
            paths.append(learnings_path)
    else:
        paths.extend(sorted(learnings_dir(root, agent).glob("*.md")))
    items: list[LearningBlockInfo] = []
    for path in sorted(paths):
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        _, body = parse_frontmatter(text)
        for match in BLOCK_PATTERN.finditer(body):
            attrs = parse_block_attrs(match.group("attrs"))
            if attrs.get("type") != "learning":
                continue
            items.append(
                LearningBlockInfo(
                    path=path,
                    block_id=match.group("id"),
                    content=match.group("content").strip(),
                    attrs=attrs,
                )
            )
    return items


def decay_confidence(confidence: float, learned_on: str, confirmed: int) -> float:
    if confirmed > 0:
        return confidence
    try:
        learned_date = datetime.fromisoformat(learned_on).date()
    except ValueError:
        return confidence
    age_days = (date.today() - learned_date).days
    if age_days <= 30:
        return confidence
    extra_days = age_days - 30
    weeks = extra_days // 7
    return max(0.0, confidence - (0.05 * weeks))


def gc_learnings(root: Path, *, threshold: float, agent: str | None = None) -> dict[str, Any]:
    target_paths: list[Path] = []
    if agent is None:
        target_paths = sorted((root / "agents").glob("*/learnings/*.md"))
    else:
        target_paths = sorted(learnings_dir(root, agent).glob("*.md"))
    removed = 0
    updated = 0
    writes: list[dict[str, str]] = []
    for path in target_paths:
        text = path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(text)
        changed = False

        def replace(match: re.Match[str]) -> str:
            nonlocal removed, updated, changed
            attrs = parse_block_attrs(match.group("attrs"))
            if attrs.get("type") != "learning":
                return match.group(0)
            raw_confidence = attrs.get("confidence", "0.85")
            try:
                confidence = float(raw_confidence)
            except ValueError:
                confidence = 0.85
            try:
                confirmed = int(attrs.get("confirmed", "0"))
            except ValueError:
                confirmed = 0
            decayed = decay_confidence(confidence, attrs.get("date", today_string()), confirmed)
            if decayed < threshold:
                removed += 1
                changed = True
                return ""
            new_confidence = f"{decayed:.2f}"
            if new_confidence != raw_confidence:
                attrs["confidence"] = new_confidence
                updated += 1
                changed = True
            return render_attr_block(match.group("id"), match.group("content").strip(), attrs)

        new_body = BLOCK_PATTERN.sub(replace, body)
        if changed:
            note = Note(path=path, frontmatter=frontmatter, body=new_body)
            writes.append(
                {
                    "path": str(path.relative_to(root)),
                    "content": render(note.frontmatter, note.body),
                }
            )
    return {
        "writes": writes,
        "removed": removed,
        "updated": updated,
        "scanned_files": len(target_paths),
    }
