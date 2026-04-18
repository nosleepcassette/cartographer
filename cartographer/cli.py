from __future__ import annotations

import argparse
import copy
import json
import shlex
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import click
from click.shell_completion import get_completion_class

from .agent_memory import (
    append_learning,
    confirm_learnings,
    gc_learnings,
    pending_learning_blocks,
    reject_learnings,
)
from .atlas import Atlas
from .config import save_config
from .integrations import qmd
from .daily_brief import build_daily_brief
from .index import Index
from .mapsos import (
    default_export_paths,
    default_intake_paths,
    ingest_mapsos_exports,
    ingest_mapsos_intake,
    load_mapsos_payload,
    sync_mapsos_payload,
)
from .notes import Note
from .obsidian import sync as obsidian_sync_impl
from .plugins import (
    apply_writes,
    list_plugins,
    parse_plugin_args,
    run_plugin,
)
from .external_import import parse_chatgpt_export, parse_claude_web_export
from .session_import import (
    _today_string,
    default_session_paths,
    import_imported_session,
    import_session,
    import_sessions,
)
from .session_import import clean_entity_imports
from .tasks import append_task, mark_done, query_tasks, sort_tasks
from .vimwiki import patch_vimrc
from .worklog import Worklog
from .working_set import add_entry as add_working_set_entry
from .working_set import gc_entries as gc_working_set_entries
from .working_set import list_entries as list_working_set_entries
from .working_set import working_set_stats

JSON_SCHEMA_VERSION = "2026-04-17"


def get_atlas(root: str | None = None) -> Atlas:
    atlas = Atlas(root=root)
    if not atlas.is_initialized():
        raise click.ClickException(
            f"atlas not initialized at {atlas.root}. run: cart init"
        )
    return atlas


def ensure_index_current(atlas: Atlas) -> Index:
    index = Index(atlas.root)
    if not atlas.index_db_path.exists() or index.needs_rebuild():
        click.echo("rebuilding index...", err=True)
        index.rebuild()
    return index


def coming_soon(message: str) -> None:
    click.echo(message)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _emit_json(payload: Any) -> None:
    click.echo(json.dumps(_jsonable(payload), indent=2, ensure_ascii=False))


def _with_schema(payload: dict[str, Any], *, surface: str) -> dict[str, Any]:
    return {
        "schema_version": JSON_SCHEMA_VERSION,
        "surface": surface,
        **payload,
    }


def _format_timestamp(value: float | None) -> str:
    if value is None:
        return "never"
    return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M")


def _task_payload(task: Any) -> dict[str, Any]:
    return {
        "id": task.id,
        "path": str(task.path),
        "text": task.text,
        "status": task.status,
        "priority": task.priority,
        "project": task.project,
        "due": task.due,
        "done": task.done,
    }


def _doctor_payload(atlas: Atlas) -> dict[str, Any]:
    initialized = atlas.is_initialized()
    warnings: list[str] = []

    index_payload: dict[str, Any] = {
        "path": str(atlas.index_db_path),
        "exists": atlas.index_db_path.exists(),
        "needs_rebuild": None,
        "notes": 0,
        "blocks": 0,
        "last_rebuild": None,
    }
    if initialized and atlas.index_db_path.exists():
        index = Index(atlas.root)
        index_status = index.status()
        index_payload.update(index_status)
        index_payload["needs_rebuild"] = index.needs_rebuild()
        if index_payload["needs_rebuild"]:
            warnings.append("atlas index is stale; run `cart index rebuild`")
    elif initialized:
        warnings.append("atlas index does not exist yet; run `cart status` or `cart index rebuild`")

    mapsos_settings = atlas.config.get("mapsos", {})
    export_dir = Path(
        str(mapsos_settings.get("export_dir") or Path.home() / ".mapsOS" / "exports")
    ).expanduser()
    intake_dir = Path(
        str(mapsos_settings.get("intake_dir") or Path.home() / "dev" / "mapsOS" / "intakes")
    ).expanduser()
    export_files = sorted(export_dir.glob("*.json")) if export_dir.exists() else []
    intake_files = sorted(intake_dir.glob("*.md")) if intake_dir.exists() else []
    if not export_files:
        warnings.append("no mapsOS exports found")

    qmd_settings = _qmd_settings(atlas)
    qmd_mode = str(qmd_settings.get("enabled", "auto")).strip().lower() or "auto"
    qmd_available = qmd.is_available()
    configured_collection = str(qmd_settings.get("default_collection", "")).strip() or None
    detected_collection = qmd.collection_name_for_path(atlas.root) if qmd_available else None
    effective_collection = configured_collection or detected_collection
    if qmd_mode == "on" and not qmd_available:
        warnings.append("qmd.enabled=on but `qmd` is not available on PATH")
    if qmd_available and qmd_mode != "off" and effective_collection is None:
        warnings.append("qmd is available but no atlas collection is configured")

    plugin_dir = atlas.root / ".cartographer" / "plugins"
    plugin_files = (
        sorted(path.name for path in plugin_dir.iterdir() if path.is_file() and not path.name.startswith("."))
        if plugin_dir.exists()
        else []
    )
    working_set = working_set_stats(atlas.root)
    if working_set["expired_count"]:
        warnings.append(
            f"working set has {working_set['expired_count']} expired entries; run `cart working-set gc`"
        )

    payload = {
        "root": str(atlas.root),
        "initialized": initialized,
        "config_path": str(atlas.config_path),
        "index": {
            **index_payload,
            "last_rebuild_text": _format_timestamp(index_payload["last_rebuild"]),
        },
        "qmd": {
            "mode": qmd_mode,
            "available": qmd_available,
            "configured_collection": configured_collection,
            "detected_collection": detected_collection,
            "effective_collection": effective_collection,
        },
        "mapsos": {
            "export_dir": str(export_dir),
            "export_dir_exists": export_dir.exists(),
            "export_count": len(export_files),
            "latest_export": None if not export_files else str(export_files[-1]),
            "intake_dir": str(intake_dir),
            "intake_dir_exists": intake_dir.exists(),
            "intake_count": len(intake_files),
            "latest_intake": None if not intake_files else str(intake_files[-1]),
        },
        "plugins": {
            "dir": str(plugin_dir),
            "exists": plugin_dir.exists(),
            "count": len(plugin_files),
            "names": plugin_files,
        },
        "working_set": working_set,
        "git": atlas.git_status_summary() if initialized else "not initialized",
        "warnings": warnings,
    }
    if not initialized:
        payload["warnings"].insert(0, f"atlas is not initialized at {atlas.root}")
    return payload


_STRUCTURED_QUERY_PREFIXES = (
    "tag:",
    "status:",
    "type:",
    "links:",
    "modified:>",
    "text:",
    "block-ref:",
)
_ATLAS_QMD_CONTEXT = "atlas knowledge graph: agents, projects, entities, tasks, daily notes"


def _qmd_settings(atlas: Atlas) -> dict[str, object]:
    raw = atlas.config.get("qmd", {})
    return raw if isinstance(raw, dict) else {}


def _supports_qmd_query(expression: str) -> bool:
    tokens = shlex.split(expression) if expression else []
    if not tokens:
        return False
    return not any(
        any(token.startswith(prefix) for prefix in _STRUCTURED_QUERY_PREFIXES)
        for token in tokens
    )


def _qmd_collection_name(atlas: Atlas, settings: dict[str, object]) -> str | None:
    configured = str(settings.get("default_collection", "")).strip()
    if configured:
        return configured
    return qmd.collection_name_for_path(atlas.root)


def _qmd_query_paths(atlas: Atlas, expr: str) -> list[str]:
    if not _supports_qmd_query(expr):
        return []

    settings = _qmd_settings(atlas)
    enabled = str(settings.get("enabled", "auto")).strip().lower() or "auto"
    if enabled == "off":
        return []

    if not qmd.is_available():
        if enabled == "on":
            raise click.ClickException(
                "qmd.enabled=on but `qmd` is not installed or not on PATH"
            )
        return []

    collection = _qmd_collection_name(atlas, settings)
    if collection is None:
        if enabled == "on":
            raise click.ClickException(
                "qmd.enabled=on but no qmd collection points at this atlas. run `cart qmd bootstrap`"
            )
        return []

    try:
        min_score = float(settings.get("min_score", 0.35))
    except (TypeError, ValueError):
        min_score = 0.35

    hits = qmd.query(
        expr,
        collection=collection,
        min_score=min_score,
        mode="query",
    )
    deduped_paths: list[str] = []
    seen: set[str] = set()
    for hit in hits:
        resolved = qmd.resolve_path(hit.path, fallback_root=atlas.root)
        if resolved is None or not resolved.exists():
            continue
        path = str(resolved)
        if path in seen:
            continue
        seen.add(path)
        deduped_paths.append(path)
    return deduped_paths


def _bootstrap_qmd(atlas: Atlas) -> dict[str, object]:
    if not qmd.is_available():
        return {"available": False}

    collection_name, created = qmd.ensure_collection(atlas.root, preferred_name="atlas")
    if collection_name is None:
        raise click.ClickException(
            f"unable to create or locate a qmd collection for {atlas.root}"
        )

    if created:
        qmd.add_context(f"qmd://{collection_name}/", _ATLAS_QMD_CONTEXT)

    updated_config = copy.deepcopy(atlas.config)
    qmd_config = updated_config.get("qmd", {})
    if not isinstance(qmd_config, dict):
        qmd_config = {}
        updated_config["qmd"] = qmd_config
    qmd_config["enabled"] = str(qmd_config.get("enabled", "auto")).strip().lower() or "auto"
    qmd_config["default_collection"] = collection_name
    save_config(updated_config, root=atlas.root)

    return {
        "available": True,
        "collection": collection_name,
        "created": created,
        "config_path": atlas.root / ".cartographer" / "config.toml",
        "embed_ok": qmd.embed_full(),
    }


def resolve_query_paths(atlas: Atlas, expr: str) -> list[str]:
    if "type:task" in expr or any(
        token in expr for token in ("priority:", "project:", "due:")
    ):
        return sorted({str(task.path) for task in query_tasks(atlas.root, expr)})
    qmd_paths = _qmd_query_paths(atlas, expr)
    if qmd_paths:
        return qmd_paths
    return ensure_index_current(atlas).query(expr)


def load_note_payload(path: Path) -> dict[str, object]:
    note = Note.from_file(path)
    return {
        "id": str(note.frontmatter.get("id") or path.stem),
        "path": str(path),
        "frontmatter": note.frontmatter,
        "content": note.body,
    }


def _session_metadata(path: Path) -> dict[str, Any]:
    note = Note.from_file(path)
    frontmatter = note.frontmatter
    path_parts = path.parts
    agent = ""
    try:
        agents_index = path_parts.index("agents")
    except ValueError:
        agents_index = -1
    if agents_index >= 0 and agents_index + 1 < len(path_parts):
        agent = str(path_parts[agents_index + 1])

    modified_value = str(frontmatter.get("modified") or "").strip()
    if not modified_value:
        modified_value = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")

    return {
        "id": str(frontmatter.get("id") or path.stem),
        "title": str(frontmatter.get("title") or path.stem),
        "path": str(path),
        "agent": agent or str(frontmatter.get("agent") or ""),
        "type": str(frontmatter.get("type") or "note"),
        "date": str(frontmatter.get("date") or ""),
        "summary_preview": str(frontmatter.get("summary_preview") or ""),
        "source_type": str(frontmatter.get("source_type") or ""),
        "source": str(frontmatter.get("source") or ""),
        "session_started": str(frontmatter.get("session_started") or ""),
        "session_updated": str(frontmatter.get("session_updated") or ""),
        "model": str(frontmatter.get("model") or ""),
        "modified": modified_value,
    }


def recent_sessions_payload(
    atlas: Atlas,
    *,
    limit: int = 8,
    agent: str | None = None,
) -> dict[str, Any]:
    session_root = atlas.root / "agents"
    paths: list[Path] = []
    if session_root.exists():
        for candidate in session_root.glob("*/sessions/*.md"):
            if not candidate.is_file():
                continue
            if agent and candidate.parts[-3] != agent:
                continue
            paths.append(candidate)

    sessions = [_session_metadata(path) for path in paths]
    sessions.sort(
        key=lambda item: (
            str(item.get("date") or ""),
            str(item.get("session_updated") or ""),
            str(item.get("modified") or ""),
            str(item.get("path") or ""),
        ),
        reverse=True,
    )
    return {
        "agent": agent,
        "count": len(sessions[: max(limit, 0)]),
        "sessions": sessions[: max(limit, 0)],
    }


@click.group()
def main() -> None:
    """cartographer — maps your knowledge."""


@main.command()
@click.argument("path", required=False, default="~/atlas")
@click.option("--no-vimwiki", is_flag=True, help="Skip vimwiki patching during init.")
@click.option(
    "--no-obsidian", is_flag=True, help="Skip atlas-local Obsidian bootstrap."
)
def init(path: str, no_vimwiki: bool, no_obsidian: bool) -> None:
    atlas = Atlas(root=path)
    result = atlas.init(
        setup_vimwiki=not no_vimwiki,
        setup_obsidian=not no_obsidian,
    )
    click.echo(f"atlas: {result['root']}")
    click.echo(f"git: {result['git']}")
    click.echo(f"vimwiki: {result['vimwiki']}")
    click.echo(f"obsidian: {result['obsidian']}")
    for warning in result.get("backup_warnings", []):
        click.echo(f"warning: {warning}", err=True)
    if result["vault"]:
        click.echo(f"obsidian vault: {result['vault']}")
    if result.get("external_vault"):
        click.echo(f"obsidian external vault: {result['external_vault']}")
    click.echo(
        "index: "
        f"{result['index']['notes']} notes, {result['index']['blocks']} blocks, {result['index']['refs']} refs"
    )


@main.command("completion")
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]))
@click.option(
    "--prog-name",
    default="cart",
    show_default=True,
    help="Command name to generate completions for.",
)
def completion(shell: str, prog_name: str) -> None:
    """Print a shell completion script for cart."""
    completion_class = get_completion_class(shell)
    if completion_class is None:
        raise click.ClickException(f"unsupported shell: {shell}")
    complete_var = f"_{prog_name.replace('-', '_').replace('.', '_').upper()}_COMPLETE"
    generator = completion_class(
        cli=main,
        ctx_args={},
        prog_name=prog_name,
        complete_var=complete_var,
    )
    click.echo(generator.source())


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def status(as_json: bool) -> None:
    """Show atlas health, task counts, and session totals."""
    atlas = get_atlas()
    info = atlas.status()
    if as_json:
        _emit_json(_with_schema(info, surface="status"))
        return
    last_rebuild_text = _format_timestamp(info["index"]["last_rebuild"])
    tasks = info["tasks"]
    priorities = tasks["by_priority"]
    worklog = info["worklog"]
    click.echo(
        f"atlas: {info['root']} ({info['note_count']} notes, {info['atlas_size']})"
    )
    click.echo(f"index: rebuilt {last_rebuild_text}")
    click.echo(
        "tasks: "
        f"{tasks['open']} open ({priorities['P0']} P0, {priorities['P1']} P1, "
        f"{priorities['P2']} P2, {priorities['P3']} P3)"
    )
    click.echo(
        "agents: "
        f"claude {info['agents']['claude_sessions']} sessions, "
        f"hermes {info['agents']['hermes_sessions']} sessions, "
        f"codex {info['agents']['codex_sessions']} sessions"
    )
    click.echo(f"git: {info['git']}")
    click.echo(f"worklog: {len(worklog['in_progress'])} in-progress tasks")


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def doctor(as_json: bool) -> None:
    """Check atlas, qmd, mapsOS, and plugin health in one pass."""
    atlas = Atlas()
    payload = _doctor_payload(atlas)
    if as_json:
        _emit_json(_with_schema(payload, surface="doctor"))
        return

    click.echo(f"atlas: {'ok' if payload['initialized'] else 'warn'}  {payload['root']}")
    click.echo(f"config: {payload['config_path']}")
    index = payload["index"]
    click.echo(
        "index: "
        f"{'ok' if index['exists'] and not index['needs_rebuild'] else 'warn'}  "
        f"{index['notes']} notes, {index['blocks']} blocks, rebuilt {index['last_rebuild_text']}"
    )
    qmd_payload = payload["qmd"]
    qmd_state = "ok" if qmd_payload["mode"] == "off" or qmd_payload["available"] else "warn"
    qmd_collection = qmd_payload["effective_collection"] or "none"
    click.echo(
        "qmd: "
        f"{qmd_state}  mode={qmd_payload['mode']}  available={qmd_payload['available']}  collection={qmd_collection}"
    )
    mapsos_payload = payload["mapsos"]
    click.echo(
        "mapsOS: "
        f"{'ok' if mapsos_payload['export_count'] else 'warn'}  "
        f"{mapsos_payload['export_count']} exports  latest={mapsos_payload['latest_export'] or 'none'}"
    )
    plugins = payload["plugins"]
    click.echo(
        "plugins: "
        f"{'ok' if plugins['exists'] else 'warn'}  {plugins['count']} files in {plugins['dir']}"
    )
    working_set = payload["working_set"]
    click.echo(
        "working-set: "
        f"{'warn' if working_set['expired_count'] else 'ok'}  "
        f"{working_set['count']} entries  expired={working_set['expired_count']}  pinned={working_set['pinned_count']}"
    )
    click.echo(f"git: {payload['git']}")
    if payload["warnings"]:
        click.echo(f"warnings: {len(payload['warnings'])}")
        for warning in payload["warnings"]:
            click.echo(f"- {warning}")
    else:
        click.echo("warnings: none")


@main.command("tui")
def tui_command() -> None:
    """Launch the atlas TUI."""
    try:
        from .tui import CartTUI
    except ModuleNotFoundError as exc:
        missing_root = (exc.name or "").split(".", 1)[0]
        if missing_root in {"textual", "rich", "markdown_it", "mdit_py_plugins"}:
            raise click.ClickException(
                "TUI dependencies are missing in the active `cart` environment. "
                "If you installed via pipx, run: `pipx install -e /Users/maps/dev/cartographer --force` "
                "or `pipx inject cartographer textual`."
            ) from exc
        raise
    app = CartTUI()
    app.run()


@main.command()
def backup() -> None:
    atlas = get_atlas()
    destination = atlas.backup()
    click.echo(f"backup: {destination}")


@main.command()
@click.argument("parts", nargs=-1, required=True)
@click.option("-p", "--priority", default="P2", show_default=True)
@click.option("--agent", default="hermes", show_default=True)
def new(parts: tuple[str, ...], priority: str, agent: str) -> None:
    if len(parts) == 1:
        note_type = "note"
        title = parts[0]
    else:
        note_type = parts[0]
        title = " ".join(parts[1:])
    atlas = get_atlas()
    path = atlas.create_note(note_type, title, priority=priority, agent=agent)
    atlas.open_in_editor(path)
    atlas.finalize_note(path)
    atlas.refresh_index()
    click.echo(path)


def _open_note(note_id: str) -> None:
    atlas = get_atlas()
    path = atlas.resolve_note_path(note_id)
    if path is None:
        raise click.ClickException(f"note not found: {note_id}")
    atlas.open_in_editor(path)
    atlas.finalize_note(path)
    atlas.refresh_index()
    click.echo(path)


@main.command()
@click.argument("note_id")
def open(note_id: str) -> None:
    _open_note(note_id)


@main.command("ls")
@click.option("--type", "note_type", help="Filter by note type.")
@click.option("--limit", default=20, type=int, show_default=True)
def ls_notes(note_type: str | None, limit: int) -> None:
    atlas = get_atlas()
    index = ensure_index_current(atlas)
    if note_type:
        paths = [Path(path) for path in index.query(f"type:{note_type}")]
    else:
        paths = index.iter_note_paths()
    for path in paths[:limit]:
        note = Note.from_file(path)
        note_id = str(note.frontmatter.get("id") or path.stem)
        title = str(note.frontmatter.get("title") or path.stem)
        rendered_type = str(note.frontmatter.get("type") or "note")
        click.echo(f"{note_id:28} {rendered_type:14} {title}")


@main.command()
@click.argument("note_id")
def edit(note_id: str) -> None:
    _open_note(note_id)


@main.command()
@click.argument("expression", nargs=-1, required=True)
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def query(expression: tuple[str, ...], as_json: bool) -> None:
    """Query atlas notes by structured tokens or plain text."""
    atlas = get_atlas()
    expr = " ".join(expression)
    results = resolve_query_paths(atlas, expr)
    if as_json:
        _emit_json(_with_schema({"expression": expr, "results": results}, surface="query"))
        return
    for result in results:
        click.echo(result)


@main.command()
@click.argument("note_id")
def show(note_id: str) -> None:
    atlas = get_atlas()
    path = atlas.resolve_note_path(note_id)
    if path is None:
        index = ensure_index_current(atlas)
        partial_matches = [
            candidate
            for candidate in index.iter_note_paths()
            if note_id.lower() in candidate.stem.lower()
        ]
        if not partial_matches:
            raise click.ClickException(f"note not found: {note_id}")
        path = partial_matches[0]
    click.echo(path.read_text(encoding="utf-8"), nl=False)


@main.group("qmd")
def qmd_group() -> None:
    """optional qmd search helpers."""


@qmd_group.command("bootstrap")
def qmd_bootstrap() -> None:
    atlas = get_atlas()
    result = _bootstrap_qmd(atlas)
    if not result["available"]:
        click.echo(
            "qmd not installed; cart will use built-in search. See https://github.com/tobilu/qmd to enable enhanced recall."
        )
        return
    collection = str(result["collection"])
    created = bool(result["created"])
    click.echo(
        f"qmd: {'created' if created else 'using'} atlas collection `{collection}` for {atlas.root}"
    )
    click.echo(f"config: wrote default_collection = \"{collection}\"")
    if result["embed_ok"]:
        click.echo("embed: complete")
    else:
        click.echo("embed: qmd embed failed; run `qmd embed` manually")
    click.echo("next: `cart query \"plain language query\"` now prefers qmd for atlas-scoped matches")


@main.command()
@click.argument("target")
@click.option("--block", "block_mode", is_flag=True, help="Treat target as note#block.")
def backlinks(target: str, block_mode: bool) -> None:
    atlas = get_atlas()
    index = ensure_index_current(atlas)
    if block_mode or "#" in target:
        if "#" not in target:
            raise click.ClickException("block target must look like note-id#block-id")
        note_id, block_id = target.split("#", 1)
        results = index.block_backlinks(note_id, block_id)
    else:
        results = index.backlinks(target)
    for result in results:
        click.echo(result)


@main.group()
def todo() -> None:
    """todo commands."""


@todo.command("list")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def todo_list(as_json: bool) -> None:
    atlas = get_atlas()
    tasks = sort_tasks(query_tasks(atlas.root, "status:open"))
    if as_json:
        _emit_json(
            _with_schema(
                {"query": "status:open", "tasks": [_task_payload(task) for task in tasks]},
                surface="todo.list",
            )
        )
        return
    for task in tasks:
        parts = [task.id, task.priority, task.text]
        if task.project:
            parts.append(f"project={task.project}")
        if task.due:
            parts.append(f"due={task.due}")
        click.echo(" | ".join(parts))


@todo.command("add")
@click.argument("text")
@click.option("-p", "--priority", default="P2", show_default=True)
@click.option("--project")
@click.option("--due")
def todo_add(text: str, priority: str, project: str | None, due: str | None) -> None:
    atlas = get_atlas()
    task = append_task(atlas.root, text, priority=priority, project=project, due=due)
    atlas.refresh_index()
    click.echo(f"{task.id} {task.path}")


@todo.command("done")
@click.argument("task_id")
def todo_done(task_id: str) -> None:
    atlas = get_atlas()
    task = mark_done(atlas.root, task_id)
    atlas.refresh_index()
    click.echo(f"completed {task.id}")


@todo.command("query")
@click.argument("expression", nargs=-1, required=True)
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def todo_query(expression: tuple[str, ...], as_json: bool) -> None:
    """Query tasks by status, priority, project, due date, or text."""
    atlas = get_atlas()
    expr = " ".join(expression)
    tasks = query_tasks(atlas.root, expr)
    if as_json:
        _emit_json(
            _with_schema(
                {"expression": expr, "tasks": [_task_payload(task) for task in tasks]},
                surface="todo.query",
            )
        )
        return
    for task in tasks:
        parts = [task.id, task.status, task.priority, task.text]
        if task.project:
            parts.append(f"project={task.project}")
        if task.due:
            parts.append(f"due={task.due}")
        click.echo(" | ".join(parts))


@main.group()
def worklog() -> None:
    """worklog commands."""


@worklog.command("status")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def worklog_status(as_json: bool) -> None:
    atlas = get_atlas()
    data = Worklog(atlas.worklog_db_path).status()
    if as_json:
        _emit_json(_with_schema(data, surface="worklog.status"))
        return
    click.echo(f"current_session: {data['current_session_id'] or 'none'}")
    click.echo(f"in_progress: {len(data['in_progress'])}")
    if data["last_session"]:
        click.echo(f"last_session: {data['last_session']['id']}")
        summary = data["last_session"].get("summary") or ""
        if summary:
            click.echo(summary)


@worklog.command("complete")
@click.argument("task_id")
@click.option("--result", default="", help="Result text.")
def worklog_complete(task_id: str, result: str) -> None:
    atlas = get_atlas()
    worklog = Worklog(atlas.worklog_db_path)
    worklog.complete_task(task_id, result=result)
    click.echo(f"completed {task_id}")


@worklog.command("log")
@click.argument("text")
def worklog_log(text: str) -> None:
    atlas = get_atlas()
    session_id = Worklog(atlas.worklog_db_path).log(text)
    click.echo(f"logged to {session_id}")


@main.group()
def index() -> None:
    """index commands."""


@index.command("rebuild")
def index_rebuild() -> None:
    atlas = get_atlas()
    result = Index(atlas.root).rebuild()
    click.echo(
        f"rebuilt index: {result['notes']} notes, {result['blocks']} blocks, {result['refs']} refs"
    )


@index.command("status")
def index_status() -> None:
    atlas = get_atlas()
    status_info = ensure_index_current(atlas).status()
    click.echo(f"notes: {status_info['notes']}")
    click.echo(f"blocks: {status_info['blocks']}")
    if status_info["last_rebuild"] is not None:
        click.echo(
            "last_rebuild: "
            + datetime.fromtimestamp(status_info["last_rebuild"]).isoformat(
                timespec="seconds"
            )
        )


@main.command(
    "learn",
    context_settings={
        "ignore_unknown_options": True,
        "allow_extra_args": True,
    },
)
@click.argument("parts", nargs=-1, type=click.UNPROCESSED)
def learn(parts: tuple[str, ...]) -> None:
    """Add learnings, or run confirm/reject/pending via `cart learn <mode>`."""
    atlas = get_atlas()
    tokens = list(parts)
    if not tokens:
        raise click.ClickException(
            "provide learning text or a learn mode: confirm, reject, pending"
        )

    mode = tokens[0]
    if mode == "pending":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--agent")
        parsed = parser.parse_args(tokens[1:])
        pending = pending_learning_blocks(atlas.root, agent=parsed.agent)
        if not pending:
            click.echo("no pending learnings")
            return
        for item in pending:
            source_agent = item.attrs.get("source_agent") or item.agent or "unknown"
            learned_on = item.attrs.get("date") or "unknown"
            click.echo(
                f"{item.block_id} | {source_agent} | {item.topic} | {learned_on} | {item.content}"
            )
        return

    if mode in {"confirm", "reject"}:
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("topic", nargs="?")
        parser.add_argument("--block", dest="block_id")
        parser.add_argument("--agent")
        parsed = parser.parse_args(tokens[1:])
        try:
            result = (
                confirm_learnings(
                    atlas.root,
                    topic=parsed.topic,
                    block_id=parsed.block_id,
                    agent=parsed.agent,
                )
                if mode == "confirm"
                else reject_learnings(
                    atlas.root,
                    topic=parsed.topic,
                    block_id=parsed.block_id,
                    agent=parsed.agent,
                )
            )
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        if result["writes"]:
            apply_writes(atlas.root, result["writes"], plugin_name=f"learn-{mode}")
            atlas.refresh_index()
        click.echo(f"{mode}ed {result['updated']} learning block(s)")
        return

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--topic", default="general")
    parser.add_argument("--agent", default="hermes")
    parser.add_argument("--confidence", default=0.85, type=float)
    parser.add_argument("--entity")
    parsed, remaining = parser.parse_known_args(tokens)
    text = " ".join(remaining).strip()
    if not text:
        raise click.ClickException("provide learning text")
    result = append_learning(
        atlas.root,
        agent=parsed.agent,
        topic=parsed.topic,
        text=text,
        confidence=parsed.confidence,
        entity=parsed.entity,
    )
    applied = apply_writes(atlas.root, result["writes"], plugin_name="learn")
    atlas.refresh_index()
    click.echo(f"learned {parsed.topic} -> {applied[0]}")


@main.command("agent-ingest")
@click.argument("parts", nargs=-1, required=True)
def agent_ingest(parts: tuple[str, ...]) -> None:
    if len(parts) == 1:
        agent = "hermes"
        source = parts[0]
    elif len(parts) == 2:
        agent, source = parts
    else:
        raise click.ClickException("usage: cart agent-ingest [agent] session.json")
    atlas = get_atlas()
    source_path = Path(source).expanduser()
    if not source_path.exists():
        raise click.ClickException(f"session file not found: {source_path}")
    raw = source_path.read_text(encoding="utf-8")
    try:
        session_data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise click.ClickException(
            f"session file is not valid JSON: {source_path}"
        ) from exc
    result = run_plugin(
        atlas.root,
        "agent-ingest",
        {
            "command": "agent-ingest",
            "args": {"agent": agent, "source_path": str(source_path)},
            "session": session_data,
        },
    )
    atlas.refresh_index()
    click.echo(str(result.get("output", "")))


@main.command("agent-gc")
@click.option("--threshold", default=0.30, type=float, show_default=True)
@click.option("--agent")
def agent_gc(threshold: float, agent: str | None) -> None:
    atlas = get_atlas()
    result = gc_learnings(atlas.root, threshold=threshold, agent=agent)
    if result["writes"]:
        apply_writes(atlas.root, result["writes"], plugin_name="agent-gc")
        atlas.refresh_index()
    click.echo(
        f"scanned {result['scanned_files']} files, updated {result['updated']}, removed {result['removed']}"
    )


@main.command()
@click.argument("query", nargs=-1)
@click.option("--model", default="hermes", show_default=True)
@click.option("--max-words", default=300, type=int, show_default=True)
@click.option("--write", "write_path")
def summarize(
    query: tuple[str, ...],
    model: str,
    max_words: int,
    write_path: str | None,
) -> None:
    atlas = get_atlas()
    expr = " ".join(query)
    if expr:
        paths = resolve_query_paths(atlas, expr)
    elif not sys.stdin.isatty():
        paths = [line.strip() for line in sys.stdin.read().splitlines() if line.strip()]
    else:
        raise click.ClickException("provide a query or pipe note paths on stdin")
    notes = [
        load_note_payload(Path(path).expanduser())
        for path in paths
        if Path(path).exists()
    ]
    result = run_plugin(
        atlas.root,
        "summarize",
        {
            "command": "summarize",
            "args": {"model": model, "max_words": max_words},
            "notes": notes,
        },
    )
    output = str(result.get("output", ""))
    if write_path:
        apply_writes(
            atlas.root,
            [
                {
                    "path": write_path,
                    "content": output + ("\n" if not output.endswith("\n") else ""),
                }
            ],
            plugin_name="summarize",
        )
    click.echo(output)


@main.command("daily-brief")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["markdown", "plain"]),
    default="markdown",
    show_default=True,
)
@click.option("--output")
def daily_brief(output_format: str, output: str | None) -> None:
    atlas = get_atlas()
    rendered = build_daily_brief(atlas.root, format=output_format)
    if output:
        destination = Path(output).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8")
    click.echo(rendered, nl=False)


@main.command("vimwiki-sync")
def vimwiki_sync() -> None:
    atlas = get_atlas()
    status_text = patch_vimrc(Path.home() / ".vimrc", atlas.root)
    click.echo(status_text)


@main.command("obsidian-sync")
@click.option(
    "--dataview",
    "use_dataview",
    is_flag=True,
    help="Sync with Dataview-compatible frontmatter.",
)
def obsidian_sync(use_dataview: bool) -> None:
    atlas = get_atlas()
    vault = atlas.config.get("obsidian", {}).get("vault")
    if not vault:
        raise click.ClickException("no obsidian vault configured")
    vault_path = Path(str(vault)).expanduser()
    if use_dataview:
        from .obsidian import sync_with_dataview

        result = sync_with_dataview(atlas.root, vault_path)
        click.echo(result["output"])
    else:
        destination = obsidian_sync_impl(atlas.root, vault_path)
        click.echo(destination)


@main.group()
def sessions() -> None:
    """session note surfaces."""


@sessions.command("recent")
@click.option("--limit", default=8, type=int, show_default=True)
@click.option("--agent", help="Filter by agent slug, e.g. hermes or claude.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def sessions_recent(limit: int, agent: str | None, as_json: bool) -> None:
    atlas = get_atlas()
    payload = recent_sessions_payload(atlas, limit=limit, agent=agent)
    if as_json:
        _emit_json(_with_schema(payload, surface="sessions.recent"))
        return
    for session in payload["sessions"]:
        summary = str(session.get("summary_preview") or "").strip()
        suffix = f" — {summary}" if summary else ""
        click.echo(
            f"{session['agent']:8} {session['date'] or 'unknown-date'}  {session['title']}{suffix}"
        )


@main.group("working-set")
def working_set() -> None:
    """temporary, role-scoped working memory surfaces."""


@working_set.command("add")
@click.argument("title")
@click.option("--role", default="intake", show_default=True)
@click.option("--scope", default="general", show_default=True)
@click.option("--body", default="", help="Optional body text for the entry.")
@click.option("--provenance", multiple=True, help="Repeatable provenance references.")
@click.option("--verification-needed", is_flag=True, help="Mark that the entry still needs source verification.")
@click.option("--pinned", is_flag=True, help="Do not expire this entry automatically.")
@click.option("--ttl-hours", default=24, type=int, show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def working_set_add(
    title: str,
    role: str,
    scope: str,
    body: str,
    provenance: tuple[str, ...],
    verification_needed: bool,
    pinned: bool,
    ttl_hours: int,
    as_json: bool,
) -> None:
    atlas = get_atlas()
    entry = add_working_set_entry(
        atlas.root,
        title=title,
        role=role,
        scope=scope,
        body=body,
        provenance=list(provenance),
        verification_needed=verification_needed,
        pinned=pinned,
        ttl_hours=ttl_hours,
    )
    if as_json:
        _emit_json(_with_schema({"entry": entry}, surface="working-set.add"))
        return
    expiry = "pinned" if entry["pinned"] else f"expires {entry['expires_at']}"
    click.echo(f"{entry['id']}  {entry['role']}/{entry['scope']}  {expiry}")


@working_set.command("list")
@click.option("--role")
@click.option("--scope")
@click.option("--include-expired", is_flag=True, help="Show expired entries instead of lazily cleaning them.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def working_set_list(
    role: str | None,
    scope: str | None,
    include_expired: bool,
    as_json: bool,
) -> None:
    atlas = get_atlas()
    entries = list_working_set_entries(
        atlas.root,
        role=role,
        scope=scope,
        include_expired=include_expired,
        delete_expired=not include_expired,
    )
    payload = {
        "role": role,
        "scope": scope,
        "count": len(entries),
        "entries": entries,
    }
    if as_json:
        _emit_json(_with_schema(payload, surface="working-set.list"))
        return
    for entry in entries:
        status = "expired" if entry.get("expired") else ("pinned" if entry.get("pinned") else "active")
        click.echo(
            f"{entry['id']}  {entry['role']}/{entry['scope']}  {status}  {entry['title']}"
        )


@working_set.command("gc")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def working_set_gc(as_json: bool) -> None:
    atlas = get_atlas()
    payload = gc_working_set_entries(atlas.root)
    if as_json:
        _emit_json(_with_schema(payload, surface="working-set.gc"))
        return
    click.echo(
        f"removed {payload['removed_count']} expired working-set entr{'y' if payload['removed_count'] == 1 else 'ies'}"
    )


def _resolve_session_import_paths(
    source_type: str,
    paths: tuple[str, ...],
    latest: int,
    import_all: bool,
) -> list[Path]:
    if paths:
        resolved = [Path(path).expanduser() for path in paths]
    elif import_all:
        resolved = default_session_paths(source_type, latest=None)
    else:
        resolved = default_session_paths(source_type, latest=latest)
    return [path for path in resolved if path.exists()]


def _run_session_import(
    source_type: str,
    paths: tuple[str, ...],
    *,
    latest: int,
    import_all: bool,
    force: bool = False,
) -> None:
    atlas = get_atlas()
    selected_paths = _resolve_session_import_paths(
        source_type, paths, latest, import_all
    )
    if not selected_paths:
        raise click.ClickException(f"no {source_type} session files found")
    result = import_sessions(atlas.root, source_type, selected_paths, force=force)
    atlas.refresh_index()
    skipped = result.get("skipped", 0)
    click.echo(
        f"imported {result['count']} {source_type} session(s)"
        + (f", skipped {skipped} already-imported" if skipped else "")
    )
    for session in result["sessions"]:
        click.echo(f"{session['source']} -> {session['session_note']}")
    if skipped and not force:
        click.echo("  (use --force to re-import skipped sessions)")


def _mapsos_export_paths(atlas: Atlas, *, latest: int | None = None) -> list[Path]:
    configured = atlas.config.get("mapsos", {}).get("export_dir")
    if configured:
        directory = Path(str(configured)).expanduser()
        if not directory.exists():
            return []
        candidates = sorted(directory.glob("*.json"))
        if latest is None:
            return candidates
        return candidates[-latest:] if latest > 0 else []
    return default_export_paths(latest=latest)


def _mapsos_intake_paths(
    atlas: Atlas,
    paths: tuple[str, ...],
    *,
    import_all: bool,
    since: str | None,
) -> list[Path]:
    if paths:
        return [
            Path(path).expanduser()
            for path in paths
            if Path(path).expanduser().exists()
        ]
    configured = atlas.config.get("mapsos", {}).get("intake_dir")
    if configured:
        directory = Path(str(configured)).expanduser()
        if not directory.exists():
            return []
        candidates = sorted(directory.glob("*.md"))
        if since is not None:
            return [path for path in candidates if path.name[:10] >= since]
        if import_all:
            return candidates
        return candidates[-1:] if candidates else []
    candidates = default_intake_paths(since=since if import_all or since else None)
    if since is not None or import_all:
        return candidates
    return candidates[-1:] if candidates else []


@main.group("session-import")
def session_import() -> None:
    """import Claude or Hermes session files into atlas surfaces."""


@session_import.command("claude")
@click.argument("paths", nargs=-1)
@click.option("--latest", default=1, type=int, show_default=True)
@click.option(
    "--all", "import_all", is_flag=True, help="Import all matching Claude sessions."
)
@click.option(
    "--force", is_flag=True, help="Re-import sessions even if already present in atlas."
)
def session_import_claude(
    paths: tuple[str, ...], latest: int, import_all: bool, force: bool
) -> None:
    _run_session_import(
        "claude", paths, latest=latest, import_all=import_all, force=force
    )


@session_import.command("hermes")
@click.argument("paths", nargs=-1)
@click.option("--latest", default=1, type=int, show_default=True)
@click.option(
    "--all", "import_all", is_flag=True, help="Import all matching Hermes sessions."
)
@click.option(
    "--force", is_flag=True, help="Re-import sessions even if already present in atlas."
)
def session_import_hermes(
    paths: tuple[str, ...], latest: int, import_all: bool, force: bool
) -> None:
    _run_session_import(
        "hermes", paths, latest=latest, import_all=import_all, force=force
    )


@main.command("bootstrap-populate")
@click.option("--claude-latest", default=2, type=int, show_default=True)
@click.option("--hermes-latest", default=4, type=int, show_default=True)
@click.option("--mapsos-latest", default=1, type=int, show_default=True)
@click.option("--no-claude", is_flag=True, help="Skip Claude session imports.")
@click.option("--no-hermes", is_flag=True, help="Skip Hermes session imports.")
@click.option("--no-mapsos", is_flag=True, help="Skip mapsOS export imports.")
def bootstrap_populate(
    claude_latest: int,
    hermes_latest: int,
    mapsos_latest: int,
    no_claude: bool,
    no_hermes: bool,
    no_mapsos: bool,
) -> None:
    atlas = get_atlas()
    imported = 0
    if not no_claude:
        claude_paths = default_session_paths("claude", latest=claude_latest)
        if claude_paths:
            result = import_sessions(atlas.root, "claude", claude_paths)
            imported += int(result["count"])
            click.echo(f"claude: imported {result['count']} session(s)")
        else:
            click.echo("claude: no session files found")
    if not no_hermes:
        hermes_paths = default_session_paths("hermes", latest=hermes_latest)
        if hermes_paths:
            result = import_sessions(atlas.root, "hermes", hermes_paths)
            imported += int(result["count"])
            click.echo(f"hermes: imported {result['count']} session(s)")
        else:
            click.echo("hermes: no session files found")
    if not no_mapsos:
        export_paths = _mapsos_export_paths(atlas, latest=mapsos_latest)
        if export_paths:
            result = ingest_mapsos_exports(atlas.root, export_paths)
            imported += int(result["count"])
            click.echo(f"mapsOS: ingested {result['count']} export(s)")
        else:
            click.echo("mapsOS: no export files found")
    atlas.refresh_index()
    click.echo(f"bootstrap-populate: imported {imported} session(s)")


@main.group()
def entities() -> None:
    """entity note maintenance."""


@entities.command("clean-imports")
def entities_clean_imports() -> None:
    atlas = get_atlas()
    result = clean_entity_imports(atlas.root)
    if result["updated"]:
        atlas.refresh_index()
    click.echo(f"cleaned {result['updated']} entity note(s)")
    for path in result["paths"]:
        click.echo(path)


@main.group()
def mapsos() -> None:
    """mapsOS bridge commands."""


@mapsos.command("ingest")
@click.argument("source", required=False, default="-")
@click.option("--daily/--no-daily", "sync_daily", default=True, show_default=True)
@click.option("--tasks/--no-tasks", "sync_tasks", default=True, show_default=True)
@click.option(
    "--snapshot/--no-snapshot", "sync_snapshot", default=True, show_default=True
)
def mapsos_ingest(
    source: str,
    sync_daily: bool,
    sync_tasks: bool,
    sync_snapshot: bool,
) -> None:
    atlas = get_atlas()
    if source == "-" and sys.stdin.isatty():
        raise click.ClickException(
            "provide a JSON file path or pipe mapsOS JSON on stdin"
        )
    try:
        payload = load_mapsos_payload(
            source, None if sys.stdin.isatty() else sys.stdin.read()
        )
    except FileNotFoundError as exc:
        raise click.ClickException(f"mapsOS payload not found: {source}") from exc
    except json.JSONDecodeError as exc:
        raise click.ClickException(
            f"mapsOS payload is not valid JSON: {source}"
        ) from exc
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    result = sync_mapsos_payload(
        atlas.root,
        payload,
        sync_daily=sync_daily,
        sync_tasks=sync_tasks,
        sync_snapshot=sync_snapshot,
    )
    atlas.refresh_index()
    click.echo(result["output"])
    for path in result["paths"]:
        click.echo(path)


@mapsos.command("ingest-intake")
@click.argument("paths", nargs=-1)
@click.option(
    "--all",
    "import_all",
    is_flag=True,
    help="Import all markdown intakes in the configured intake dir.",
)
@click.option("--since", help="Import intake files on or after YYYY-MM-DD.")
def mapsos_ingest_intake(
    paths: tuple[str, ...], import_all: bool, since: str | None
) -> None:
    atlas = get_atlas()
    selected_paths = _mapsos_intake_paths(
        atlas, paths, import_all=import_all, since=since
    )
    if not selected_paths:
        raise click.ClickException("no mapsOS intake markdown files found")
    results = [ingest_mapsos_intake(atlas.root, path) for path in selected_paths]
    atlas.refresh_index()
    total_learnings = sum(int(result["learning_count"]) for result in results)
    click.echo(
        f"mapsOS intake: ingested {len(results)} file(s), {total_learnings} learnings"
    )
    for result in results:
        click.echo(result["output"])


@mapsos.command("ingest-exports")
@click.option(
    "--latest", "latest_only", is_flag=True, help="Only ingest the most recent export."
)
def mapsos_ingest_exports(latest_only: bool) -> None:
    atlas = get_atlas()
    selected_paths = _mapsos_export_paths(atlas, latest=1 if latest_only else None)
    if not selected_paths:
        raise click.ClickException("no mapsOS export files found")
    result = ingest_mapsos_exports(atlas.root, selected_paths)
    atlas.refresh_index()
    click.echo(result["output"])
    for path in result["paths"]:
        click.echo(path)


@mapsos.command("sync-arcs")
def mapsos_sync_arcs() -> None:
    """Sync completed arc tasks back to mapsOS."""
    atlas = get_atlas()
    from .mapsos import sync_arc_updates_from_mapsos

    result = sync_arc_updates_from_mapsos(atlas.root)
    click.echo(result["output"])


@mapsos.command("import-arc")
@click.argument("export_file", required=False, default="-")
def mapsos_import_arc(export_file: str) -> None:
    """Import arc tasks from a mapsOS export JSON file."""
    atlas = get_atlas()
    import json as _json

    if export_file == "-" and sys.stdin.isatty():
        raise click.ClickException(
            "provide a JSON file path or pipe mapsOS export JSON on stdin"
        )
    try:
        raw = (
            sys.stdin.read()
            if export_file == "-"
            else Path(export_file).expanduser().read_text(encoding="utf-8")
        )
        export_data = _json.loads(raw)
    except FileNotFoundError as exc:
        raise click.ClickException(f"export file not found: {export_file}") from exc
    except _json.JSONDecodeError as exc:
        raise click.ClickException(f"invalid JSON: {exc}") from exc
    from .mapsos import import_arc_from_mapsos_export

    result = import_arc_from_mapsos_export(atlas.root, export_data)
    atlas.refresh_index()
    click.echo(result["output"])


@mapsos.command("patterns")
@click.option("--since", help="Only include entries on or after YYYY-MM-DD.")
@click.option(
    "--field",
    type=click.Choice(["state", "sleep", "energy", "pain", "arcs"]),
    help="Summarize just one field.",
)
def mapsos_patterns(since: str | None, field: str | None) -> None:
    from .patterns import entries_since, load_state_log, summarize_patterns

    atlas = get_atlas()
    entries = entries_since(load_state_log(atlas.root), since)
    click.echo(summarize_patterns(entries, field=field))


@main.command("export-tasks")
@click.option(
    "--format",
    "output_format",
    default="taskwarrior",
    type=click.Choice(["taskwarrior"]),
    show_default=True,
)
@click.option("--query", default="status:open", help="Task query expression.")
@click.option("--output", "-o", help="Output file path (default: stdout).")
def export_tasks(output_format: str, query: str, output: str | None) -> None:
    """Export tasks to external formats (taskwarrior)."""
    atlas = get_atlas()
    tasks = query_tasks(atlas.root, query)
    if output_format == "taskwarrior":
        lines = []
        for task in tasks:
            attrs = [f"proj:{task.project}"] if task.project else []
            if task.due:
                attrs.append(f"due:{task.due}")
            priority_map = {"P0": "H", "P1": "M", "P2": "L", "P3": ""}
            tw_priority = priority_map.get(task.priority, "")
            tw_status = "completed" if task.done else "pending"
            tw_tags = " ".join(f"+{attr}" for attr in attrs)
            line = f"{tw_priority} {tw_status} {tw_tags} {task.text}"
            lines.append(line)
        content = "\n".join(lines) + "\n"
    else:
        raise click.ClickException(f"unsupported format: {output_format}")
    if output:
        out_path = Path(output).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
        click.echo(f"exported {len(tasks)} tasks to {out_path}")
    else:
        click.echo(content, nl=False)


@main.command("export")
@click.argument("note_id")
@click.option(
    "--resolve-transclusions",
    is_flag=True,
    help="Resolve ![[note#block]] transclusions.",
)
@click.option(
    "--format",
    "output_format",
    default="markdown",
    type=click.Choice(["markdown", "html"]),
    show_default=True,
)
@click.option("--output", "-o", help="Output file path (default: stdout).")
def export_note(
    note_id: str, resolve_transclusions: bool, output_format: str, output: str | None
) -> None:
    """Export a note with optional transclusion resolution."""
    from .transclusion import export_note_with_transclusions

    atlas = get_atlas()
    if resolve_transclusions:
        result = export_note_with_transclusions(note_id, atlas.root, output_format)
        if not result.get("success"):
            errors = result.get("errors", ["unknown error"])
            raise click.ClickException(f"export failed: {errors[0]}")
        content = result["body"]
    else:
        index = ensure_index_current(atlas)
        note_path = index.find_note_path(note_id)
        if note_path is None:
            raise click.ClickException(f"note not found: {note_id}")
        content = note_path.read_text(encoding="utf-8")
        if output_format == "html":
            from .transclusion import _markdown_to_html

            content = _markdown_to_html(content)
    if output:
        out_path = Path(output).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
        click.echo(f"exported to {out_path}")
    else:
        click.echo(content, nl=False)


@main.group()
def plugin() -> None:
    """plugin commands."""


@plugin.command("list")
def plugin_list() -> None:
    atlas = get_atlas()
    for name in list_plugins(atlas.root):
        click.echo(name)


@plugin.command("run")
@click.argument("name")
@click.argument("args", nargs=-1)
def plugin_run(name: str, args: tuple[str, ...]) -> None:
    atlas = get_atlas()
    payload: dict[str, object] = {
        "command": name,
        "args": parse_plugin_args(args),
    }
    if not sys.stdin.isatty():
        raw_stdin = sys.stdin.read()
        if raw_stdin.strip():
            try:
                decoded = json.loads(raw_stdin)
                if isinstance(decoded, dict):
                    payload.update(decoded)
                else:
                    payload["input"] = decoded
            except json.JSONDecodeError:
                payload["input"] = raw_stdin
    result = run_plugin(atlas.root, name, payload)
    if result.get("output"):
        click.echo(str(result["output"]))
    errors = result.get("errors") or []
    for error in errors:
        click.echo(str(error), err=True)


# ---------------------------------------------------------------------------
# cart graph — graph export
# ---------------------------------------------------------------------------


@main.command("graph")
@click.option(
    "--export",
    "export_path",
    default=None,
    help="Path for graph export (default: graph-export.json or graph-view.html).",
)
@click.option(
    "--format",
    "fmt",
    default="json",
    type=click.Choice(["json", "html"]),
    show_default=True,
)
@click.option("--open", "open_in_browser", is_flag=True, help="Open HTML graph after export.")
def graph_export(export_path: str | None, fmt: str, open_in_browser: bool) -> None:
    """Export the atlas note graph as JSON or an interactive HTML view."""
    import webbrowser

    from .graph_export import load_graph_payload, render_graph_html

    atlas = get_atlas()
    db_path = atlas.root / ".cartographer" / "index.db"
    if not db_path.exists():
        atlas.refresh_index()
    if not db_path.exists():
        raise click.ClickException("atlas index not found — run `cart status` first")
    payload = load_graph_payload(atlas.root)

    out_path = (
        Path(export_path).expanduser()
        if export_path
        else atlas.root / ("graph-view.html" if fmt == "html" else "graph-export.json")
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        out_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    else:
        out_path.write_text(render_graph_html(payload), encoding="utf-8")
    click.echo(
        f"graph exported: {out_path} ({payload['node_count']} nodes, {payload['edge_count']} edges)"
    )
    if open_in_browser:
        if fmt != "html":
            raise click.ClickException("--open only works with --format html")
        webbrowser.open(out_path.resolve().as_uri())


# ---------------------------------------------------------------------------
# cart import — external platform exports
# ---------------------------------------------------------------------------


@main.group("import")
def import_group() -> None:
    """import session history from external platforms (ChatGPT, Claude.ai)."""


def _external_import_sessions(
    sessions: list,
    atlas_root: "Path",
    *,
    force: bool,
) -> "dict[str, Any]":
    from .session_import import _unique

    imported: list = []
    skipped: list = []
    written: list = []
    for sess in sessions:
        result = import_imported_session(atlas_root, sess, force=force)
        if result.get("skipped"):
            skipped.append(result)
        else:
            imported.append(result)
            written.extend(result["written"])
    return {
        "count": len(imported),
        "skipped": len(skipped),
        "written": _unique(written),
        "sessions": imported,
    }


@import_group.command("chatgpt")
@click.argument("export_file", type=click.Path(exists=True))
@click.option(
    "--latest",
    default=None,
    type=int,
    help="Only import the N most recent conversations.",
)
@click.option("--force", is_flag=True, help="Re-import even if already in atlas.")
def import_chatgpt(export_file: str, latest: int | None, force: bool) -> None:
    """Import from a ChatGPT conversations.json export file."""
    path = Path(export_file).expanduser()
    try:
        sessions = parse_chatgpt_export(path)
    except Exception as exc:
        raise click.ClickException(f"failed to parse ChatGPT export: {exc}") from exc
    if latest is not None and latest > 0:
        sessions = sessions[-latest:]
    atlas = get_atlas()
    result = _external_import_sessions(sessions, atlas.root, force=force)
    atlas.refresh_index()
    skipped = result.get("skipped", 0)
    click.echo(
        f"imported {result['count']} ChatGPT conversation(s)"
        + (f", skipped {skipped} already-imported" if skipped else "")
    )
    for sess in result["sessions"]:
        click.echo(f"  {sess['source']} -> {sess['session_note']}")
    if skipped and not force:
        click.echo("  (use --force to re-import skipped)")


@import_group.command("claude-web")
@click.argument("export_file", type=click.Path(exists=True))
@click.option(
    "--latest",
    default=None,
    type=int,
    help="Only import the N most recent conversations.",
)
@click.option("--force", is_flag=True, help="Re-import even if already in atlas.")
def import_claude_web(export_file: str, latest: int | None, force: bool) -> None:
    """Import from a Claude.ai conversations.json export file."""
    path = Path(export_file).expanduser()
    try:
        sessions = parse_claude_web_export(path)
    except Exception as exc:
        raise click.ClickException(f"failed to parse Claude.ai export: {exc}") from exc
    if latest is not None and latest > 0:
        sessions = sessions[-latest:]
    atlas = get_atlas()
    result = _external_import_sessions(sessions, atlas.root, force=force)
    atlas.refresh_index()
    skipped = result.get("skipped", 0)
    click.echo(
        f"imported {result['count']} Claude.ai conversation(s)"
        + (f", skipped {skipped} already-imported" if skipped else "")
    )
    for sess in result["sessions"]:
        click.echo(f"  {sess['source']} -> {sess['session_note']}")
    if skipped and not force:
        click.echo("  (use --force to re-import skipped)")


if __name__ == "__main__":
    main()
