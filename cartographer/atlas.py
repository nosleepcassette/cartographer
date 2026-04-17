from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import tarfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import atlas_root, load_config, save_config
from .hooks import ensure_hook_dir
from .index import Index
from .notes import Note
from .obsidian import detect_vault
from .plugins import sync_builtin_plugins
from .tasks import summarize_tasks
from .templates import sync_builtin_templates, render_template
from .vimwiki import backup_vimwiki_assets, patch_vimrc
from .worklog import Worklog, record_operation


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "note"


def human_bytes(size: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    amount = float(size)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f}{unit}" if unit != "B" else f"{int(amount)}B"
        amount /= 1024
    return f"{size}B"


class Atlas:
    def __init__(self, root: str | Path | None = None):
        self.config = load_config(root=root)
        self.root = atlas_root(self.config)

    @property
    def meta_dir(self) -> Path:
        return self.root / ".cartographer"

    @property
    def config_path(self) -> Path:
        return self.meta_dir / "config.toml"

    @property
    def index_db_path(self) -> Path:
        return self.meta_dir / "index.db"

    @property
    def worklog_db_path(self) -> Path:
        return self.meta_dir / "worklog.db"

    def is_initialized(self) -> bool:
        return self.config_path.exists()

    def ensure_initialized(self) -> None:
        if not self.is_initialized():
            raise FileNotFoundError(f"atlas is not initialized: {self.root}")

    def _default_directories(self) -> list[Path]:
        return [
            self.root,
            self.meta_dir,
            self.meta_dir / "plugins",
            self.meta_dir / "hooks",
            self.root / "daily",
            self.root / "projects",
            self.root / "agents",
            self.root / "agents" / "hermes",
            self.root / "agents" / "hermes" / "learnings",
            self.root / "agents" / "hermes" / "sessions",
            self.root / "agents" / "codex",
            self.root / "entities",
            self.root / "tasks",
            self.root / "ref",
        ]

    def _write_index_note(self) -> Path:
        path = self.root / "index.md"
        if path.exists():
            return path
        today = date.today().isoformat()
        note = Note(
            path=path,
            frontmatter={
                "id": "index",
                "title": "Atlas",
                "type": "index",
                "tags": ["atlas"],
                "links": [],
                "created": today,
                "modified": today,
            },
            body=(
                "# Atlas\n\n"
                "## sections\n\n"
                "- [[daily]]\n"
                "- [[projects]]\n"
                "- [[entities]]\n"
                "- [[tasks]]\n"
                "- [[ref]]\n"
            ),
        )
        note.write()
        return path

    def _write_task_index(self) -> Path:
        path = self.root / "tasks" / "active.md"
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

    def _write_gitignore(self) -> Path:
        path = self.root / ".gitignore"
        required_lines = [
            ".cartographer/index.db",
            ".cartographer/worklog.db",
            ".obsidian/",
        ]
        existing = []
        if path.exists():
            existing = path.read_text(encoding="utf-8").splitlines()
        lines = existing[:]
        for line in required_lines:
            if line not in lines:
                lines.append(line)
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return path

    def init(self) -> dict[str, Any]:
        created: list[str] = []
        for directory in self._default_directories():
            if not directory.exists():
                created.append(str(directory))
            directory.mkdir(parents=True, exist_ok=True)

        self.config["cartographer"]["root"] = str(self.root)
        vault = detect_vault(self.config)
        if vault is not None:
            self.config.setdefault("obsidian", {})
            self.config["obsidian"]["vault"] = str(vault)
        save_config(self.config, root=self.root)

        copied_templates = [str(path) for path in sync_builtin_templates(self.root)]
        copied_plugins = [str(path) for path in sync_builtin_plugins(self.root)]
        ensure_hook_dir(self.root)
        created.append(str(self._write_index_note()))
        created.append(str(self._write_task_index()))
        created.append(str(self._write_gitignore()))

        git_state = "existing"
        if not (self.root / ".git").exists():
            subprocess.run(
                ["git", "init", str(self.root)],
                check=False,
                capture_output=True,
                text=True,
            )
            git_state = "initialized"

        vimwiki_status = "skipped"
        backups: list[str] = []
        skip_vimwiki = os.environ.get("CARTOGRAPHER_SKIP_VIMWIKI_PATCH") == "1"
        if not skip_vimwiki and self.config.get("vimwiki", {}).get("sync", True):
            backups = [str(path) for path in backup_vimwiki_assets()]
            vimwiki_status = patch_vimrc(Path.home() / ".vimrc", self.root)

        worklog = Worklog(self.worklog_db_path)
        session = worklog.start_session()
        task_id = worklog.add_task(session.id, "init atlas root")
        summary = f"initialized atlas at {self.root}"
        worklog.complete_task(task_id, result=summary)
        worklog.end_session(session.id, summary=summary)

        index_result = Index(self.root).rebuild()
        return {
            "root": str(self.root),
            "created": created,
            "templates": copied_templates,
            "plugins": copied_plugins,
            "vault": None if vault is None else str(vault),
            "git": git_state,
            "vimwiki": vimwiki_status,
            "backups": backups,
            "index": index_result,
        }

    def refresh_index(self) -> dict[str, Any]:
        return Index(self.root).rebuild()

    def _editor_command(self) -> list[str]:
        editor = os.environ.get("EDITOR")
        if editor:
            return shlex.split(editor)
        for candidate in ("vim", "vi"):
            path = shutil.which(candidate)
            if path:
                return [path]
        raise RuntimeError("no editor found; set $EDITOR")

    def open_in_editor(self, path: Path) -> None:
        if os.environ.get("CARTOGRAPHER_SKIP_EDITOR") == "1":
            return
        command = self._editor_command() + [str(path)]
        subprocess.run(command, check=False)

    def finalize_note(self, path: Path) -> None:
        if not path.exists() or path.suffix != ".md":
            return
        note = Note.from_file(path)
        note.frontmatter.setdefault("modified", date.today().isoformat())
        note.frontmatter["modified"] = date.today().isoformat()
        note.write(ensure_blocks=True)

    def create_note(
        self,
        note_type: str,
        title: str,
        *,
        priority: str = "P2",
        agent: str = "hermes",
    ) -> Path:
        self.ensure_initialized()
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        slug = slugify(title)

        if note_type == "note":
            path = self.root / f"{slug}.md"
            note_id = slug
        elif note_type == "daily":
            day = title if re.fullmatch(r"\d{4}-\d{2}-\d{2}", title) else today
            path = self.root / "daily" / f"{day}.md"
            note_id = f"daily-{day}"
            title = day
        elif note_type == "project":
            path = self.root / "projects" / f"{slug}.md"
            note_id = slug
        elif note_type == "task":
            path = self.root / "tasks" / f"{slug}.md"
            note_id = slug
        elif note_type == "agent-log":
            session_dir = self.root / "agents" / agent / "sessions"
            session_dir.mkdir(parents=True, exist_ok=True)
            prefix = today + "_"
            count = len(list(session_dir.glob(f"{today}_*.md"))) + 1
            path = session_dir / f"{today}_{count:03d}.md"
            note_id = f"{agent}-{today}-{count:03d}"
        elif note_type == "ref":
            path = self.root / "ref" / f"{slug}.md"
            note_id = slug
        elif note_type == "entity":
            path = self.root / "entities" / f"{slug}.md"
            note_id = slug
        else:
            raise ValueError(f"unknown note type: {note_type}")

        if path.exists():
            raise FileExistsError(f"note already exists: {path}")

        content = render_template(
            note_type,
            {
                "id": note_id,
                "title": title,
                "date": today,
                "yesterday": yesterday,
                "priority": priority,
                "block_id": f"t{slugify(title)[:6] or 'task'}",
                "agent": agent,
            },
            atlas_root=self.root,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.finalize_note(path)
        record_operation(
            self.worklog_db_path,
            f"create {note_type} note",
            f"created {path}",
        )
        self.refresh_index()
        return path

    def resolve_note_path(self, note_id: str) -> Path | None:
        self.ensure_initialized()
        if Path(note_id).exists():
            return Path(note_id).expanduser()
        index = Index(self.root)
        if not self.index_db_path.exists() or index.needs_rebuild():
            index.rebuild()
        return index.find_note_path(note_id)

    def backup(self) -> Path:
        self.ensure_initialized()
        destination_dir = Path.home() / ".cartographer_backups"
        destination_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        destination = destination_dir / f"atlas_{stamp}.tar.gz"
        with tarfile.open(destination, "w:gz") as archive:
            for path in self.root.rglob("*"):
                if path == self.index_db_path:
                    continue
                archive.add(path, arcname=str(Path(self.root.name) / path.relative_to(self.root)))
        record_operation(
            self.worklog_db_path,
            "backup atlas",
            f"created backup {destination}",
        )
        return destination

    def git_status_summary(self) -> str:
        if not (self.root / ".git").exists():
            return "not a git repo"
        porcelain = subprocess.run(
            ["git", "-C", str(self.root), "status", "--porcelain"],
            check=False,
            capture_output=True,
            text=True,
        )
        last_commit = subprocess.run(
            ["git", "-C", str(self.root), "log", "-1", "--format=%cr"],
            check=False,
            capture_output=True,
            text=True,
        )
        clean = "clean" if not porcelain.stdout.strip() else "dirty"
        last_commit_text = last_commit.stdout.strip() or "no commits"
        return f"{clean} ({last_commit_text})"

    def status(self) -> dict[str, Any]:
        self.ensure_initialized()
        index = Index(self.root)
        if not self.index_db_path.exists() or index.needs_rebuild():
            index.rebuild()
        index_status = index.status()
        size = 0
        for path in self.root.rglob("*"):
            if path.is_file():
                size += path.stat().st_size
        tasks_summary = summarize_tasks(self.root)
        hermes_sessions = list((self.root / "agents" / "hermes" / "sessions").glob("*.md"))
        codex_sessions = list((self.root / "agents" / "codex").glob("*.md"))
        worklog_status = Worklog(self.worklog_db_path).status()
        return {
            "root": self.root,
            "note_count": index_status["notes"],
            "atlas_size": human_bytes(size),
            "index": index_status,
            "tasks": tasks_summary,
            "agents": {
                "hermes_sessions": len(hermes_sessions),
                "codex_sessions": len(codex_sessions),
            },
            "git": self.git_status_summary(),
            "worklog": worklog_status,
        }
