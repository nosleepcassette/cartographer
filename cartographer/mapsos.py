from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .notes import Note
from .tasks import parse_tasks_in_file
from .templates import render_template


MAPSOS_SECTION_START = "<!-- cart:mapsos start -->"
MAPSOS_SECTION_END = "<!-- cart:mapsos end -->"


@dataclass(slots=True)
class MapsOSTask:
    title: str
    source_id: str
    status: str = "open"
    priority: str = "P2"
    arc: str | None = None
    due: str | None = None
    notes: str | None = None

    @property
    def done(self) -> bool:
        return self.status == "done"


def _today_string() -> str:
    return date.today().isoformat()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "mapsos"


def _stable_task_id(task: MapsOSTask) -> str:
    key = f"{task.source_id}|{task.title}|{task.arc or ''}"
    return "m" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]


def _extract_date(payload: dict[str, Any]) -> str:
    candidates = [
        payload.get("date"),
        payload.get("day"),
        payload.get("session_date"),
    ]
    session = payload.get("session")
    if isinstance(session, dict):
        candidates.extend(
            [
                session.get("date"),
                session.get("day"),
                session.get("session_date"),
            ]
        )
    for candidate in candidates:
        if isinstance(candidate, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", candidate.strip()):
            return candidate.strip()
    return _today_string()


def _coerce_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _extract_string(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _extract_summary(payload: dict[str, Any]) -> str:
    candidates: list[str] = []
    for key in ("summary", "notes", "journal", "briefing"):
        value = _extract_string(payload.get(key))
        if value:
            candidates.append(value)
    session = payload.get("session")
    if isinstance(session, dict):
        for key in ("summary", "notes", "journal", "briefing"):
            value = _extract_string(session.get(key))
            if value:
                candidates.append(value)
    return candidates[0] if candidates else "No session summary provided."


def _normalize_label(item: Any) -> str | None:
    if isinstance(item, str):
        return item.strip() or None
    if isinstance(item, dict):
        for key in ("label", "name", "title", "id", "arc"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _normalize_priority(value: Any) -> str:
    if isinstance(value, str):
        normalized = value.strip().upper()
        if normalized in {"P0", "P1", "P2", "P3"}:
            return normalized
        if normalized in {"URGENT", "CRITICAL", "NOW"}:
            return "P0"
        if normalized in {"HIGH", "H1"}:
            return "P1"
        if normalized in {"MEDIUM", "NORMAL", "DEFAULT", "P2"}:
            return "P2"
        if normalized in {"LOW", "SOMEDAY", "P3"}:
            return "P3"
        if normalized.isdigit():
            number = int(normalized)
            if number <= 0:
                return "P0"
            if number == 1:
                return "P1"
            if number == 2:
                return "P2"
            return "P3"
    if isinstance(value, (int, float)):
        if value <= 0:
            return "P0"
        if value <= 1:
            return "P1"
        if value <= 2:
            return "P2"
        return "P3"
    return "P2"


def _normalize_status(raw_task: dict[str, Any]) -> str:
    status = _extract_string(raw_task.get("status"))
    if status:
        normalized = status.lower()
        if normalized in {"done", "completed", "complete", "closed"}:
            return "done"
        if normalized in {"open", "todo", "pending", "active", "in_progress", "in-progress"}:
            return "open"
    if bool(raw_task.get("done")) or bool(raw_task.get("completed")):
        return "done"
    return "open"


def _task_from_item(item: Any, index: int, *, arc_hint: str | None = None) -> MapsOSTask | None:
    if isinstance(item, str):
        title = item.strip()
        if not title:
            return None
        return MapsOSTask(
            title=title,
            source_id=f"task-{index}",
            arc=arc_hint,
        )
    if not isinstance(item, dict):
        return None
    title = None
    for key in ("title", "text", "name", "task"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            title = value.strip()
            break
    if title is None:
        return None
    source_id = None
    for key in ("id", "uuid", "task_id", "slug"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            source_id = value.strip()
            break
    if source_id is None:
        source_id = f"task-{index}-{_slugify(title)}"
    arc = arc_hint
    if arc is None:
        for key in ("arc", "project", "track"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                arc = value.strip()
                break
    due = None
    due_value = item.get("due") or item.get("due_date")
    if isinstance(due_value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", due_value.strip()):
        due = due_value.strip()
    return MapsOSTask(
        title=title,
        source_id=source_id,
        status=_normalize_status(item),
        priority=_normalize_priority(item.get("priority")),
        arc=arc,
        due=due,
        notes=_extract_string(item.get("notes") or item.get("summary")),
    )


def _iter_mapsos_task_items(payload: dict[str, Any]) -> list[tuple[Any, str | None]]:
    items: list[tuple[Any, str | None]] = []

    def collect(container: dict[str, Any]) -> None:
        for key in ("tasks", "arc_tasks", "todo"):
            value = container.get(key)
            if value is not None:
                items.extend((entry, None) for entry in _coerce_list(value))
        arcs_value = container.get("arcs")
        if arcs_value is None:
            return
        for arc_entry in _coerce_list(arcs_value):
            if not isinstance(arc_entry, dict):
                continue
            arc_label = _normalize_label(arc_entry)
            for key in ("tasks", "todo", "items"):
                value = arc_entry.get(key)
                if value is not None:
                    items.extend((entry, arc_label) for entry in _coerce_list(value))

    collect(payload)
    session = payload.get("session")
    if isinstance(session, dict):
        collect(session)
    return items


def normalize_mapsos_tasks(payload: dict[str, Any]) -> list[MapsOSTask]:
    tasks: list[MapsOSTask] = []
    for index, (item, arc_hint) in enumerate(_iter_mapsos_task_items(payload), start=1):
        task = _task_from_item(item, index, arc_hint=arc_hint)
        if task is None:
            continue
        tasks.append(task)
    return tasks


def _extract_state(payload: dict[str, Any]) -> str | None:
    for key in ("state", "mood", "current_state"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    session = payload.get("session")
    if isinstance(session, dict):
        for key in ("state", "mood", "current_state"):
            value = session.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _extract_labels(payload: dict[str, Any], *keys: str) -> list[str]:
    labels: list[str] = []
    for key in keys:
        value = payload.get(key)
        for item in _coerce_list(value):
            label = _normalize_label(item)
            if label:
                labels.append(label)
    session = payload.get("session")
    if isinstance(session, dict):
        for key in keys:
            value = session.get(key)
            for item in _coerce_list(value):
                label = _normalize_label(item)
                if label:
                    labels.append(label)
    return list(dict.fromkeys(labels))


def _ensure_daily_note(root: Path, day: str) -> Note:
    path = root / "daily" / f"{day}.md"
    if not path.exists():
        content = render_template(
            "daily",
            {
                "id": f"daily-{day}",
                "title": day,
                "date": day,
                "yesterday": None,
            },
            atlas_root=root,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return Note.from_file(path)


def _upsert_mapsos_section(body: str, section: str) -> str:
    payload = f"{MAPSOS_SECTION_START}\n{section.rstrip()}\n{MAPSOS_SECTION_END}"
    if MAPSOS_SECTION_START in body and MAPSOS_SECTION_END in body:
        pattern = re.compile(
            re.escape(MAPSOS_SECTION_START) + r".*?" + re.escape(MAPSOS_SECTION_END),
            re.DOTALL,
        )
        return pattern.sub(payload, body, count=1).rstrip() + "\n"
    return body.rstrip() + "\n\n## mapsOS\n\n" + payload + "\n"


def _render_daily_section(payload: dict[str, Any], tasks: list[MapsOSTask]) -> str:
    lines = []
    state = _extract_state(payload)
    if state:
        lines.append(f"- state: {state}")
    arcs = _extract_labels(payload, "arcs")
    if arcs:
        lines.append(f"- arcs: {', '.join(arcs)}")
    intentions = _extract_labels(payload, "intentions")
    if intentions:
        lines.append(f"- intentions: {', '.join(intentions)}")
    summary = _extract_summary(payload)
    task_lines = [
        f"- [{'x' if task.done else ' '}] {task.title} ({task.priority}{', ' + task.arc if task.arc else ''})"
        for task in tasks[:8]
    ]
    body = [
        "### state",
        "\n".join(lines) if lines else "- no state data",
        "",
        "### session",
        summary,
        "",
        "### tasks",
        "\n".join(task_lines) if task_lines else "- no exported tasks",
    ]
    return "\n".join(body).rstrip()


def _render_tasks_note(day: str, tasks: list[MapsOSTask]) -> Note:
    body_lines = [
        "# mapsOS Tasks",
        "",
        f"_Synced from mapsOS on {day}._",
    ]
    if tasks:
        body_lines.append("")
    else:
        body_lines.extend(["", "- no tasks exported"])
    for task in tasks:
        attrs = ['type="task"', 'source="mapsos"', f'source_id="{task.source_id}"']
        if task.arc:
            attrs.append(f'arc="{_slugify(task.arc)}"')
        body_lines.extend(
            [
                f'<!-- cart:block id="{_stable_task_id(task)}" {" ".join(attrs)} -->',
                f"- [{'x' if task.done else ' '}] {task.title}",
                f"  status: {task.status}",
                f"  priority: {task.priority}",
            ]
        )
        if task.arc:
            body_lines.append(f"  project: {_slugify(task.arc)}")
            body_lines.append(f"  arc: {task.arc}")
        if task.due:
            body_lines.append(f"  due: {task.due}")
        body_lines.append(f"  mapsos_id: {task.source_id}")
        if task.notes:
            body_lines.append(f"  notes: {task.notes}")
        body_lines.append("<!-- /cart:block -->")
        body_lines.append("")
    return Note(
        path=Path("tasks") / "mapsos.md",
        frontmatter={
            "id": "tasks-mapsos",
            "title": "mapsOS Tasks",
            "type": "task-list",
            "source": "mapsOS",
            "created": day,
            "modified": day,
        },
        body="\n".join(body_lines).rstrip() + "\n",
    )


def _render_snapshot_note(day: str, payload: dict[str, Any], tasks: list[MapsOSTask]) -> Note:
    state = _extract_state(payload) or "unknown"
    arcs = _extract_labels(payload, "arcs")
    intentions = _extract_labels(payload, "intentions")
    task_lines = [
        f"- [{'x' if task.done else ' '}] {task.title} ({task.priority})"
        for task in tasks
    ] or ["- no exported tasks"]
    body = (
        f"# mapsOS snapshot {day}\n\n"
        "## summary\n\n"
        f"{_extract_summary(payload)}\n\n"
        "## state\n\n"
        f"- state: {state}\n"
        f"- arcs: {', '.join(arcs) if arcs else 'none'}\n"
        f"- intentions: {', '.join(intentions) if intentions else 'none'}\n\n"
        "## tasks\n\n"
        + "\n".join(task_lines)
        + "\n\n## raw\n\n```json\n"
        + json.dumps(payload, indent=2, ensure_ascii=True)
        + "\n```\n"
    )
    return Note(
        path=Path("agents") / "mapsOS" / f"{day}.md",
        frontmatter={
            "id": f"mapsos-{day}",
            "title": f"mapsOS snapshot {day}",
            "type": "agent-log",
            "agent": "mapsOS",
            "source": "mapsOS",
            "created": day,
            "modified": day,
            "auto_blocks": True,
            "tags": ["mapsOS", "snapshot"],
        },
        body=body,
    )


def sync_mapsos_payload(
    root: Path,
    payload: dict[str, Any],
    *,
    sync_daily: bool = True,
    sync_tasks: bool = True,
    sync_snapshot: bool = True,
) -> dict[str, Any]:
    day = _extract_date(payload)
    tasks = normalize_mapsos_tasks(payload)
    written: list[Path] = []

    if sync_daily:
        daily_note = _ensure_daily_note(root, day)
        daily_note.body = _upsert_mapsos_section(daily_note.body, _render_daily_section(payload, tasks))
        daily_note.frontmatter["modified"] = _today_string()
        daily_note.write(ensure_blocks=True)
        written.append(daily_note.path)

    if sync_tasks:
        tasks_note = _render_tasks_note(day, tasks)
        tasks_note.path = root / tasks_note.path
        tasks_note.write()
        written.append(tasks_note.path)

    if sync_snapshot:
        snapshot_note = _render_snapshot_note(day, payload, tasks)
        snapshot_note.path = root / snapshot_note.path
        snapshot_note.write(ensure_blocks=True)
        written.append(snapshot_note.path)

    open_tasks = [task for task in tasks if not task.done]
    return {
        "date": day,
        "paths": [str(path) for path in written],
        "task_count": len(tasks),
        "open_task_count": len(open_tasks),
        "output": (
            f"mapsOS ingest {day}: wrote {len(written)} files, "
            f"{len(tasks)} tasks ({len(open_tasks)} open)"
        ),
    }


def load_mapsos_payload(source: str, stdin_text: str | None = None) -> dict[str, Any]:
    if source == "-":
        raw = stdin_text or ""
    else:
        raw = Path(source).expanduser().read_text(encoding="utf-8")
    decoded = json.loads(raw)
    if isinstance(decoded, list):
        return {"tasks": decoded}
    if not isinstance(decoded, dict):
        raise ValueError("mapsOS payload must decode to a JSON object or array")
    return decoded


def synced_mapsos_tasks(root: Path) -> list[Any]:
    path = root / "tasks" / "mapsos.md"
    if not path.exists():
        return []
    return parse_tasks_in_file(path)
