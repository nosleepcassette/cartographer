from __future__ import annotations

import argparse
import copy
from dataclasses import asdict
import json
import shlex
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import click
from click.core import ParameterSource
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
from .notes import Note, parse_link_target
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
from .therapy import (
    build_therapy_handoff_payload,
    build_therapy_review_payload,
    counter_evidence_payload,
    therapy_plugin_status,
    write_therapy_handoff,
    write_therapy_review,
)
from .vimwiki import patch_vimrc
from .worklog import Worklog
from .working_set import add_entry as add_working_set_entry
from .working_set import gc_entries as gc_working_set_entries
from .working_set import list_entries as list_working_set_entries
from .working_set import working_set_stats
from .wires import (
    VALID_AVOIDANCE_RISKS,
    VALID_CURRENT_STATES,
    VALID_EMOTIONAL_VALENCES,
    VALID_ENERGY_IMPACTS,
    VALID_WIRE_PREDICATES,
    WIRE_PATTERN,
    insert_wire_comment,
    parse_wire_comments,
    remove_wire_spans,
    render_wire_comment,
)

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
    wire_status = {
        "count": 0,
        "issue_count": 0,
    }
    if initialized and atlas.index_db_path.exists():
        index = Index(atlas.root)
        index_status = index.status()
        wire_status["count"] = int(index_status.get("wires", 0))
        wire_status["issue_count"] = int(index_status.get("wire_issues", 0))
        doctor_payload = index.wire_doctor()
        wire_status["issue_count"] = int(doctor_payload["issue_count"])
        if doctor_payload["issue_count"]:
            warnings.append(
                f"wire doctor found {doctor_payload['issue_count']} issue(s); run `cart wire doctor`"
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
        "wires": wire_status,
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


def _embedding_query_paths(atlas: Atlas, expr: str) -> list[str]:
    if not _supports_qmd_query(expr):
        return []
    try:
        from .embed import semantic_query_paths
    except Exception:
        return []
    return semantic_query_paths(atlas.root, expr, top_k=20)


def resolve_query_paths(atlas: Atlas, expr: str) -> list[str]:
    if "type:task" in expr or any(
        token in expr for token in ("priority:", "project:", "due:")
    ):
        return sorted({str(task.path) for task in query_tasks(atlas.root, expr)})
    qmd_paths = _qmd_query_paths(atlas, expr)
    if qmd_paths:
        return qmd_paths
    embedding_paths = _embedding_query_paths(atlas, expr)
    if embedding_paths:
        return embedding_paths
    return ensure_index_current(atlas).query(expr)


def load_note_payload(path: Path) -> dict[str, object]:
    note = Note.from_file(path)
    return {
        "id": str(note.frontmatter.get("id") or path.stem),
        "path": str(path),
        "frontmatter": note.frontmatter,
        "content": note.body,
    }


def _record_path_accesses(
    atlas: Atlas,
    paths: list[str] | tuple[str, ...],
    *,
    access_type: str,
) -> None:
    note_ids: list[str] = []
    seen: set[str] = set()
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists():
            continue
        try:
            note = Note.from_file(path)
        except Exception:
            continue
        note_id = str(note.frontmatter.get("id") or path.stem)
        if note_id in seen:
            continue
        seen.add(note_id)
        note_ids.append(note_id)
    if not note_ids:
        return
    try:
        Index(atlas.root).record_accesses(note_ids, access_type=access_type)
    except Exception:
        return


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


def _resolve_note_or_block_ref(
    index: Index,
    ref: str,
    *,
    require_block: bool = False,
) -> tuple[str, str | None, Path]:
    note_ref, block_id = parse_link_target(ref)
    canonical_note = index.canonicalize_note_ref(note_ref)
    if canonical_note is None:
        raise click.ClickException(f"note not found: {note_ref}")
    path = index.find_note_path(canonical_note)
    if path is None:
        raise click.ClickException(f"note not found: {canonical_note}")
    if require_block and block_id is None:
        raise click.ClickException(f"block reference required: {ref}")
    if block_id is not None and not index.block_exists(canonical_note, block_id):
        raise click.ClickException(f"block not found: {canonical_note}#{block_id}")
    return canonical_note, block_id, path


def _render_note_or_block(note_id: str, block_id: str | None) -> str:
    return note_id if block_id is None else f"{note_id}#{block_id}"


def _wire_direction(incoming: bool, outgoing: bool) -> str:
    if incoming and not outgoing:
        return "incoming"
    if outgoing and not incoming:
        return "outgoing"
    return "both"


def _wire_predicate_and_relationship(
    predicate: str | None,
    relationship: str | None,
) -> tuple[str, str | None]:
    resolved = (predicate or relationship or "").strip()
    if not resolved:
        raise click.ClickException("wire add requires --predicate or --relationship")
    if resolved not in VALID_WIRE_PREDICATES:
        raise click.ClickException(
            f"invalid wire predicate/relationship: {resolved}. See `cart wire predicates`."
        )
    return resolved, (relationship.strip() if relationship else resolved)


def _wire_metadata_fields(wire: dict[str, Any]) -> list[str]:
    fields: list[str] = []
    if wire.get("emotional_valence"):
        fields.append(f"valence={wire['emotional_valence']}")
    if wire.get("energy_impact"):
        fields.append(f"energy={wire['energy_impact']}")
    if wire.get("avoidance_risk"):
        fields.append(f"avoidance={wire['avoidance_risk']}")
    if wire.get("current_state"):
        fields.append(f"state={wire['current_state']}")
    if wire.get("growth_edge") is True:
        fields.append("growth-edge")
    if wire.get("since"):
        fields.append(f"since={wire['since']}")
    if wire.get("until"):
        fields.append(f"until={wire['until']}")
    return fields


def _render_wire_summary(wire: dict[str, Any]) -> str:
    source_ref = _render_note_or_block(
        str(wire["source_note"]),
        None if wire["source_block"] is None else str(wire["source_block"]),
    )
    target_ref = _render_note_or_block(
        str(wire["target_note"]),
        None if wire["target_block"] is None else str(wire["target_block"]),
    )
    metadata = _wire_metadata_fields(wire)
    suffix = "  [bi]" if wire.get("bidirectional") else ""
    if metadata:
        suffix += "  {" + ", ".join(metadata) + "}"
    if wire.get("valence_note"):
        suffix += f"  — {wire['valence_note']}"
    return f"{source_ref} --{wire['predicate']}--> {target_ref}{suffix}"


def _replace_or_append_wire_comment(
    note: Note,
    *,
    source_block: str | None,
    target_note: str,
    target_block: str | None,
    predicate: str,
    comment: str,
) -> tuple[bool, bool]:
    wires, _ = parse_wire_comments(
        note.body,
        note_id=str(note.frontmatter.get("id") or note.path.stem),
        path=note.path,
    )
    for wire in wires:
        if wire.source_block != source_block:
            continue
        if wire.target_note != target_note or wire.target_block != target_block:
            continue
        if wire.predicate != predicate:
            continue
        if wire.raw == comment:
            return False, False
        note.body = note.body[: wire.start] + comment + note.body[wire.end :]
        return False, True
    insert_wire_comment(note, source_block=source_block, comment=comment)
    return True, False


def _wire_gc_plan(index: Index) -> list[dict[str, Any]]:
    payload = index.wire_doctor()
    issues_by_path: dict[str, list[dict[str, Any]]] = {}
    for issue in payload["issues"]:
        issues_by_path.setdefault(str(issue["path"]), []).append(issue)

    plan: list[dict[str, Any]] = []
    removable_codes = {
        "missing_target",
        "missing_predicate",
        "invalid_target",
        "invalid_predicate",
        "orphan_target_note",
        "orphan_target_block",
    }
    for path_text, issues in sorted(issues_by_path.items()):
        path = Path(path_text)
        if not path.exists():
            continue
        note = Note.from_file(path)
        note_id = str(note.frontmatter.get("id") or path.stem)
        wires, _ = parse_wire_comments(note.body, note_id=note_id, path=path)
        wire_issue_keys = {
            (
                str(issue["code"]),
                int(issue["line"]),
                str(issue.get("target_note") or ""),
                str(issue.get("target_block") or ""),
                str(issue.get("predicate") or ""),
            )
            for issue in issues
            if str(issue["code"]) in removable_codes
        }
        malformed_issue_lines = {
            int(issue["line"])
            for issue in issues
            if str(issue["code"]) in {"missing_target", "missing_predicate", "invalid_target"}
        }
        spans: set[tuple[int, int]] = set()
        lines: set[int] = set()

        for wire in wires:
            wire_key = (
                "invalid_predicate" if wire.predicate not in VALID_WIRE_PREDICATES else "",
                wire.line,
                wire.target_note,
                wire.target_block or "",
                wire.predicate,
            )
            if wire_key in wire_issue_keys:
                spans.add((wire.start, wire.end))
                lines.add(wire.line)
                continue
            orphan_note_key = (
                "orphan_target_note",
                wire.line,
                wire.target_note,
                wire.target_block or "",
                wire.predicate,
            )
            orphan_block_key = (
                "orphan_target_block",
                wire.line,
                wire.target_note,
                wire.target_block or "",
                wire.predicate,
            )
            if orphan_note_key in wire_issue_keys or orphan_block_key in wire_issue_keys:
                spans.add((wire.start, wire.end))
                lines.add(wire.line)

        for match in WIRE_PATTERN.finditer(note.body):
            line = note.body.count("\n", 0, match.start()) + 1
            if line in malformed_issue_lines:
                spans.add((match.start(), match.end()))
                lines.add(line)

        if spans:
            plan.append(
                {
                    "path": str(path),
                    "line_numbers": sorted(lines),
                    "span_count": len(spans),
                    "spans": sorted(spans),
                }
            )
    return plan


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
    wires = payload["wires"]
    click.echo(
        "wires: "
        f"{'warn' if wires['issue_count'] else 'ok'}  "
        f"{wires['count']} indexed  issues={wires['issue_count']}"
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
@click.option("-p", "--priority", default="P2", show_default=True, help="Task priority (P0-P4). Default is P2.")
@click.option("--agent", default="hermes", show_default=True, help="Agent origin for this note.")
@click.option("--from-stdin", is_flag=True, help="Append stdin content to the new note body.")
def new(parts: tuple[str, ...], priority: str, agent: str, from_stdin: bool) -> None:
    """Create a new note or task.

    PARTS: either a title (creates 'note' type), or TYPE and TITLE separately.

    Example: cart new "My note" → creates a note titled "My note"
    Example: cart new project "Foo" → creates a project note titled "Foo"
    """
    if len(parts) == 1:
        note_type = "note"
        title = parts[0]
    else:
        note_type = parts[0]
        title = " ".join(parts[1:])
    atlas = get_atlas()
    body_override = sys.stdin.read() if from_stdin else None
    try:
        path = atlas.create_note(
            note_type,
            title,
            priority=priority,
            agent=agent,
            body_override=body_override,
        )
        if not from_stdin:
            atlas.open_in_editor(path)
            atlas.finalize_note(path)
            atlas.refresh_index()
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(path)


def _open_note(note_id: str) -> None:
    atlas = get_atlas()
    path = atlas.resolve_note_path(note_id)
    if path is None:
        raise click.ClickException(f"note not found: {note_id}")
    atlas.open_in_editor(path)
    try:
        atlas.finalize_note(path)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    atlas.refresh_index()
    try:
        Index(atlas.root).record_accesses([note_id], access_type="open")
    except Exception:
        pass
    click.echo(path)


@main.command()
@click.argument("note_id")
def open(note_id: str) -> None:
    _open_note(note_id)


@main.command("ls")
@click.option("--type", "note_type", help="Filter by note type (e.g., project, entity, session).")
@click.option("--limit", default=20, type=int, show_default=True, help="Maximum notes to display.")
def ls_notes(note_type: str | None, limit: int) -> None:
    """List notes with ID, type, and title.

    Example: cart ls
    Example: cart ls --type project
    Example: cart ls --limit 50
    """
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


def _render_routed_results(payload: dict[str, Any]) -> None:
    click.echo(f"routes: {', '.join(payload['routes'])}")
    click.echo("")
    for item in payload["results"]:
        path_text = f" ({item['path']})" if item.get("path") else ""
        click.echo(f"[{item['shelf']}] {item['label']}{path_text}")
        click.echo(item["text"])
        click.echo("")


@main.command()
@click.argument("expression", nargs=-1, required=True)
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
@click.option("--route", "route_mode", is_flag=True, help="Route the query across operating-truth/profile/graph/corpus shelves.")
def query(expression: tuple[str, ...], as_json: bool, route_mode: bool) -> None:
    """Query atlas notes by structured tokens or plain text.

    Use structured queries like: type:project tag:urgent
    Or free-text: cart query "machine learning"
    """
    atlas = get_atlas()
    expr = " ".join(expression)
    if route_mode:
        from .query_router import route_query

        payload = route_query(atlas.root, expr)
        _record_path_accesses(
            atlas,
            [
                str(item.get("path"))
                for item in payload.get("results", [])
                if isinstance(item, dict) and item.get("path")
            ],
            access_type="query-route",
        )
        if as_json:
            _emit_json(
                _with_schema(
                    {
                        "expression": expr,
                        "route": True,
                        **payload,
                    },
                    surface="query",
                )
            )
            return
        _render_routed_results(payload)
        return
    results = resolve_query_paths(atlas, expr)
    _record_path_accesses(atlas, results, access_type="query")
    if as_json:
        _emit_json(
            _with_schema(
                {"expression": expr, "results": results, "route": False},
                surface="query",
            )
        )
        return
    for result in results:
        click.echo(result)


@main.group("operating-truth", invoke_without_command=True)
@click.option("--type", "entry_type", default=None, help="Filter to one operating-truth type.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
@click.pass_context
def operating_truth_group(
    ctx: click.Context,
    entry_type: str | None,
    as_json: bool,
) -> None:
    """Show or manage the operational state shelf."""
    if ctx.invoked_subcommand is not None:
        return
    atlas = get_atlas()
    from .operating_truth import list_operating_truth

    items = list_operating_truth(atlas.root, entry_type=entry_type)
    if as_json:
        _emit_json(
            _with_schema(
                {
                    "type": entry_type,
                    "entries": items,
                },
                surface="operating-truth",
            )
        )
        return
    if not items:
        click.echo("no operating truth entries")
        return
    for item in items:
        click.echo(f"{item['id']}  {item['type']:<20} {item['content']}")


@operating_truth_group.command("set")
@click.argument(
    "entry_type",
    type=click.Choice(["active_work"]),
)
@click.argument("content")
def operating_truth_set(entry_type: str, content: str) -> None:
    atlas = get_atlas()
    from .operating_truth import set_operating_truth

    payload = set_operating_truth(atlas.root, entry_type, content)
    click.echo(f"{payload['id']}  {payload['type']}  {payload['content']}")


@operating_truth_group.command("add")
@click.argument(
    "entry_type",
    type=click.Choice(
        ["active_work", "open_decision", "current_commitment", "commitment", "next_step", "external_owner"]
    ),
)
@click.argument("content")
@click.option("--priority", default=1, type=int, show_default=True)
def operating_truth_add(entry_type: str, content: str, priority: int) -> None:
    atlas = get_atlas()
    from .operating_truth import add_operating_truth

    payload = add_operating_truth(atlas.root, entry_type, content, priority=priority)
    click.echo(f"{payload['id']}  {payload['type']}  {payload['content']}")


@operating_truth_group.command("done")
@click.argument("entry_id")
def operating_truth_done(entry_id: str) -> None:
    atlas = get_atlas()
    from .operating_truth import mark_operating_truth_status

    payload = mark_operating_truth_status(atlas.root, entry_id, status="completed")
    click.echo(f"completed: {payload['id']}")


@operating_truth_group.command("expire")
@click.argument("entry_id")
def operating_truth_expire(entry_id: str) -> None:
    atlas = get_atlas()
    from .operating_truth import mark_operating_truth_status

    payload = mark_operating_truth_status(atlas.root, entry_id, status="expired")
    click.echo(f"expired: {payload['id']}")


@operating_truth_group.command("history")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def operating_truth_history_command(as_json: bool) -> None:
    atlas = get_atlas()
    from .operating_truth import operating_truth_history

    items = operating_truth_history(atlas.root)
    if as_json:
        _emit_json(_with_schema({"entries": items}, surface="operating-truth.history"))
        return
    if not items:
        click.echo("no operating truth history")
        return
    for item in items:
        click.echo(f"{item['id']}  {item['status']:<10} {item['type']:<20} {item['content']}")


@main.command("think")
@click.argument("note_id")
@click.option("--depth", type=int, default=None, help="Traversal depth.")
@click.option("--decay", type=float, default=None, help="Activation decay per hop.")
@click.option(
    "--no-emotional-weight",
    is_flag=True,
    help="Ignore emotional valence in wire weights.",
)
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def think_command(
    note_id: str,
    depth: int | None,
    decay: float | None,
    no_emotional_weight: bool,
    as_json: bool,
) -> None:
    """Spreading activation from a note - explore what's connected through the graph."""
    atlas = get_atlas()
    ensure_index_current(atlas)
    from .think import configured_think_settings, spreading_activation

    settings = configured_think_settings(atlas.root)
    try:
        resolved_depth = depth if depth is not None else int(settings.get("default_depth", 3))
    except (TypeError, ValueError):
        resolved_depth = 3
    try:
        resolved_decay = decay if decay is not None else float(settings.get("default_decay", 0.85))
    except (TypeError, ValueError):
        resolved_decay = 0.85
    emotional_weight = not no_emotional_weight and bool(settings.get("emotional_weighting", True))
    try:
        results = spreading_activation(
            atlas.root,
            note_id,
            depth=resolved_depth,
            decay=resolved_decay,
            emotional_weight=emotional_weight,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        _emit_json(
            _with_schema(
                {
                    "note_id": note_id,
                    "depth": resolved_depth,
                    "decay": resolved_decay,
                    "emotional_weight": emotional_weight,
                    "results": results,
                },
                surface="think",
            )
        )
        return
    click.echo(
        f"{note_id} - spreading activation (depth={resolved_depth}, decay={resolved_decay:.2f})"
    )
    click.echo("")
    for item in results:
        path_text = " -> ".join(item["path_ids"])
        hops = int(item["depth"])
        click.echo(
            f"{item['activation']:>5.2f}  {item['note_id']:<20} [{hops} hops: {path_text}]"
        )


@main.command("discover")
@click.option("--threshold", type=float, default=None, help="Minimum similarity to propose.")
@click.option("--accept", is_flag=True, help="Auto-create wires for all proposals.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def discover_command(threshold: float | None, accept: bool, as_json: bool) -> None:
    """Find similar but unwired note pairs - propose new connections."""
    atlas = get_atlas()
    ensure_index_current(atlas)
    from .discover import accept_bridge_proposals, configured_discover_settings, discover_bridges

    settings = configured_discover_settings(atlas.root)
    try:
        resolved_threshold = threshold if threshold is not None else float(settings.get("threshold", 0.6))
    except (TypeError, ValueError):
        resolved_threshold = 0.6
    try:
        max_proposals = int(settings.get("max_proposals", 20))
    except (TypeError, ValueError):
        max_proposals = 20
    proposals = discover_bridges(
        atlas.root,
        threshold=resolved_threshold,
        max_proposals=max_proposals,
    )
    accepted_count = 0
    if accept:
        accepted_count = accept_bridge_proposals(atlas.root, proposals)
    if as_json:
        _emit_json(
            _with_schema(
                {
                    "threshold": resolved_threshold,
                    "accept": accept,
                    "accepted_count": accepted_count,
                    "proposals": proposals,
                },
                surface="discover",
            )
        )
        return
    click.echo(f"bridge proposals (threshold={resolved_threshold:.2f})")
    click.echo("")
    for proposal in proposals:
        reasons = proposal["reasons"]
        reason_parts: list[str] = []
        if reasons["tags"]:
            reason_parts.append("tags: " + ", ".join(reasons["tags"][:3]))
        if reasons["links"]:
            reason_parts.append("links: " + ", ".join(reasons["links"][:3]))
        if reasons["keywords"]:
            reason_parts.append("keywords: " + ", ".join(reasons["keywords"][:4]))
        if reasons["type_match"]:
            reason_parts.append(f"type: {proposal['left_type']}")
        click.echo(
            f"{proposal['score']:>5.2f}  {proposal['left_id']} <-> {proposal['right_id']}  "
            + " | ".join(reason_parts)
        )
    click.echo("")
    if accept:
        click.echo(f"accepted {accepted_count} proposal(s).")
    else:
        click.echo(f"{len(proposals)} proposals. Run with --accept to create wires.")


def _walk_metadata_summary(item: dict[str, Any]) -> str:
    fields: list[str] = []
    if item.get("emotional_valence"):
        fields.append(f"valence={item['emotional_valence']}")
    if item.get("energy_impact"):
        fields.append(f"energy={item['energy_impact']}")
    if item.get("avoidance_risk"):
        fields.append(f"avoidance={item['avoidance_risk']}")
    if item.get("current_state"):
        fields.append(f"state={item['current_state']}")
    if item.get("growth_edge"):
        fields.append("growth-edge")
    return ", ".join(fields)


@main.command("walk")
@click.argument("note_id")
@click.option("--depth", default=2, type=int, show_default=True, help="Walk depth.")
@click.option(
    "--avoidance-only",
    type=click.Choice(["high", "medium", "low"]),
    help="Only follow wires with this avoidance risk or higher.",
)
@click.option("--growth-edges", is_flag=True, help="Only follow growth-edge wires.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def walk_command(
    note_id: str,
    depth: int,
    avoidance_only: str | None,
    growth_edges: bool,
    as_json: bool,
) -> None:
    """Walk the atlas graph from a note - explore its wire neighborhood."""
    atlas = get_atlas()
    ensure_index_current(atlas)
    from .walk import walk_atlas

    try:
        traversals = walk_atlas(
            atlas.root,
            note_id,
            depth=depth,
            filter_avoidance=avoidance_only,
            filter_growth_edge=growth_edges,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        _emit_json(
            _with_schema(
                {
                    "note_id": note_id,
                    "depth": depth,
                    "avoidance_only": avoidance_only,
                    "growth_edges": growth_edges,
                    "traversals": traversals,
                },
                surface="walk",
            )
        )
        return
    click.echo(f"{note_id} - graph walk (depth={depth})")
    click.echo("")
    current_depth = None
    for item in traversals:
        if item["depth"] != current_depth:
            current_depth = item["depth"]
            if current_depth != 1:
                click.echo("")
            click.echo(f"depth {current_depth}:")
        if item["direction"] == "outgoing":
            line = f"  {item['from_note']} ->{item['predicate']}-> {item['to_note']}"
        else:
            line = f"  {item['from_note']} <-{item['predicate']}<- {item['to_note']}"
        metadata = _walk_metadata_summary(item)
        if metadata:
            line += f"  {{{metadata}}}"
        click.echo(line)


@main.command("embed")
@click.option("--force", is_flag=True, help="Re-embed all notes, not just missing or stale ones.")
@click.option("--model", default=None, help="Embedding model name override.")
def embed_command(force: bool, model: str | None) -> None:
    """Compute and store embeddings for atlas notes."""
    atlas = get_atlas()
    ensure_index_current(atlas)
    from .embed import configured_backend, embed_all_notes, is_fastembed_available

    if not is_fastembed_available():
        click.echo("fastembed not installed. Run: pip install 'fastembed>=0.5.1'")
        return
    backend = configured_backend(atlas.root, model_name=model)
    embedded_count = embed_all_notes(atlas.root, backend=backend, force=force)
    click.echo(
        f"embeddings updated: {embedded_count} note(s) using {backend.model_name}"
    )


@main.command("stats")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def stats_command(as_json: bool) -> None:
    """Atlas health dashboard - growth, connectivity, topology, warnings."""
    atlas = get_atlas()
    ensure_index_current(atlas)
    from .stats import atlas_stats, render_stats_text

    payload = atlas_stats(atlas.root)
    if as_json:
        _emit_json(_with_schema(payload, surface="stats"))
        return
    click.echo(render_stats_text(payload), nl=False)


@main.command("temporal-patterns")
@click.option(
    "--signal",
    type=click.Choice(["state", "wires", "sessions", "daily", "access", "all"]),
    default="all",
    show_default=True,
    help="Which signal domain to analyze.",
)
@click.option("--lead", default=48, type=int, show_default=True, help="Lead time in hours.")
@click.option("--min-n", default=3, type=int, show_default=True, help="Minimum aligned buckets required.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable output.")
@click.option("--write", "write_report_flag", is_flag=True, help="Write the report to the configured temporal patterns directory.")
def temporal_patterns_command(
    signal: str,
    lead: int,
    min_n: int,
    as_json: bool,
    write_report_flag: bool,
) -> None:
    """Detect cross-dimensional temporal correlations across the atlas."""
    atlas = get_atlas()
    ensure_index_current(atlas)
    from .temporal_patterns import TemporalPatternDetector

    detector = TemporalPatternDetector(atlas.root)
    try:
        patterns = detector.detect_all_patterns(
            lead_hours=lead,
            min_n=min_n,
            signal_domain=signal,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    written_path: Path | None = None
    if write_report_flag:
        output_dir = Path(
            str(detector.config.get("output_dir") or "ref/temporal-patterns")
        ).expanduser()
        if not output_dir.is_absolute():
            output_dir = atlas.root / output_dir
        written_path = detector.write_report(patterns, output_dir)

    payload = {
        "signal": signal,
        "lead_hours": lead,
        "min_n": min_n,
        "pattern_count": len(patterns),
        "patterns": [asdict(pattern) for pattern in patterns],
        "summary": detector.quick_summary(),
    }
    if written_path is not None:
        payload["written"] = str(written_path)

    if as_json:
        _emit_json(_with_schema(payload, surface="temporal-patterns"))
        return

    if written_path is not None:
        click.echo(f"written: {written_path}")
    click.echo(detector.format_report(patterns), nl=False)


@main.command("supersede")
@click.argument("old_note_id")
@click.argument("new_note_id")
def supersede_command(old_note_id: str, new_note_id: str) -> None:
    """Mark one note as superseded by another."""
    atlas = get_atlas()
    from .temporal_truth import supersede_notes

    payload = supersede_notes(atlas.root, old_note_id, new_note_id)
    click.echo(f"superseded: {payload['old_note']} -> {payload['new_note']}")


@main.command("history")
@click.argument("note_id")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def history_command(note_id: str, as_json: bool) -> None:
    """Show a note's supersession chain."""
    atlas = get_atlas()
    from .temporal_truth import temporal_history

    items = temporal_history(atlas.root, note_id)
    if as_json:
        _emit_json(_with_schema({"note_id": note_id, "history": items}, surface="history"))
        return
    for item in items:
        status = "current" if item["is_current"] else "historical"
        click.echo(f"{item['id']:<24} {status:<10} {item['valid_from'] or '-'} -> {item['valid_to'] or 'now'}")


@main.command("conflicts")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def conflicts_command(as_json: bool) -> None:
    """Surface current-truth conflicts for human review."""
    atlas = get_atlas()
    ensure_index_current(atlas)
    from .temporal_truth import find_conflicts

    items = find_conflicts(atlas.root)
    if as_json:
        _emit_json(_with_schema({"conflicts": items}, surface="conflicts"))
        return
    if not items:
        click.echo("no temporal conflicts found")
        return
    for item in items:
        click.echo(f"{item['type']}: {item['group']} -> {', '.join(item['notes'])}")


@main.command("stale")
@click.option("--days", default=None, type=int, help="Override stale threshold in days.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def stale_command(days: int | None, as_json: bool) -> None:
    """Show current notes that may need temporal review."""
    atlas = get_atlas()
    ensure_index_current(atlas)
    from .temporal_truth import find_stale_notes

    items = find_stale_notes(atlas.root, threshold_days=days)
    if as_json:
        _emit_json(_with_schema({"days": days, "notes": items}, surface="stale"))
        return
    if not items:
        click.echo("no stale notes found")
        return
    for item in items:
        click.echo(f"{item['id']:<24} {item['type']:<12} {item['path']}")


@main.command("delete")
@click.argument("note_id")
@click.option("--force", is_flag=True, help="Skip confirmation.")
@click.option("--no-cascade", is_flag=True, help="Delete the note without cleaning links in other notes.")
@click.option("--archive", is_flag=True, help="Archive the note instead of deleting it.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def delete_command(
    note_id: str,
    force: bool,
    no_cascade: bool,
    archive: bool,
    as_json: bool,
) -> None:
    """Delete or archive a note with impact analysis."""
    atlas = get_atlas()
    ensure_index_current(atlas)
    from .delete import delete_impact, delete_note

    impact = delete_impact(atlas.root, note_id)
    if as_json and not force:
        _emit_json(_with_schema({"impact": impact}, surface="delete.preview"))
        return

    if not force:
        click.echo(f"Deleting: {impact['note_id']}")
        click.echo(
            "Impact: "
            f"{impact['incoming_wires'] + impact['outgoing_wires']} wires, "
            f"{impact['block_refs']} block_refs, "
            f"{impact['frontmatter_links']} notes link to it, "
            f"{impact['embeddings']} embeddings, "
            f"{impact['operating_truth_refs']} operating-truth refs"
        )
        response = click.prompt(
            "Also delete all wires and refs? [Y/n/a(rchive)]",
            default="y",
            show_default=False,
        ).strip().lower()
        if response in {"", "y", "yes"}:
            pass
        elif response in {"a", "archive"}:
            archive = True
        else:
            raise click.ClickException("delete aborted")

    payload = delete_note(
        atlas.root,
        note_id,
        cascade=not no_cascade,
        archive=archive,
    )
    if as_json:
        _emit_json(_with_schema(payload, surface="delete"))
        return
    if payload["archived"]:
        click.echo(f"archived: {payload['deleted']} -> {payload['archive_path']}")
    else:
        click.echo(f"deleted: {payload['deleted']}")


@main.group("guardrails", invoke_without_command=True)
@click.pass_context
def guardrails_group(ctx: click.Context) -> None:
    """Guardrail controls for atlas admission filtering."""
    if ctx.invoked_subcommand is not None:
        return
    atlas = get_atlas()
    from .guardrails import guardrails_status

    status = guardrails_status(atlas.root)
    click.echo("enabled" if status["enabled"] else "disabled")


@guardrails_group.command("scan")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def guardrails_scan(as_json: bool) -> None:
    atlas = get_atlas()
    from .guardrails import scan_atlas

    payload = scan_atlas(atlas.root)
    if as_json:
        _emit_json(_with_schema(payload, surface="guardrails.scan"))
        return
    click.echo(f"{payload['count']} guardrail violation(s)")
    for item in payload["violations"]:
        click.echo(f"{item['severity']:<6} {item['type']:<18} {item['note_id']}")


@guardrails_group.command("enable")
def guardrails_enable() -> None:
    atlas = get_atlas()
    from .guardrails import set_guardrails_enabled

    set_guardrails_enabled(atlas.root, True)
    click.echo("guardrails enabled")


@guardrails_group.command("disable")
def guardrails_disable() -> None:
    atlas = get_atlas()
    from .guardrails import set_guardrails_enabled

    set_guardrails_enabled(atlas.root, False)
    click.echo("guardrails disabled")


@guardrails_group.command("status")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def guardrails_status_command(as_json: bool) -> None:
    atlas = get_atlas()
    from .guardrails import guardrails_status

    payload = guardrails_status(atlas.root)
    if as_json:
        _emit_json(_with_schema(payload, surface="guardrails.status"))
        return
    click.echo("enabled" if payload["enabled"] else "disabled")
    for key, value in payload["config"].items():
        click.echo(f"{key}: {value}")


@main.command()
@click.argument("note_id")
def show(note_id: str) -> None:
    """Display note contents. Supports partial ID matching.

    Example: cart show hopeagent-session-001
    Example: cart show hopeagent (matches first note with ID containing 'hopeagent')
    """
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


@main.group("wire")
def wire_group() -> None:
    """semantic wire commands."""


@wire_group.command("predicates")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def wire_predicates(as_json: bool) -> None:
    payload = {
        "count": len(VALID_WIRE_PREDICATES),
        "predicates": list(VALID_WIRE_PREDICATES),
        "emotional_valences": list(VALID_EMOTIONAL_VALENCES),
        "energy_impacts": list(VALID_ENERGY_IMPACTS),
        "avoidance_risks": list(VALID_AVOIDANCE_RISKS),
        "current_states": list(VALID_CURRENT_STATES),
    }
    if as_json:
        _emit_json(_with_schema(payload, surface="wire.predicates"))
        return
    for predicate in VALID_WIRE_PREDICATES:
        click.echo(predicate)


@wire_group.command("add")
@click.argument("source")
@click.argument("target")
@click.option(
    "--predicate",
    required=False,
    type=click.Choice(list(VALID_WIRE_PREDICATES)),
)
@click.option(
    "--relationship",
    required=False,
    type=click.Choice(list(VALID_WIRE_PREDICATES)),
    help="Alias for --predicate and stored relationship label.",
)
@click.option("--bidirectional", is_flag=True, help="Mark the relationship as symmetric.")
@click.option(
    "--emotional-valence",
    type=click.Choice(list(VALID_EMOTIONAL_VALENCES)),
    help="Emotional tone of the relationship.",
)
@click.option(
    "--energy-impact",
    type=click.Choice(list(VALID_ENERGY_IMPACTS)),
    help="Energy impact of the relationship.",
)
@click.option(
    "--avoidance-risk",
    type=click.Choice(list(VALID_AVOIDANCE_RISKS)),
    help="Avoidance risk carried by this relationship.",
)
@click.option("--growth-edge", is_flag=True, help="Mark the wire as an active growth edge.")
@click.option(
    "--current-state",
    type=click.Choice(list(VALID_CURRENT_STATES)),
    help="Current state of the relationship.",
)
@click.option("--since", help="Optional ISO date or freeform start marker.")
@click.option("--until", help="Optional ISO date or freeform end marker.")
@click.option("--valence-note", help="Free-text note for emotional nuance.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def wire_add(
    source: str,
    target: str,
    predicate: str | None,
    relationship: str | None,
    bidirectional: bool,
    emotional_valence: str | None,
    energy_impact: str | None,
    avoidance_risk: str | None,
    growth_edge: bool,
    current_state: str | None,
    since: str | None,
    until: str | None,
    valence_note: str | None,
    as_json: bool,
) -> None:
    atlas = get_atlas()
    index = ensure_index_current(atlas)
    predicate, relationship = _wire_predicate_and_relationship(predicate, relationship)
    source_note, source_block, source_path = _resolve_note_or_block_ref(index, source)
    target_note, target_block, _ = _resolve_note_or_block_ref(index, target)
    payload = {
        "source": _render_note_or_block(source_note, source_block),
        "target": _render_note_or_block(target_note, target_block),
        "predicate": predicate,
        "relationship": relationship,
        "bidirectional": bidirectional,
        "emotional_valence": emotional_valence,
        "energy_impact": energy_impact,
        "avoidance_risk": avoidance_risk,
        "growth_edge": growth_edge,
        "current_state": current_state,
        "since": since,
        "until": until,
        "valence_note": valence_note,
        "created": False,
        "updated": False,
    }

    note = Note.from_file(source_path)
    comment = render_wire_comment(
        target_note=target_note,
        target_block=target_block,
        predicate=predicate,
        bidirectional=bidirectional,
        relationship=relationship,
        emotional_valence=emotional_valence,
        energy_impact=energy_impact,
        avoidance_risk=avoidance_risk,
        growth_edge=True if growth_edge else None,
        current_state=current_state,
        since=since,
        until=until,
        valence_note=valence_note,
    )
    created, updated = _replace_or_append_wire_comment(
        note,
        source_block=source_block,
        target_note=target_note,
        target_block=target_block,
        predicate=predicate,
        comment=comment,
    )
    payload["created"] = created
    payload["updated"] = updated
    if created or updated:
        note.write()
        atlas.refresh_index()
    if as_json:
        _emit_json(_with_schema(payload, surface="wire.add"))
        return
    status = "created" if created else "updated" if updated else "unchanged"
    metadata = _wire_metadata_fields(payload)
    suffix = ("  [bidirectional]" if bidirectional else "") + (
        f"  {{{', '.join(metadata)}}}" if metadata else ""
    )
    click.echo(
        f"wire {status}: {payload['source']} --{predicate}--> {payload['target']}{suffix}"
    )
    if valence_note:
        click.echo(f"note: {valence_note}")


@wire_group.command("ls")
@click.argument("node")
@click.option("--incoming", is_flag=True, help="Only show incoming wires.")
@click.option("--outgoing", is_flag=True, help="Only show outgoing wires.")
@click.option("--predicate", help="Filter to one predicate.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def wire_list(
    node: str,
    incoming: bool,
    outgoing: bool,
    predicate: str | None,
    as_json: bool,
) -> None:
    atlas = get_atlas()
    index = ensure_index_current(atlas)
    note_id, block_id, _ = _resolve_note_or_block_ref(index, node)
    direction = _wire_direction(incoming, outgoing)
    wires = index.list_wires(
        note_id=note_id,
        block_id=block_id,
        direction=direction,
        predicate=predicate,
    )
    payload = {
        "node": _render_note_or_block(note_id, block_id),
        "direction": direction,
        "predicate": predicate,
        "count": len(wires),
        "wires": wires,
    }
    if as_json:
        _emit_json(_with_schema(payload, surface="wire.list"))
        return
    for wire in wires:
        direction_label = "in " if wire["direction"] == "incoming" else "out"
        click.echo(f"{direction_label:3} {_render_wire_summary(wire)}")


@wire_group.command("query")
@click.option("--node", help="Limit results to wires touching this note.")
@click.option("--predicate", help="Filter to one predicate.")
@click.option("--relationship", help="Filter to one relationship/predicate.")
@click.option(
    "--emotional-valence",
    type=click.Choice(list(VALID_EMOTIONAL_VALENCES)),
    help="Filter by emotional valence.",
)
@click.option(
    "--energy-impact",
    type=click.Choice(list(VALID_ENERGY_IMPACTS)),
    help="Filter by energy impact.",
)
@click.option(
    "--avoidance-risk",
    type=click.Choice(list(VALID_AVOIDANCE_RISKS)),
    help="Filter by avoidance risk.",
)
@click.option("--growth-edge", is_flag=True, help="Only show growth edges.")
@click.option(
    "--current-state",
    type=click.Choice(list(VALID_CURRENT_STATES)),
    help="Filter by current state.",
)
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def wire_query(
    node: str | None,
    predicate: str | None,
    relationship: str | None,
    emotional_valence: str | None,
    energy_impact: str | None,
    avoidance_risk: str | None,
    growth_edge: bool,
    current_state: str | None,
    as_json: bool,
) -> None:
    atlas = get_atlas()
    index = ensure_index_current(atlas)
    note_id: str | None = None
    if node:
        note_id, _block_id, _path = _resolve_note_or_block_ref(index, node)
    wires = index.query_wires(
        note_id=note_id,
        predicate=predicate,
        relationship=relationship,
        emotional_valence=emotional_valence,
        energy_impact=energy_impact,
        avoidance_risk=avoidance_risk,
        growth_edge=True if growth_edge else None,
        current_state=current_state,
    )
    payload = {
        "node": note_id,
        "predicate": predicate,
        "relationship": relationship,
        "emotional_valence": emotional_valence,
        "energy_impact": energy_impact,
        "avoidance_risk": avoidance_risk,
        "growth_edge": growth_edge,
        "current_state": current_state,
        "count": len(wires),
        "wires": wires,
    }
    if as_json:
        _emit_json(_with_schema(payload, surface="wire.query"))
        return
    if not wires:
        click.echo("no matching wires")
        return
    for wire in wires:
        click.echo(_render_wire_summary(wire))


@wire_group.command("emotional-summary")
@click.argument("node")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def wire_emotional_summary(node: str, as_json: bool) -> None:
    atlas = get_atlas()
    index = ensure_index_current(atlas)
    note_id, block_id, _path = _resolve_note_or_block_ref(index, node)
    wires = index.list_wires(note_id=note_id, block_id=block_id, direction="both")
    primary = next(
        (
            wire
            for wire in wires
            if {
                str(wire["source_note"]),
                str(wire["target_note"]),
            }
            == {note_id, "maps"}
        ),
        wires[0] if wires else None,
    )
    payload = {
        "node": _render_note_or_block(note_id, block_id),
        "count": len(wires),
        "primary": primary,
        "summary": None
        if primary is None
        else {
            "emotional_valence": primary.get("emotional_valence"),
            "energy_impact": primary.get("energy_impact"),
            "avoidance_risk": primary.get("avoidance_risk"),
            "growth_edge": primary.get("growth_edge"),
            "current_state": primary.get("current_state"),
            "since": primary.get("since"),
            "until": primary.get("until"),
            "valence_note": primary.get("valence_note"),
        },
        "wires": wires,
    }
    if as_json:
        _emit_json(_with_schema(payload, surface="wire.emotional_summary"))
        return
    click.echo(f"{payload['node']} — emotional topology")
    if payload["summary"] is None:
        click.echo("no wires found")
        return
    summary = payload["summary"]
    click.echo(
        "summary: "
        + " / ".join(
            [
                str(summary.get("emotional_valence") or "?"),
                str(summary.get("energy_impact") or "?"),
                str(summary.get("avoidance_risk") or "?"),
                "growth-edge" if summary.get("growth_edge") else "non-growth",
                str(summary.get("current_state") or "?"),
            ]
        )
    )
    if summary.get("valence_note"):
        click.echo(f"note: {summary['valence_note']}")
    for wire in wires:
        click.echo(f"- {_render_wire_summary(wire)}")


@wire_group.command("doctor")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def wire_doctor(as_json: bool) -> None:
    atlas = get_atlas()
    index = ensure_index_current(atlas)
    payload = index.wire_doctor()
    if as_json:
        _emit_json(_with_schema(payload, surface="wire.doctor"))
        return
    if payload["issue_count"] == 0:
        click.echo("wires: ok")
        return
    click.echo(f"wires: {payload['issue_count']} issue(s)")
    for issue in payload["issues"]:
        click.echo(
            f"- {issue['path']}:{issue['line']}  {issue['code']}  {issue['message']}"
        )


@wire_group.command("validate")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def wire_validate(as_json: bool) -> None:
    atlas = get_atlas()
    index = ensure_index_current(atlas)
    payload = index.wire_doctor()
    if as_json:
        _emit_json(_with_schema(payload, surface="wire.validate"))
    elif payload["issue_count"] == 0:
        click.echo("wires: valid")
    else:
        click.echo(f"wires: invalid ({payload['issue_count']} issue(s))")
    raise click.exceptions.Exit(1 if payload["issue_count"] else 0)


@wire_group.command("gc")
@click.option("--apply", is_flag=True, help="Remove the candidate wire comments.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def wire_gc(apply: bool, as_json: bool) -> None:
    atlas = get_atlas()
    index = ensure_index_current(atlas)
    plan = _wire_gc_plan(index)
    removed = 0
    if apply:
        for item in plan:
            path = Path(str(item["path"]))
            note = Note.from_file(path)
            note.body = remove_wire_spans(note.body, list(item["spans"]))
            note.write()
            removed += int(item["span_count"])
        if plan:
            atlas.refresh_index()
    payload = {
        "apply": apply,
        "candidate_count": sum(int(item["span_count"]) for item in plan),
        "removed_count": removed,
        "note_count": len(plan),
        "notes": [
            {
                "path": item["path"],
                "line_numbers": item["line_numbers"],
                "candidate_count": item["span_count"],
            }
            for item in plan
        ],
    }
    if as_json:
        _emit_json(_with_schema(payload, surface="wire.gc"))
        return
    if not plan:
        click.echo("wire gc: nothing to clean")
        return
    if not apply:
        click.echo(
            f"wire gc: {payload['candidate_count']} candidate comment(s) across {payload['note_count']} note(s)"
        )
        click.echo("rerun with `cart wire gc --apply` to remove them")
        for item in payload["notes"]:
            click.echo(
                f"- {item['path']}  lines={','.join(str(line) for line in item['line_numbers'])}"
            )
        return
    click.echo(
        f"wire gc: removed {payload['removed_count']} comment(s) across {payload['note_count']} note(s)"
    )


@wire_group.command("traverse")
@click.argument("start")
@click.option("--depth", default=2, type=int, show_default=True)
@click.option("--predicate", help="Filter to one predicate.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def wire_traverse(
    start: str,
    depth: int,
    predicate: str | None,
    as_json: bool,
) -> None:
    atlas = get_atlas()
    index = ensure_index_current(atlas)
    start_note, _block_id, _path = _resolve_note_or_block_ref(index, start)
    payload = index.traverse_wires(
        start_note=start_note,
        depth=max(depth, 0),
        predicate=predicate,
    )
    if as_json:
        _emit_json(_with_schema(payload, surface="wire.traverse"))
        return
    click.echo(
        f"{payload['start_note']}: {payload['edge_count']} traversed edge(s), {len(payload['visited'])} visited note(s)"
    )
    for edge in payload["edges"]:
        source_ref = _render_note_or_block(
            str(edge["source_note"]),
            None if edge["source_block"] is None else str(edge["source_block"]),
        )
        target_ref = _render_note_or_block(
            str(edge["target_note"]),
            None if edge["target_block"] is None else str(edge["target_block"]),
        )
        suffix = "  [bi]" if edge["bidirectional"] else ""
        click.echo(
            f"- d{edge['depth']}  {edge['predicate']:18} {source_ref} -> {target_ref}{suffix}"
        )


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
    """Task and todo management commands."""


@todo.command("list")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def todo_list(as_json: bool) -> None:
    """List all open tasks, sorted by priority."""
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
@click.option("-p", "--priority", default="P2", show_default=True, help="Task priority (P0-P4).")
@click.option("--project", help="Associate with a project.")
@click.option("--due", help="Due date (e.g., 2026-04-25 or 'tomorrow').")
def todo_add(text: str, priority: str, project: str | None, due: str | None) -> None:
    """Add a new task or todo.

    Example: cart todo add "Fix cart TUI performance" -p P1
    Example: cart todo add "Review PR" --project hopeagent --due tomorrow
    """
    atlas = get_atlas()
    task = append_task(atlas.root, text, priority=priority, project=project, due=due)
    atlas.refresh_index()
    click.echo(f"{task.id} {task.path}")


@todo.command("done")
@click.argument("task_id")
def todo_done(task_id: str) -> None:
    """Mark a task as complete.

    Example: cart todo done task-12345
    """
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
    """Activity and completion logging."""


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
    """Database index maintenance and status commands."""


@index.command("rebuild")
def index_rebuild() -> None:
    """Rebuild the SQLite index from scratch.

    Use when index is out of sync or corrupted. This is safe—it re-indexes all notes.
    """
    atlas = get_atlas()
    result = Index(atlas.root).rebuild()
    click.echo(
        f"rebuilt index: {result['notes']} notes, {result['blocks']} blocks, {result['refs']} refs"
    )


@index.command("status")
def index_status() -> None:
    """Show index statistics (note count, block count, reference count)."""
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
@click.option("--temporal", "include_temporal", is_flag=True, help="Include temporal pattern correlations in the brief.")
@click.option("--output")
def daily_brief(output_format: str, include_temporal: bool, output: str | None) -> None:
    atlas = get_atlas()
    rendered = build_daily_brief(
        atlas.root,
        format=output_format,
        include_temporal=True if include_temporal else None,
    )
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
    """Session note and agent log management."""


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


@main.group()
def therapy() -> None:
    """therapy-scoped atlas export surfaces."""


@therapy.command("export")
@click.option("--role", default="intake", show_default=True)
@click.option("--scope", default="therapy", show_default=True)
@click.option(
    "--format",
    "output_format",
    default="markdown",
    type=click.Choice(["markdown", "json"]),
    show_default=True,
)
@click.option("--write", "write_path", help="Write the handoff to a specific atlas path.")
@click.option("--json", "as_json", is_flag=True, help="Emit the payload as JSON instead of writing a file.")
def therapy_export(
    role: str,
    scope: str,
    output_format: str,
    write_path: str | None,
    as_json: bool,
) -> None:
    atlas = get_atlas()
    entries = list_working_set_entries(
        atlas.root,
        role=role,
        scope=scope,
        include_expired=False,
        delete_expired=True,
    )
    sessions_payload = recent_sessions_payload(atlas, limit=6)
    payload = build_therapy_handoff_payload(
        working_set_entries=entries,
        sessions=list(sessions_payload["sessions"]),
        role=role,
        scope=scope,
    )
    if as_json:
        _emit_json(_with_schema(payload, surface="therapy.export"))
        return

    fmt = "json" if output_format == "json" else "markdown"
    destination = None if write_path is None else Path(write_path).expanduser()
    written = write_therapy_handoff(
        atlas.root,
        payload=payload,
        fmt=fmt,
        destination=destination,
    )
    click.echo(written)


@therapy.command("review")
@click.option("--role", default="intake", show_default=True)
@click.option("--scope", default="therapy", show_default=True)
@click.option("--sessions", default=6, type=int, show_default=True)
@click.option("--task-query", default="status:open", show_default=True)
@click.option(
    "--format",
    "output_format",
    default="markdown",
    type=click.Choice(["markdown", "json"]),
    show_default=True,
)
@click.option("--temporal", "include_temporal", is_flag=True, help="Include therapy-relevant temporal pattern correlations.")
@click.option("--write", "write_path", help="Write the therapy review to a specific atlas path.")
@click.option("--json", "as_json", is_flag=True, help="Emit the payload as JSON instead of writing a file.")
def therapy_review(
    role: str,
    scope: str,
    sessions: int,
    task_query: str,
    output_format: str,
    include_temporal: bool,
    write_path: str | None,
    as_json: bool,
) -> None:
    atlas = get_atlas()
    plugin = therapy_plugin_status(atlas.root)
    if not plugin["available"]:
        missing = ", ".join(plugin["missing"]) or "unknown"
        raise click.ClickException(
            f"therapy plugin unavailable at {plugin['dir']} (missing: {missing})"
        )
    entries = list_working_set_entries(
        atlas.root,
        role=role,
        scope=scope,
        include_expired=False,
        delete_expired=True,
    )
    sessions_payload = recent_sessions_payload(atlas, limit=max(sessions, 0))
    tasks = [_task_payload(task) for task in query_tasks(atlas.root, task_query)]
    try:
        payload = build_therapy_review_payload(
            atlas.root,
            working_set_entries=entries,
            sessions=list(sessions_payload["sessions"]),
            tasks=tasks,
            role=role,
            scope=scope,
            include_temporal=include_temporal,
        )
    except (FileNotFoundError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc

    if as_json:
        _emit_json(_with_schema(payload, surface="therapy.review"))
        return

    fmt = "json" if output_format == "json" else "markdown"
    destination = None if write_path is None else Path(write_path).expanduser()
    written = write_therapy_review(
        atlas.root,
        payload=payload,
        fmt=fmt,
        destination=destination,
    )
    click.echo(written)


@therapy.command("counter-evidence")
@click.argument("claim", nargs=-1, required=True)
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def therapy_counter_evidence(claim: tuple[str, ...], as_json: bool) -> None:
    atlas = get_atlas()
    text = " ".join(claim).strip()
    if not text:
        raise click.ClickException("claim is required")
    try:
        payload = counter_evidence_payload(atlas.root, text)
    except (FileNotFoundError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc
    response = {
        "claim": text,
        **payload,
    }
    if as_json:
        _emit_json(_with_schema(response, surface="therapy.counter-evidence"))
        return
    pattern = str(response.get("pattern_detected") or "unknown")
    click.echo(f"pattern: {pattern}")
    queries = response.get("counter_queries") or []
    if isinstance(queries, list) and queries:
        for query in queries:
            click.echo(f"- {query}")


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
    """Entity (person/organization) note maintenance and operations."""


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
    """Qualitative state tracking via mapsOS integration."""


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
    """Plugin installation, listing, and execution."""


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
@click.option(
    "--serve",
    "serve_mode",
    is_flag=True,
    help="Serve the live HTML graph at localhost and auto-regenerate on atlas changes.",
)
@click.option(
    "--port",
    default=6969,
    type=int,
    show_default=True,
    help="Port for --serve mode.",
)
@click.option(
    "--daemon",
    "daemon_mode",
    is_flag=True,
    help="Run the live graph server in the background.",
)
@click.option(
    "--status-daemon",
    "status_daemon",
    is_flag=True,
    help="Show status for the background graph daemon on --port.",
)
@click.option(
    "--stop-daemon",
    "stop_daemon",
    is_flag=True,
    help="Stop the background graph daemon on --port.",
)
@click.pass_context
def graph_export(
    ctx: click.Context,
    export_path: str | None,
    fmt: str,
    open_in_browser: bool,
    serve_mode: bool,
    port: int,
    daemon_mode: bool,
    status_daemon: bool,
    stop_daemon: bool,
) -> None:
    """Export the atlas note graph as JSON or an interactive HTML view."""

    atlas = get_atlas()
    fmt_source = ctx.get_parameter_source("fmt")

    if status_daemon and stop_daemon:
        raise click.ClickException("use either --status-daemon or --stop-daemon, not both")
    if daemon_mode and not serve_mode:
        raise click.ClickException("--daemon only works with --serve")
    if (status_daemon or stop_daemon) and serve_mode:
        raise click.ClickException("--status-daemon/--stop-daemon cannot be combined with --serve")
    if (status_daemon or stop_daemon) and export_path:
        raise click.ClickException("--export cannot be used with daemon management flags")
    if (status_daemon or stop_daemon) and open_in_browser:
        raise click.ClickException("--open cannot be used with daemon management flags")

    if status_daemon:
        from .graph_serve import daemon_status

        status = daemon_status(atlas.root, port=port)
        if status["running"]:
            click.echo(f"graph daemon running: pid {status['pid']} at {status['url']}")
            click.echo(f"log: {status['log_path']}")
            click.echo(f"pid file: {status['pid_path']}")
            server_status = status.get("server_status")
            if isinstance(server_status, dict):
                click.echo(
                    "graph status: "
                    f"{server_status.get('node_count')} nodes, "
                    f"{server_status.get('edge_count')} edges, "
                    f"last regen {server_status.get('last_regen')}"
                )
        else:
            click.echo(f"graph daemon not running on port {port}")
            if status.get("stale_pid") is not None:
                click.echo(f"removed stale pid file for pid {status['stale_pid']}")
            click.echo(f"log: {status['log_path']}")
            click.echo(f"pid file: {status['pid_path']}")
        return

    if stop_daemon:
        from .graph_serve import stop_graph_daemon

        stopped = stop_graph_daemon(atlas.root, port=port)
        if stopped["stopped"]:
            if stopped["forced"]:
                click.echo(
                    f"graph daemon stopped: pid {stopped['pid']} on port {port} (forced)"
                )
            else:
                click.echo(f"graph daemon stopped: pid {stopped['pid']} on port {port}")
        else:
            click.echo(f"graph daemon not running on port {port}")
            if stopped.get("stale_pid") is not None:
                click.echo(f"removed stale pid file for pid {stopped['stale_pid']}")
        click.echo(f"log: {stopped['log_path']}")
        click.echo(f"pid file: {stopped['pid_path']}")
        return

    if serve_mode:
        if export_path:
            raise click.ClickException("--export cannot be used with --serve")
        if fmt_source == ParameterSource.DEFAULT:
            fmt = "html"
        if fmt != "html":
            raise click.ClickException("--serve only works with --format html")
        if daemon_mode:
            from .graph_serve import spawn_graph_daemon

            daemon = spawn_graph_daemon(
                atlas.root,
                port=port,
                open_in_browser=open_in_browser,
            )
            click.echo(
                f"graph daemon started: pid {daemon['pid']} serving {daemon['url']}"
            )
            click.echo(f"log: {daemon['log_path']}")
            click.echo(f"pid file: {daemon['pid_path']}")
            return
        from .graph_serve import serve_graph

        serve_graph(atlas.root, port=port, open_in_browser=open_in_browser)
        return

    import webbrowser

    from .graph_export import load_graph_payload, render_graph_html

    ensure_index_current(atlas)
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


@main.command("summary")
@click.option("--emotional", is_flag=True, help="Summarize emotional topology of all wires.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def summary(emotional: bool, as_json: bool) -> None:
    """Synthesize insights from semantic wires and emotional topology."""
    atlas = get_atlas()
    index = ensure_index_current(atlas)

    # Query all wires
    all_wires = index.query_wires(note_id=None)

    if not all_wires:
        click.echo("no wires found")
        return

    # Synthesize emotional insights
    avoidance_high = [w for w in all_wires if w.get("avoidance_risk") == "high"]
    avoidance_medium = [w for w in all_wires if w.get("avoidance_risk") == "medium"]

    support_energizing = [w for w in all_wires if w.get("energy_impact") == "energizing" and w.get("avoidance_risk") in ("low", "none")]

    growth_edges = [w for w in all_wires if w.get("growth_edge") is True]

    # Current state distribution
    states = {}
    for w in all_wires:
        state = w.get("current_state")
        if state:
            states[state] = states.get(state, 0) + 1

    # Emotional valence distribution
    valences = {}
    for w in all_wires:
        val = w.get("emotional_valence")
        if val:
            valences[val] = valences.get(val, 0) + 1

    # Energy distribution
    energies = {}
    for w in all_wires:
        eng = w.get("energy_impact")
        if eng:
            energies[eng] = energies.get(eng, 0) + 1

    payload = {
        "total_wires": len(all_wires),
        "emotional_topology": {
            "avoidance_patterns": {
                "high_risk": len(avoidance_high),
                "medium_risk": len(avoidance_medium),
                "high_risk_nodes": [
                    {
                        "source": w.get("source_note"),
                        "target": w.get("target_note"),
                        "state": w.get("current_state"),
                        "valence_note": w.get("valence_note"),
                    }
                    for w in avoidance_high[:10]
                ],
            },
            "support_network": {
                "energizing_low_risk": len(support_energizing),
                "nodes": [
                    {
                        "source": w.get("source_note"),
                        "target": w.get("target_note"),
                        "energy": w.get("energy_impact"),
                        "state": w.get("current_state"),
                    }
                    for w in support_energizing[:10]
                ],
            },
            "growth_edges": {
                "count": len(growth_edges),
                "nodes": [
                    {
                        "source": w.get("source_note"),
                        "target": w.get("target_note"),
                        "valence": w.get("emotional_valence"),
                        "state": w.get("current_state"),
                    }
                    for w in growth_edges[:10]
                ],
            },
            "capacity_state": {
                "distribution": states,
                "dominant_state": max(states, key=states.get) if states else None,
            },
            "valence_distribution": valences,
            "energy_distribution": energies,
        },
    }

    if as_json:
        _emit_json(_with_schema(payload, surface="summary.emotional"))
        return

    # Human-readable output
    click.echo(f"emotional topology summary — {len(all_wires)} wires")
    click.echo()

    click.echo(f"avoidance patterns:")
    click.echo(f"  high-risk: {len(avoidance_high)} wires")
    click.echo(f"  medium-risk: {len(avoidance_medium)} wires")
    if avoidance_high:
        click.echo(f"  top high-risk territory:")
        for w in avoidance_high[:5]:
            click.echo(f"    {w.get('source_note')} ↔ {w.get('target_note')} ({w.get('current_state')})")
    click.echo()

    click.echo(f"support network:")
    click.echo(f"  energizing + low-risk: {len(support_energizing)} wires")
    if support_energizing:
        click.echo(f"  support people/projects:")
        for w in support_energizing[:5]:
            click.echo(f"    {w.get('source_note')} ↔ {w.get('target_note')} ({w.get('energy_impact')})")
    click.echo()

    click.echo(f"growth edges:")
    click.echo(f"  count: {len(growth_edges)}")
    if growth_edges:
        click.echo(f"  edges in play:")
        for w in growth_edges[:5]:
            click.echo(f"    {w.get('source_note')} ↔ {w.get('target_note')} ({w.get('emotional_valence')})")
    click.echo()

    click.echo(f"capacity state:")
    for state, count in sorted(states.items(), key=lambda x: -x[1]):
        click.echo(f"  {state}: {count}")
    click.echo()

    click.echo(f"emotional distribution:")
    for val, count in sorted(valences.items(), key=lambda x: -x[1]):
        click.echo(f"  {val}: {count}")


if __name__ == "__main__":
    main()
