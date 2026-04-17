from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader


TEMPLATE_FILES = {
    "note": "note.md.j2",
    "daily": "daily.md.j2",
    "project": "project.md.j2",
    "task": "task.md.j2",
    "agent-log": "agent-log.md.j2",
    "ref": "note.md.j2",
    "entity": "note.md.j2",
}

BUILTIN_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "jinja"


def atlas_template_dir(atlas_root: Path) -> Path:
    return atlas_root / ".cartographer" / "templates"


def template_filename(note_type: str) -> str:
    return TEMPLATE_FILES.get(note_type, TEMPLATE_FILES["note"])


def render_template(
    note_type: str,
    context: dict[str, Any],
    *,
    atlas_root: Path | None = None,
) -> str:
    search_paths = []
    if atlas_root is not None:
        search_paths.append(str(atlas_template_dir(atlas_root)))
    search_paths.append(str(BUILTIN_TEMPLATE_DIR))
    environment = Environment(
        loader=FileSystemLoader(search_paths),
        keep_trailing_newline=True,
    )
    template = environment.get_template(template_filename(note_type))
    rendered = template.render(**context)
    if not rendered.endswith("\n"):
        rendered += "\n"
    return rendered


def sync_builtin_templates(atlas_root: Path) -> list[Path]:
    target_dir = atlas_template_dir(atlas_root)
    target_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for source in sorted(BUILTIN_TEMPLATE_DIR.glob("*.j2")):
        target = target_dir / source.name
        if target.exists():
            continue
        shutil.copy2(source, target)
        written.append(target)
    return written
