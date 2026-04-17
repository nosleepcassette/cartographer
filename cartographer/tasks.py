from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .blocks import BLOCK_PATTERN, generate_block_id, parse_block_attrs
from .notes import Note


TASK_CHECKBOX_PATTERN = re.compile(r"^- \[(?P<done>[ xX])\] (?P<text>.+)$")
TASK_ATTR_PATTERN = re.compile(r"^\s{2,}(?P<key>[A-Za-z0-9_-]+):\s*(?P<value>.+)$")
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


@dataclass(slots=True)
class Task:
    id: str
    path: Path
    text: str
    status: str = "open"
    priority: str = "P2"
    project: str | None = None
    due: str | None = None
    done: bool = False

    @property
    def priority_rank(self) -> int:
        return PRIORITY_ORDER.get(self.priority, 99)


def task_dir(atlas_root: Path) -> Path:
    return atlas_root / "tasks"


def task_files(atlas_root: Path) -> list[Path]:
    directory = task_dir(atlas_root)
    if not directory.exists():
        return []
    return sorted(directory.rglob("*.md"))


def _parse_task_block(
    path: Path, block_id: str, attrs: dict[str, str], content: str
) -> Task | None:
    lines = [line.rstrip() for line in content.strip().splitlines() if line.strip()]
    if not lines:
        return None
    checkbox = TASK_CHECKBOX_PATTERN.match(lines[0].strip())
    if checkbox is None:
        return None
    metadata: dict[str, str] = {}
    for line in lines[1:]:
        match = TASK_ATTR_PATTERN.match(line)
        if match:
            metadata[match.group("key")] = match.group("value")
    done = checkbox.group("done").lower() == "x"
    status = metadata.get("status", "done" if done else "open")
    return Task(
        id=block_id,
        path=path,
        text=checkbox.group("text").strip(),
        status=status,
        priority=metadata.get("priority", "P2"),
        project=metadata.get("project"),
        due=metadata.get("due"),
        done=done or status == "done",
    )


def parse_tasks_in_file(path: Path) -> list[Task]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    tasks: list[Task] = []
    for match in BLOCK_PATTERN.finditer(text):
        attrs = parse_block_attrs(match.group("attrs"))
        if attrs.get("type") != "task":
            continue
        task = _parse_task_block(path, match.group("id"), attrs, match.group("content"))
        if task is not None:
            tasks.append(task)
    return tasks


def iter_tasks(atlas_root: Path, *, include_done: bool = True) -> list[Task]:
    items: list[Task] = []
    for path in task_files(atlas_root):
        for task in parse_tasks_in_file(path):
            if include_done or not task.done:
                items.append(task)
    return items


def sort_tasks(tasks: list[Task]) -> list[Task]:
    return sorted(
        tasks,
        key=lambda task: (
            task.priority_rank,
            task.due or "9999-12-31",
            task.text.lower(),
        ),
    )


def ensure_active_task_file(atlas_root: Path) -> Path:
    path = task_dir(atlas_root) / "active.md"
    if path.exists():
        return path
    today = date.today().isoformat()
    note = Note(
        path=path,
        frontmatter={
            "id": "tasks-active",
            "title": "Active Tasks",
            "type": "task-list",
            "created": today,
            "modified": today,
        },
        body="# Tasks\n",
    )
    note.write()
    return path


def append_task(
    atlas_root: Path,
    text: str,
    *,
    priority: str = "P2",
    project: str | None = None,
    due: str | None = None,
) -> Task:
    path = ensure_active_task_file(atlas_root)
    note = Note.from_file(path)
    task_id = generate_block_id("t")
    block_lines = [
        f'<!-- cart:block id="{task_id}" type="task" -->',
        f"- [ ] {text}",
        "  status: open",
        f"  priority: {priority}",
    ]
    if project:
        block_lines.append(f"  project: {project}")
    if due:
        block_lines.append(f"  due: {due}")
    block_lines.append("<!-- /cart:block -->")
    note.body = note.body.rstrip() + "\n\n" + "\n".join(block_lines) + "\n"
    note.frontmatter["modified"] = date.today().isoformat()
    note.write()
    created = next(task for task in parse_tasks_in_file(path) if task.id == task_id)
    return created


def mark_done(atlas_root: Path, task_id: str) -> Task:
    for path in task_files(atlas_root):
        note = Note.from_file(path)
        changed = False

        def replace_block(match: re.Match[str]) -> str:
            nonlocal changed
            if match.group("id") != task_id:
                return match.group(0)
            attrs = match.group("attrs")
            lines = [
                line.rstrip() for line in match.group("content").strip().splitlines()
            ]
            updated_lines: list[str] = []
            status_updated = False
            for index, line in enumerate(lines):
                stripped = line.strip()
                if index == 0:
                    checkbox = TASK_CHECKBOX_PATTERN.match(stripped)
                    if checkbox:
                        updated_lines.append(f"- [x] {checkbox.group('text')}")
                        continue
                attr_match = TASK_ATTR_PATTERN.match(line)
                if attr_match and attr_match.group("key") == "status":
                    updated_lines.append("  status: done")
                    status_updated = True
                    continue
                updated_lines.append(line)
            if not status_updated:
                updated_lines.append("  status: done")
            changed = True
            return (
                f'<!-- cart:block id="{task_id}"{attrs} -->\n'
                + "\n".join(updated_lines)
                + "\n<!-- /cart:block -->"
            )

        note.body = BLOCK_PATTERN.sub(replace_block, note.body)
        if not changed:
            continue
        note.frontmatter["modified"] = date.today().isoformat()
        note.write()
        task = next(task for task in parse_tasks_in_file(path) if task.id == task_id)
        _write_mapsos_hint(atlas_root, task)
        return task
    raise FileNotFoundError(f"task not found: {task_id}")


def _write_mapsos_hint(atlas_root: Path, task: Task) -> None:
    if not task.project:
        return
    hints_dir = atlas_root / ".cartographer" / "mapsos-hints"
    hints_dir.mkdir(parents=True, exist_ok=True)
    hint_file = hints_dir / f"{task.id}.json"
    import json as _json

    hint_file.write_text(
        _json.dumps(
            {
                "task_id": task.id,
                "project": task.project,
                "completed": task.done,
                "completed_at": date.today().isoformat(),
            }
        ),
        encoding="utf-8",
    )


def query_tasks(atlas_root: Path, expression: str) -> list[Task]:
    tasks = iter_tasks(atlas_root, include_done=True)
    tokens = shlex.split(expression) if expression else []
    for token in tokens:
        if token.startswith("project:"):
            value = token.partition(":")[2]
            tasks = [task for task in tasks if task.project == value]
        elif token.startswith("priority:"):
            value = token.partition(":")[2].upper()
            tasks = [task for task in tasks if task.priority.upper() == value]
        elif token.startswith("status:"):
            value = token.partition(":")[2]
            tasks = [task for task in tasks if task.status == value]
        elif token.startswith("due:"):
            value = token.partition(":")[2]
            tasks = [task for task in tasks if task.due == value]
        elif token.startswith("text:"):
            value = token.partition(":")[2].lower()
            tasks = [task for task in tasks if value in task.text.lower()]
        else:
            value = token.lower()
            tasks = [task for task in tasks if value in task.text.lower()]
    return sort_tasks(tasks)


def summarize_tasks(atlas_root: Path) -> dict[str, object]:
    open_tasks = iter_tasks(atlas_root, include_done=False)
    by_priority = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    for task in open_tasks:
        if task.priority in by_priority:
            by_priority[task.priority] += 1
    return {"open": len(open_tasks), "by_priority": by_priority}
