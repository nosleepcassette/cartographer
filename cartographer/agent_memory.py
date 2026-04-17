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
    confidence_label: str | None = None
    confirmed: int = 0
    rejected: int = 0
    source: str = "manual"
    source_session: str | None = None
    source_agent: str | None = None
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


def master_summary_path(root: Path) -> Path:
    return root / "agents" / "MASTER_SUMMARY.md"


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
    note_id: str | None = None,
    heading: str | None = None,
    body: str | None = None,
) -> Note:
    if relative_path in overlay:
        return _load_note_from_text(root / relative_path, overlay[relative_path])
    path = root / relative_path
    if path.exists():
        return Note.from_file(path)
    today = today_string()
    frontmatter: dict[str, Any] = {
        "id": note_id or slugify(Path(relative_path).stem),
        "title": title,
        "type": note_type,
        "created": today,
        "modified": today,
    }
    if extra_frontmatter:
        frontmatter.update(extra_frontmatter)
    return Note(path=path, frontmatter=frontmatter, body=body or f"# {heading or title}\n")


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
        confidence_label=None if item.get("confidence_label") is None else str(item["confidence_label"]),
        confirmed=confirmed_value,
        rejected=int(item.get("rejected", 0) or 0),
        source=str(item.get("source") or default_source),
        source_session=None if item.get("source_session") is None else str(item["source_session"]),
        source_agent=None if item.get("source_agent") is None else str(item["source_agent"]),
        date=str(item.get("date") or item_date),
        entity=None if item.get("entity") is None else str(item["entity"]),
    )


def extract_source_session_id(session_data: Any, *, fallback: str) -> str:
    if isinstance(session_data, dict):
        for key in ("session_id", "id", "uuid"):
            value = session_data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return fallback


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
    source_agent = item.source_agent or agent
    for match in BLOCK_PATTERN.finditer(note.body):
        attrs = parse_block_attrs(match.group("attrs"))
        if attrs.get("type") != "learning":
            continue
        if match.group("content").strip() != item.text.strip():
            continue
        if (attrs.get("source_session") or "") != (item.source_session or ""):
            continue
        if (attrs.get("source_agent") or source_agent) != source_agent:
            continue
        return relative_path
    block = render_attr_block(
        generate_block_id("l"),
        item.text,
        {
            "type": "learning",
            "confidence": f"{item.confidence:.2f}",
            "confidence_label": item.confidence_label,
            "source": item.source,
            "source_session": item.source_session,
            "source_agent": source_agent,
            "date": item.date,
            "confirmed": str(item.confirmed),
            "rejected": str(item.rejected),
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
    summary_id = f"{slugify(agent)}-summary"
    note = _ensure_note(
        root,
        relative_path,
        overlay,
        title=f"{agent} summary",
        note_type="agent-summary",
        note_id=summary_id,
        extra_frontmatter={"agent": agent, "tags": [agent, "summary"]},
    )
    note.frontmatter["id"] = summary_id
    note.frontmatter["agent"] = agent
    note.frontmatter["type"] = "agent-summary"
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


def _default_master_summary_body() -> str:
    return (
        "# maps — master context\n\n"
        "## identity\n\n"
        "## current situation\n\n"
        "## active projects\n\n"
        "## technical stack\n\n"
        "## preferences + patterns\n\n"
        "## open questions\n\n"
        "## recent decisions\n\n"
        "## agent notes\n"
    )


def update_master_summary_overlay(
    root: Path,
    overlay: dict[str, str],
    *,
    contributing_agent: str | None = None,
    generated_by: str | None = None,
) -> str:
    relative_path = str(Path("agents") / "MASTER_SUMMARY.md")
    note = _ensure_note(
        root,
        relative_path,
        overlay,
        title="Master Summary",
        note_type="master-summary",
        note_id="master-summary",
        extra_frontmatter={
            "updated": today_string(),
            "version": 1,
            "contributing_agents": [],
            "generated_by": generated_by or "hermes",
        },
        heading="maps — master context",
        body=_default_master_summary_body(),
    )
    note.frontmatter["id"] = "master-summary"
    note.frontmatter.setdefault("title", "Master Summary")
    note.frontmatter["type"] = "master-summary"
    note.frontmatter.setdefault("version", 1)
    note.frontmatter.setdefault("created", today_string())
    note.frontmatter["updated"] = today_string()
    if generated_by and not note.frontmatter.get("generated_by"):
        note.frontmatter["generated_by"] = generated_by

    raw_agents = note.frontmatter.get("contributing_agents", [])
    contributing_agents = [
        str(agent_name).strip()
        for agent_name in raw_agents
        if isinstance(agent_name, str) and str(agent_name).strip()
    ] if isinstance(raw_agents, list) else []
    if contributing_agent and contributing_agent not in contributing_agents:
        contributing_agents.append(contributing_agent)
    contributing_agents = sorted(dict.fromkeys(contributing_agents))
    note.frontmatter["contributing_agents"] = contributing_agents
    note.frontmatter["links"] = [f"{slugify(agent_name)}-summary" for agent_name in contributing_agents]
    if not note.body.strip():
        note.body = _default_master_summary_body()
    _set_overlay(root, relative_path, note, overlay)
    return relative_path


def ensure_master_summary_note(root: Path) -> Path:
    overlay: dict[str, str] = {}
    relative_path = update_master_summary_overlay(root, overlay)
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(overlay[relative_path], encoding="utf-8")
    return path


def build_agent_ingest_result(root: Path, agent: str, source_path: str, session_data: Any) -> dict[str, Any]:
    learnings = extract_learning_items(session_data, source=f"{agent}-session")
    session_reference_hint = extract_source_session_id(session_data, fallback=Path(source_path).stem)
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
        item.source_agent = agent
        item.source_session = session_reference_hint
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
    update_master_summary_overlay(
        root,
        overlay,
        contributing_agent=agent,
        generated_by="hermes" if agent == "hermes" else agent,
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
    source_session: str | None = None,
    source_agent: str | None = None,
    confidence_label: str | None = None,
    learned_on: str | None = None,
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
            confidence_label=confidence_label,
            source=source,
            confirmed=confirmed,
            date=learned_on or today_string(),
            entity=entity,
            source_session=source_session,
            source_agent=source_agent or agent,
        ),
    )
    return {"writes": [{"path": path, "content": content} for path, content in overlay.items()]}


@dataclass(slots=True)
class LearningBlockInfo:
    path: Path
    block_id: str
    content: str
    attrs: dict[str, str]

    @property
    def agent(self) -> str:
        try:
            return self.path.parts[-3]
        except IndexError:
            return ""

    @property
    def topic(self) -> str:
        return self.path.stem


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


def pending_learning_blocks(root: Path, *, agent: str | None = None) -> list[LearningBlockInfo]:
    return [
        item
        for item in iter_learning_blocks(root, agent=agent)
        if item.attrs.get("confirmed") != "1" and item.attrs.get("rejected") != "1"
    ]


def _rewrite_learning_blocks(
    root: Path,
    *,
    agent: str | None,
    predicate: Any,
    mutate: Any,
) -> dict[str, Any]:
    target_paths = sorted((root / "agents").glob("*/learnings/*.md")) if agent is None else sorted(learnings_dir(root, agent).glob("*.md"))
    writes: list[dict[str, str]] = []
    changed_blocks = 0
    for path in target_paths:
        text = path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(text)
        changed = False

        def replace(match: re.Match[str]) -> str:
            nonlocal changed, changed_blocks
            attrs = parse_block_attrs(match.group("attrs"))
            content = match.group("content").strip()
            info = LearningBlockInfo(path=path, block_id=match.group("id"), content=content, attrs=attrs)
            if attrs.get("type") != "learning" or not predicate(info):
                return match.group(0)
            updated_attrs = mutate(dict(attrs))
            changed = True
            changed_blocks += 1
            return render_attr_block(match.group("id"), content, updated_attrs)

        new_body = BLOCK_PATTERN.sub(replace, body)
        if not changed:
            continue
        note = Note(path=path, frontmatter=frontmatter, body=new_body)
        writes.append(
            {
                "path": str(path.relative_to(root)),
                "content": render(note.frontmatter, note.body),
            }
        )
    return {"writes": writes, "updated": changed_blocks}


def confirm_learnings(
    root: Path,
    *,
    topic: str | None = None,
    block_id: str | None = None,
    agent: str | None = None,
) -> dict[str, Any]:
    if topic is None and block_id is None:
        raise ValueError("confirm requires a topic or --block id")
    normalized_topic = None if topic is None else slugify(topic)
    return _rewrite_learning_blocks(
        root,
        agent=agent,
        predicate=lambda info: (
            (block_id is not None and info.block_id == block_id)
            or (normalized_topic is not None and info.topic == normalized_topic)
        ),
        mutate=lambda attrs: {
            **attrs,
            "confirmed": "1",
            "rejected": "0",
            "confidence": "1.00",
            "confidence_label": "confirmed",
        },
    )


def reject_learnings(
    root: Path,
    *,
    topic: str | None = None,
    block_id: str | None = None,
    agent: str | None = None,
) -> dict[str, Any]:
    if topic is None and block_id is None:
        raise ValueError("reject requires a topic or --block id")
    normalized_topic = None if topic is None else slugify(topic)
    return _rewrite_learning_blocks(
        root,
        agent=agent,
        predicate=lambda info: (
            (block_id is not None and info.block_id == block_id)
            or (normalized_topic is not None and info.topic == normalized_topic)
        ),
        mutate=lambda attrs: {
            **attrs,
            "confirmed": "0",
            "rejected": "1",
            "confidence": "0.00",
            "confidence_label": "rejected",
        },
    )


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
            if attrs.get("rejected") == "1":
                removed += 1
                changed = True
                return ""
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
