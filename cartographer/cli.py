from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import click

from .agent_memory import append_learning, gc_learnings
from .atlas import Atlas
from .index import Index
from .mapsos import load_mapsos_payload, sync_mapsos_payload
from .notes import Note
from .obsidian import sync as obsidian_sync_impl
from .plugins import (
    apply_writes,
    list_plugins,
    parse_plugin_args,
    run_plugin,
)
from .tasks import append_task, mark_done, query_tasks, sort_tasks
from .vimwiki import patch_vimrc
from .worklog import Worklog


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


def resolve_query_paths(atlas: Atlas, expr: str) -> list[str]:
    if "type:task" in expr or any(token in expr for token in ("priority:", "project:", "due:")):
        return sorted({str(task.path) for task in query_tasks(atlas.root, expr)})
    return ensure_index_current(atlas).query(expr)


def load_note_payload(path: Path) -> dict[str, object]:
    note = Note.from_file(path)
    return {
        "id": str(note.frontmatter.get("id") or path.stem),
        "path": str(path),
        "frontmatter": note.frontmatter,
        "content": note.body,
    }


@click.group()
def main() -> None:
    """cartographer — maps your knowledge."""


@main.command()
@click.argument("path", required=False, default="~/atlas")
def init(path: str) -> None:
    atlas = Atlas(root=path)
    result = atlas.init()
    click.echo(f"atlas: {result['root']}")
    click.echo(f"git: {result['git']}")
    click.echo(f"vimwiki: {result['vimwiki']}")
    for warning in result.get("backup_warnings", []):
        click.echo(f"warning: {warning}", err=True)
    if result["vault"]:
        click.echo(f"obsidian: detected {result['vault']}")
    click.echo(
        "index: "
        f"{result['index']['notes']} notes, {result['index']['blocks']} blocks, {result['index']['refs']} refs"
    )


@main.command()
def status() -> None:
    atlas = get_atlas()
    info = atlas.status()
    last_rebuild = info["index"]["last_rebuild"]
    last_rebuild_text = (
        "never"
        if last_rebuild is None
        else datetime.fromtimestamp(last_rebuild).strftime("%Y-%m-%d %H:%M")
    )
    tasks = info["tasks"]
    priorities = tasks["by_priority"]
    worklog = info["worklog"]
    click.echo(f"atlas: {info['root']} ({info['note_count']} notes, {info['atlas_size']})")
    click.echo(f"index: rebuilt {last_rebuild_text}")
    click.echo(
        "tasks: "
        f"{tasks['open']} open ({priorities['P0']} P0, {priorities['P1']} P1, "
        f"{priorities['P2']} P2, {priorities['P3']} P3)"
    )
    click.echo(
        "agents: "
        f"hermes {info['agents']['hermes_sessions']} sessions, "
        f"codex {info['agents']['codex_sessions']} sessions"
    )
    click.echo(f"git: {info['git']}")
    click.echo(f"worklog: {len(worklog['in_progress'])} in-progress tasks")


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


@main.command()
@click.argument("note_id")
def edit(note_id: str) -> None:
    _open_note(note_id)


@main.command()
@click.argument("expression", nargs=-1, required=True)
def query(expression: tuple[str, ...]) -> None:
    atlas = get_atlas()
    expr = " ".join(expression)
    results = resolve_query_paths(atlas, expr)
    for result in results:
        click.echo(result)


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
def todo_list() -> None:
    atlas = get_atlas()
    for task in sort_tasks(query_tasks(atlas.root, "status:open")):
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
def todo_query(expression: tuple[str, ...]) -> None:
    atlas = get_atlas()
    for task in query_tasks(atlas.root, " ".join(expression)):
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
def worklog_status() -> None:
    atlas = get_atlas()
    data = Worklog(atlas.worklog_db_path).status()
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
            + datetime.fromtimestamp(status_info["last_rebuild"]).isoformat(timespec="seconds")
        )


@main.command("learn")
@click.argument("text")
@click.option("--topic", default="general", show_default=True)
@click.option("--agent", default="hermes", show_default=True)
@click.option("--confidence", default=0.85, type=float, show_default=True)
@click.option("--entity")
def learn(
    text: str,
    topic: str,
    agent: str,
    confidence: float,
    entity: str | None,
) -> None:
    atlas = get_atlas()
    result = append_learning(
        atlas.root,
        agent=agent,
        topic=topic,
        text=text,
        confidence=confidence,
        entity=entity,
    )
    applied = apply_writes(atlas.root, result["writes"], plugin_name="learn")
    atlas.refresh_index()
    click.echo(f"learned {topic} -> {applied[0]}")


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
        raise click.ClickException(f"session file is not valid JSON: {source_path}") from exc
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
    notes = [load_note_payload(Path(path).expanduser()) for path in paths if Path(path).exists()]
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
            [{"path": write_path, "content": output + ("\n" if not output.endswith("\n") else "")}],
            plugin_name="summarize",
        )
    click.echo(output)


@main.command("vimwiki-sync")
def vimwiki_sync() -> None:
    atlas = get_atlas()
    status_text = patch_vimrc(Path.home() / ".vimrc", atlas.root)
    click.echo(status_text)


@main.command("obsidian-sync")
def obsidian_sync() -> None:
    atlas = get_atlas()
    vault = atlas.config.get("obsidian", {}).get("vault")
    if not vault:
        raise click.ClickException("no obsidian vault configured")
    destination = obsidian_sync_impl(atlas.root, Path(str(vault)).expanduser())
    click.echo(destination)


@main.group()
def mapsos() -> None:
    """mapsOS bridge commands."""


@mapsos.command("ingest")
@click.argument("source", required=False, default="-")
@click.option("--daily/--no-daily", "sync_daily", default=True, show_default=True)
@click.option("--tasks/--no-tasks", "sync_tasks", default=True, show_default=True)
@click.option("--snapshot/--no-snapshot", "sync_snapshot", default=True, show_default=True)
def mapsos_ingest(
    source: str,
    sync_daily: bool,
    sync_tasks: bool,
    sync_snapshot: bool,
) -> None:
    atlas = get_atlas()
    if source == "-" and sys.stdin.isatty():
        raise click.ClickException("provide a JSON file path or pipe mapsOS JSON on stdin")
    try:
        payload = load_mapsos_payload(source, None if sys.stdin.isatty() else sys.stdin.read())
    except FileNotFoundError as exc:
        raise click.ClickException(f"mapsOS payload not found: {source}") from exc
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"mapsOS payload is not valid JSON: {source}") from exc
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


if __name__ == "__main__":
    main()
