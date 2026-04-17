from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import click

from .agent_memory import (
    append_learning,
    confirm_learnings,
    gc_learnings,
    pending_learning_blocks,
    reject_learnings,
)
from .atlas import Atlas
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
    if "type:task" in expr or any(
        token in expr for token in ("priority:", "project:", "due:")
    ):
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
def query(expression: tuple[str, ...]) -> None:
    atlas = get_atlas()
    expr = " ".join(expression)
    results = resolve_query_paths(atlas, expr)
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
    help="Path for JSON export (default: ~/atlas/graph-export.json).",
)
@click.option(
    "--format", "fmt", default="json", type=click.Choice(["json"]), show_default=True
)
def graph_export(export_path: str | None, fmt: str) -> None:
    """Export the atlas note graph as a JSON file (nodes + edges)."""
    import sqlite3 as _sqlite3

    atlas = get_atlas()
    db_path = atlas.root / ".cartographer" / "index.db"
    if not db_path.exists():
        atlas.refresh_index()
    if not db_path.exists():
        raise click.ClickException("atlas index not found — run `cart status` first")

    con = _sqlite3.connect(str(db_path))
    con.row_factory = _sqlite3.Row
    try:
        rows = con.execute(
            "SELECT id, title, type, tags, links FROM notes ORDER BY type, id"
        ).fetchall()
        ref_rows = con.execute(
            "SELECT DISTINCT from_note, to_note FROM block_refs WHERE from_note != to_note"
        ).fetchall()
    finally:
        con.close()

    nodes = []
    for row in rows:
        try:
            tags = json.loads(row["tags"]) if row["tags"] else []
        except Exception:
            tags = []
        nodes.append(
            {
                "id": row["id"],
                "title": row["title"] or row["id"],
                "type": row["type"] or "note",
                "tags": tags,
            }
        )

    edges = [{"source": r["from_note"], "target": r["to_note"]} for r in ref_rows]

    payload = {
        "generated": _today_string(),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": nodes,
        "edges": edges,
    }

    out_path = (
        Path(export_path).expanduser()
        if export_path
        else atlas.root / "graph-export.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    click.echo(f"graph exported: {out_path} ({len(nodes)} nodes, {len(edges)} edges)")


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
