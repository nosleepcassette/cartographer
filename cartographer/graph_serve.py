from __future__ import annotations

import http.client
import http.server
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import click

from .atlas import Atlas
from .config import load_config
from .graph_export import load_graph_payload, render_graph_html
from .index import Index
from .notes import Note
from .profiles import profile_payload
from .wires import (
    delete_wire_comment,
    find_wire_comment,
    insert_wire_comment,
    render_wire_comment,
    replace_wire_comment,
)


EXTRA_IGNORED_TOP_LEVEL_DIRS = {"readings", "shared"}


@dataclass
class GraphState:
    """Mutable in-memory graph snapshot shared across threads."""

    html: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    node_count: int = 0
    edge_count: int = 0
    last_regen: str = ""
    plugin_names: tuple[str, ...] = ()
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def update(
        self,
        html: str,
        *,
        payload: dict[str, Any],
        node_count: int,
        edge_count: int,
    ) -> None:
        with self._lock:
            self.html = html
            self.payload = payload
            self.node_count = node_count
            self.edge_count = edge_count
            self.last_regen = datetime.now().astimezone().replace(microsecond=0).isoformat()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "html": self.html,
                "payload": self.payload,
                "node_count": self.node_count,
                "edge_count": self.edge_count,
                "last_regen": self.last_regen,
            }


def daemon_artifact_paths(atlas_root: Path | str, *, port: int) -> tuple[Path, Path]:
    atlas_root = Path(atlas_root).expanduser()
    meta_dir = atlas_root / ".cartographer"
    meta_dir.mkdir(parents=True, exist_ok=True)
    return (
        meta_dir / f"graph-serve-{port}.pid",
        meta_dir / f"graph-serve-{port}.log",
    )


def _read_pid_file(pid_path: Path) -> int | None:
    if not pid_path.exists():
        return None
    try:
        return int(pid_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _existing_daemon_pid(pid_path: Path) -> int | None:
    pid = _read_pid_file(pid_path)
    if pid is None:
        return None
    return pid if _pid_is_running(pid) else None


def _server_status(port: int, *, timeout: float = 0.5) -> dict[str, Any] | None:
    connection = http.client.HTTPConnection("localhost", port, timeout=timeout)
    try:
        connection.request("GET", "/status")
        response = connection.getresponse()
        if response.status != 200:
            return None
        payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    finally:
        connection.close()
    return payload if isinstance(payload, dict) else None


def _ignored_watch_settings(atlas_root: Path) -> tuple[set[str], set[str]]:
    config = load_config(root=atlas_root)
    ignore_config = config.get("ignore", {}) if isinstance(config, dict) else {}
    ignored_dirs = {
        str(value).strip()
        for value in ignore_config.get("dirs", [])
        if str(value).strip()
    }
    ignored_extensions = {
        str(value).strip()
        for value in ignore_config.get("extensions", [])
        if str(value).strip()
    }
    ignored_dirs.update(EXTRA_IGNORED_TOP_LEVEL_DIRS)
    return ignored_dirs, ignored_extensions


def _snapshot_watched_files(atlas_root: Path) -> dict[str, int]:
    ignored_dirs, ignored_extensions = _ignored_watch_settings(atlas_root)
    snapshot: dict[str, int] = {}
    if not atlas_root.exists():
        return snapshot

    for path in atlas_root.rglob("*.md"):
        try:
            relative = path.relative_to(atlas_root)
        except ValueError:
            continue
        if any(part in ignored_dirs for part in relative.parts):
            continue
        if path.suffix in ignored_extensions:
            continue
        try:
            snapshot[relative.as_posix()] = path.stat().st_mtime_ns
        except OSError:
            continue
    return snapshot


def regenerate_graph(
    state: GraphState,
    atlas_root: Path | str,
    *,
    force_rebuild: bool = False,
    announce_rebuild: bool = False,
    plugin_names: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Refresh the graph payload and replace the in-memory HTML snapshot."""

    atlas_root = Path(atlas_root).expanduser()
    index = Index(atlas_root)
    needs_rebuild = force_rebuild or not index.db_path.exists() or index.needs_rebuild()
    if needs_rebuild:
        if announce_rebuild:
            click.echo("rebuilding index...", err=True)
        index.rebuild()

    payload = load_graph_payload(atlas_root, plugin_names=plugin_names)
    state.update(
        render_graph_html(payload, plugin_names=plugin_names),
        payload=payload,
        node_count=int(payload["node_count"]),
        edge_count=int(payload["edge_count"]),
    )
    return payload


def watch_atlas(
    atlas_root: Path | str,
    state: GraphState,
    *,
    stop_event: threading.Event | None = None,
    poll_interval: float = 2.0,
    debounce: float = 2.0,
) -> None:
    """Poll atlas markdown files and regenerate after a quiet debounce window."""

    atlas_root = Path(atlas_root).expanduser()
    stop_event = stop_event or threading.Event()
    previous_snapshot = _snapshot_watched_files(atlas_root)
    pending_since: float | None = None

    while not stop_event.is_set():
        current_snapshot = _snapshot_watched_files(atlas_root)
        now = time.monotonic()

        if current_snapshot != previous_snapshot:
            previous_snapshot = current_snapshot
            pending_since = now

        if pending_since is not None and now - pending_since >= debounce:
            try:
                regenerate_graph(state, atlas_root, force_rebuild=True, plugin_names=state.plugin_names)
            except Exception as exc:
                click.echo(f"graph regeneration failed: {exc}", err=True)
            pending_since = None

        stop_event.wait(poll_interval)


def _first_query_value(parsed: urllib.parse.SplitResult, name: str, default: str | None = None) -> str | None:
    values = urllib.parse.parse_qs(parsed.query or "").get(name)
    if not values:
        return default
    return str(values[0])


def _canonical_note_query(index: Index, atlas_root: Path, raw: str) -> str:
    candidate = str(raw).strip()
    if not candidate:
        raise click.ClickException("missing note query")
    candidate_path = Path(candidate).expanduser()
    if candidate_path.is_absolute():
        try:
            candidate = candidate_path.resolve().relative_to(atlas_root.resolve()).with_suffix("").as_posix()
        except ValueError:
            candidate = candidate_path.stem
    return index.canonicalize_note_ref(candidate) or candidate


def _predicate_api_payload(atlas_root: Path) -> list[dict[str, str]]:
    from .profiles import predicate_palette_payload

    return predicate_palette_payload(atlas_root, config=load_config(root=atlas_root))


def _trace_api_payload(atlas_root: Path, parsed: urllib.parse.SplitResult) -> dict[str, Any]:
    from .think import configured_think_settings, spreading_activation

    index = Index(atlas_root)
    note_query = _first_query_value(parsed, "note")
    if note_query is None:
        raise click.ClickException("trace api requires ?note=")
    note_ref = _canonical_note_query(index, atlas_root, note_query)
    settings = configured_think_settings(atlas_root)
    depth = int(_first_query_value(parsed, "depth", str(settings.get("default_depth", 3))) or 3)
    decay = float(_first_query_value(parsed, "decay", str(settings.get("default_decay", 0.85))) or 0.85)
    predicate = _first_query_value(parsed, "type")
    strong_only = (_first_query_value(parsed, "strong", "0") or "0").strip().lower() in {"1", "true", "yes"}
    results = spreading_activation(
        atlas_root,
        note_ref,
        depth=depth,
        decay=decay,
        emotional_weight=bool(settings.get("emotional_weighting", True)),
        predicate=predicate,
    )
    if strong_only:
        results = [item for item in results if float(item["activation"]) >= 0.7]
    return {
        "note_id": note_ref,
        "depth": depth,
        "decay": decay,
        "predicate": predicate,
        "strong_only": strong_only,
        "results": results,
    }


def _discover_api_payload(atlas_root: Path, parsed: urllib.parse.SplitResult) -> dict[str, Any]:
    from .discover import configured_discover_settings, discover_bridges

    settings = configured_discover_settings(atlas_root)
    threshold = float(_first_query_value(parsed, "threshold", str(settings.get("threshold", 0.6))) or 0.6)
    max_proposals = int(settings.get("max_proposals", 20) or 20)
    candidates = discover_bridges(atlas_root, threshold=threshold, max_proposals=max_proposals)
    note_ref = _first_query_value(parsed, "note")
    if note_ref:
        index = Index(atlas_root)
        canonical = _canonical_note_query(index, atlas_root, note_ref)
        candidates = [
            candidate
            for candidate in candidates
            if canonical in {str(candidate["left_id"]), str(candidate["right_id"])}
        ]
    return {
        "threshold": threshold,
        "count": len(candidates),
        "candidates": candidates,
    }


def _current_actor() -> str:
    return (
        str(os.environ.get("USER") or "").strip()
        or str(Path.home().name).strip()
        or "cartographer"
    )


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _require_float_in_range(name: str, value: Any, *, minimum: float = 0.0, maximum: float = 1.0) -> float | None:
    parsed = _optional_float(value)
    if parsed is None:
        return None
    if not minimum <= parsed <= maximum:
        raise click.ClickException(f"{name} must be between {minimum:.1f} and {maximum:.1f}")
    return round(parsed, 3)


def _validate_predicate(atlas_root: Path, predicate: str | None) -> str:
    value = _optional_text(predicate)
    if value is None:
        raise click.ClickException("predicate is required")
    valid = set(profile_payload(atlas_root, config=load_config(root=atlas_root)).get("default_predicates") or [])
    if valid and value not in valid:
        raise click.ClickException(f"unsupported predicate: {value}")
    return value


def _resolve_note_path_for_wire(atlas_root: Path, payload: dict[str, Any], *, source_field: str = "source_note") -> Path:
    raw_path = _optional_text(payload.get("path") or payload.get("source_path"))
    if raw_path:
        return Path(raw_path).expanduser()
    source_note = _optional_text(payload.get(source_field))
    if source_note is None:
        raise click.ClickException("wire payload is missing source note")
    resolved = Atlas(root=atlas_root).resolve_note_path(source_note)
    if resolved is None:
        raise click.ClickException(f"source note not found: {source_note}")
    return resolved


def _wire_identity(payload: dict[str, Any]) -> dict[str, Any]:
    target_note = _optional_text(payload.get("target_note"))
    if target_note is None:
        raise click.ClickException("wire payload is missing target_note")
    predicate = _optional_text(payload.get("predicate"))
    if predicate is None:
        raise click.ClickException("wire payload is missing predicate")
    return {
        "source_block": _optional_text(payload.get("source_block")),
        "target_note": target_note,
        "target_block": _optional_text(payload.get("target_block")),
        "predicate": predicate,
    }


def _edge_payload(existing: Any) -> dict[str, Any]:
    return {
        "source_note": existing.source_note,
        "source_block": existing.source_block,
        "target_note": existing.target_note,
        "target_block": existing.target_block,
        "predicate": existing.predicate,
        "weight": existing.weight,
        "relationship": existing.relationship,
        "bidirectional": existing.bidirectional,
        "emotional_valence": existing.emotional_valence,
        "energy_impact": existing.energy_impact,
        "avoidance_risk": existing.avoidance_risk,
        "growth_edge": existing.growth_edge,
        "current_state": existing.current_state,
        "since": existing.since,
        "until": existing.until,
        "valence_note": existing.valence_note,
        "author": existing.author,
        "method": existing.method,
        "reviewed": existing.reviewed,
        "reviewed_by": existing.reviewed_by,
        "reviewed_at": existing.reviewed_at,
        "review_duration_s": existing.review_duration_s,
        "confidence": existing.confidence,
        "note": existing.note,
        "path": existing.path,
        "line": existing.line,
    }


def _render_wire_comment_from_payload(
    atlas_root: Path,
    *,
    base: dict[str, Any],
    payload: dict[str, Any],
    identity_predicate: str,
) -> tuple[str, dict[str, Any]]:
    actor = _current_actor()
    predicate = _validate_predicate(atlas_root, payload.get("new_predicate") or payload.get("predicate") or base.get("predicate"))
    weight = _require_float_in_range("weight", payload.get("weight", base.get("weight")))
    review_duration_s = _optional_float(payload.get("review_duration_s", base.get("review_duration_s")))
    if review_duration_s is not None and review_duration_s < 0:
        raise click.ClickException("review_duration_s must be non-negative")
    reviewed = _optional_bool(payload.get("reviewed"))
    if reviewed is None:
        reviewed = base.get("reviewed")
    reviewed_by = _optional_text(payload.get("reviewed_by")) or _optional_text(base.get("reviewed_by"))
    reviewed_at = _optional_text(payload.get("reviewed_at")) or _optional_text(base.get("reviewed_at"))
    method = _optional_text(payload.get("method")) or _optional_text(base.get("method")) or "manual"
    if reviewed:
        reviewed_by = reviewed_by or actor
        reviewed_at = reviewed_at or datetime.now().astimezone().replace(microsecond=0).isoformat()
        if method in {"agent", "interactive"} and payload.get("method") is None:
            method = "confirmed"
    relationship = _optional_text(payload.get("relationship"))
    if relationship is None:
        relationship = _optional_text(base.get("relationship")) or predicate
    confidence = _optional_text(payload.get("confidence")) or _optional_text(base.get("confidence"))
    note_text = _optional_text(payload.get("note"))
    if note_text is None and payload.get("note") is None:
        note_text = _optional_text(base.get("note"))
    comment_payload = {
        "target_note": _optional_text(base.get("target_note")),
        "target_block": _optional_text(base.get("target_block")),
        "predicate": predicate,
        "weight": weight,
        "bidirectional": bool(payload.get("bidirectional", base.get("bidirectional"))),
        "relationship": relationship,
        "emotional_valence": _optional_text(payload.get("emotional_valence")) or _optional_text(base.get("emotional_valence")),
        "energy_impact": _optional_text(payload.get("energy_impact")) or _optional_text(base.get("energy_impact")),
        "avoidance_risk": _optional_text(payload.get("avoidance_risk")) or _optional_text(base.get("avoidance_risk")),
        "growth_edge": _optional_bool(payload.get("growth_edge")) if payload.get("growth_edge") is not None else base.get("growth_edge"),
        "current_state": _optional_text(payload.get("current_state")) or _optional_text(base.get("current_state")),
        "since": _optional_text(payload.get("since")) or _optional_text(base.get("since")),
        "until": _optional_text(payload.get("until")) or _optional_text(base.get("until")),
        "valence_note": _optional_text(payload.get("valence_note")) or _optional_text(base.get("valence_note")),
        "author": _optional_text(payload.get("author")) or _optional_text(base.get("author")) or actor,
        "method": method,
        "reviewed": reviewed,
        "reviewed_by": reviewed_by,
        "reviewed_at": reviewed_at,
        "review_duration_s": review_duration_s,
        "confidence": confidence,
        "note": note_text,
    }
    comment = render_wire_comment(**comment_payload)
    output = {
        **base,
        **comment_payload,
        "predicate": predicate,
        "weight": weight,
        "path": base.get("path"),
        "line": base.get("line"),
        "identity_predicate": identity_predicate,
    }
    return comment, output


def _refresh_graph_after_write(state: GraphState, atlas_root: Path) -> None:
    Atlas(root=atlas_root).refresh_index()
    regenerate_graph(state, atlas_root, force_rebuild=True, plugin_names=state.plugin_names)


def _wire_update_api_payload(state: GraphState, atlas_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(payload)
    payload["_atlas_root"] = str(atlas_root)
    note_path = _resolve_note_path_for_wire(atlas_root, payload)
    note = Note.from_file(note_path)
    identity = _wire_identity(payload)
    existing = find_wire_comment(note, **identity)
    if existing is None:
        raise click.ClickException("wire not found")
    base = _edge_payload(existing)
    comment, updated = _render_wire_comment_from_payload(
        atlas_root,
        base=base,
        payload=payload,
        identity_predicate=identity["predicate"],
    )
    if existing.raw == comment:
        return {"updated": False, "edge": updated}
    replaced = replace_wire_comment(
        note,
        source_block=identity["source_block"],
        target_note=identity["target_note"],
        target_block=identity["target_block"],
        predicate=identity["predicate"],
        comment=comment,
    )
    if not replaced:
        raise click.ClickException("wire not found")
    note.frontmatter["modified"] = date.today().isoformat()
    note.write()
    _refresh_graph_after_write(state, atlas_root)
    return {"updated": True, "edge": updated}


def _wire_review_api_payload(state: GraphState, atlas_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    review_payload = {
        **payload,
        "reviewed": True,
        "reviewed_by": _optional_text(payload.get("reviewed_by")) or _current_actor(),
        "reviewed_at": _optional_text(payload.get("reviewed_at"))
        or datetime.now().astimezone().replace(microsecond=0).isoformat(),
    }
    if payload.get("method") is None:
        review_payload["method"] = None
    return _wire_update_api_payload(state, atlas_root, review_payload)


def _wire_delete_api_payload(state: GraphState, atlas_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(payload)
    payload["_atlas_root"] = str(atlas_root)
    note_path = _resolve_note_path_for_wire(atlas_root, payload)
    note = Note.from_file(note_path)
    identity = _wire_identity(payload)
    removed = delete_wire_comment(note, **identity)
    if not removed:
        raise click.ClickException("wire not found")
    note.frontmatter["modified"] = date.today().isoformat()
    note.write()
    _refresh_graph_after_write(state, atlas_root)
    return {"deleted": True}


def _wire_create_api_payload(state: GraphState, atlas_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(payload)
    payload["_atlas_root"] = str(atlas_root)
    atlas = Atlas(root=atlas_root)
    source_note = _optional_text(payload.get("source_note"))
    target_note = _optional_text(payload.get("target_note"))
    if source_note is None or target_note is None:
        raise click.ClickException("source_note and target_note are required")
    source_note = _canonical_note_query(Index(atlas_root), atlas_root, source_note)
    target_note = _canonical_note_query(Index(atlas_root), atlas_root, target_note)
    source_path = atlas.resolve_note_path(source_note)
    target_path = atlas.resolve_note_path(target_note)
    if source_path is None:
        raise click.ClickException(f"source note not found: {source_note}")
    if target_path is None:
        raise click.ClickException(f"target note not found: {target_note}")
    note = Note.from_file(source_path)
    source_block = _optional_text(payload.get("source_block"))
    target_block = _optional_text(payload.get("target_block"))
    predicate = _validate_predicate(atlas_root, payload.get("predicate"))
    actor = _current_actor()
    reviewed_at = datetime.now().astimezone().replace(microsecond=0).isoformat()
    base = {
        "target_note": target_note,
        "target_block": target_block,
        "predicate": predicate,
        "weight": payload.get("weight", 0.7),
        "relationship": _optional_text(payload.get("relationship")) or predicate,
        "bidirectional": bool(payload.get("bidirectional", False)),
        "emotional_valence": _optional_text(payload.get("emotional_valence")),
        "energy_impact": _optional_text(payload.get("energy_impact")),
        "avoidance_risk": _optional_text(payload.get("avoidance_risk")),
        "growth_edge": _optional_bool(payload.get("growth_edge")),
        "current_state": _optional_text(payload.get("current_state")),
        "since": _optional_text(payload.get("since")),
        "until": _optional_text(payload.get("until")),
        "valence_note": _optional_text(payload.get("valence_note")),
        "author": _optional_text(payload.get("author")) or actor,
        "method": _optional_text(payload.get("method")) or "manual",
        "reviewed": True if payload.get("reviewed") is None else bool(payload.get("reviewed")),
        "reviewed_by": _optional_text(payload.get("reviewed_by")) or actor,
        "reviewed_at": _optional_text(payload.get("reviewed_at")) or reviewed_at,
        "review_duration_s": _optional_float(payload.get("review_duration_s")),
        "confidence": _optional_text(payload.get("confidence")) or "high",
        "note": _optional_text(payload.get("note")),
        "path": str(source_path),
        "line": None,
    }
    comment, created_edge = _render_wire_comment_from_payload(
        atlas_root,
        base=base,
        payload=payload,
        identity_predicate=predicate,
    )
    existing = find_wire_comment(
        note,
        source_block=source_block,
        target_note=target_note,
        target_block=target_block,
        predicate=predicate,
    )
    if existing is not None and existing.raw == comment:
        return {"created": False, "updated": False, "edge": created_edge}
    if existing is not None:
        replace_wire_comment(
            note,
            source_block=source_block,
            target_note=target_note,
            target_block=target_block,
            predicate=predicate,
            comment=comment,
        )
        updated = True
        created = False
    else:
        insert_wire_comment(note, source_block=source_block, comment=comment)
        updated = False
        created = True
    note.frontmatter["modified"] = date.today().isoformat()
    note.write()
    _refresh_graph_after_write(state, atlas_root)
    return {"created": created, "updated": updated, "edge": created_edge}


def _discover_accept_api_payload(state: GraphState, atlas_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    from .discover import accept_bridge_proposals

    actor = _current_actor()
    proposal = {
        "left_id": _optional_text(payload.get("left_id")),
        "right_id": _optional_text(payload.get("right_id")),
        "left_path": _optional_text(payload.get("left_path")),
        "right_path": _optional_text(payload.get("right_path")),
        "score": float(payload.get("score") or 0.0),
        "reasons": payload.get("reasons") if isinstance(payload.get("reasons"), dict) else {},
        "predicate": _validate_predicate(atlas_root, payload.get("predicate")),
        "weight": _require_float_in_range("weight", payload.get("weight", 0.7)),
        "author": "cart-discover",
        "method": "interactive",
        "reviewed": True,
        "reviewed_by": actor,
        "reviewed_at": datetime.now().astimezone().replace(microsecond=0).isoformat(),
        "review_duration_s": _optional_float(payload.get("review_duration_s")),
        "confidence": _optional_text(payload.get("confidence")) or "medium",
        "note": _optional_text(payload.get("note")),
    }
    if not proposal["left_id"] or not proposal["right_id"]:
        raise click.ClickException("discover accept requires left_id and right_id")
    accepted = accept_bridge_proposals(atlas_root, [proposal])
    if accepted <= 0:
        raise click.ClickException("candidate was not accepted")
    regenerate_graph(state, atlas_root, force_rebuild=True, plugin_names=state.plugin_names)
    return {"accepted": accepted}


def _graph_handler_factory(
    atlas_root: Path,
    state: GraphState,
) -> type[http.server.BaseHTTPRequestHandler]:
    class GraphHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlsplit(self.path)
            path = parsed.path or "/"

            if path == "/":
                self._send_html()
                return
            if path == "/status":
                snapshot = state.snapshot()
                self._send_json(
                    {
                        "node_count": snapshot["node_count"],
                        "edge_count": snapshot["edge_count"],
                        "last_regen": snapshot["last_regen"],
                    }
                )
                return
            if path == "/api/predicates":
                self._send_json(_predicate_api_payload(atlas_root))
                return
            if path == "/api/trace":
                try:
                    self._send_json(_trace_api_payload(atlas_root, parsed))
                except Exception as exc:
                    self._send_json({"error": str(exc)}, status=400)
                return
            if path == "/api/discover":
                try:
                    self._send_json(_discover_api_payload(atlas_root, parsed))
                except Exception as exc:
                    self._send_json({"error": str(exc)}, status=400)
                return
            if path == "/reload":
                try:
                    regenerate_graph(state, atlas_root, force_rebuild=True, plugin_names=state.plugin_names)
                except Exception as exc:
                    self._send_json({"error": str(exc)}, status=500)
                    return
                self.send_response(302)
                self.send_header("Location", "/")
                self.end_headers()
                return
            if path.startswith("/themes/"):
                self._send_theme_script(path)
                return

            self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlsplit(self.path)
            path = parsed.path or "/"
            try:
                payload = self._read_json_body()
                if path == "/api/wire/create":
                    self._send_json(_wire_create_api_payload(state, atlas_root, payload))
                    return
                if path == "/api/wire/update":
                    self._send_json(_wire_update_api_payload(state, atlas_root, payload))
                    return
                if path == "/api/wire/review":
                    self._send_json(_wire_review_api_payload(state, atlas_root, payload))
                    return
                if path == "/api/wire/delete":
                    self._send_json(_wire_delete_api_payload(state, atlas_root, payload))
                    return
                if path == "/api/discover/accept":
                    self._send_json(_discover_accept_api_payload(state, atlas_root, payload))
                    return
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            self.send_error(404)

        def _send_html(self) -> None:
            html = str(state.snapshot()["html"])
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))

        def _send_json(self, payload: Any, *, status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

        def _read_json_body(self) -> dict[str, Any]:
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except ValueError as exc:
                raise click.ClickException("invalid content length") from exc
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise click.ClickException("invalid json body") from exc
            if not isinstance(payload, dict):
                raise click.ClickException("json body must be an object")
            return payload

        def _send_theme_script(self, request_path: str) -> None:
            requested = request_path.removeprefix("/themes/")
            script_name = Path(requested).name
            if not script_name or script_name != requested:
                self.send_error(404)
                return

            theme_path = atlas_root / "themes" / script_name
            if not theme_path.exists() or not theme_path.is_file():
                self.send_error(404)
                return

            try:
                content = theme_path.read_text(encoding="utf-8")
            except OSError:
                self.send_error(404)
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/javascript; charset=utf-8")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))

        def log_message(self, format: str, *args: object) -> None:
            return

    return GraphHandler


def build_graph_http_server(
    atlas_root: Path | str,
    state: GraphState,
    *,
    host: str = "localhost",
    port: int = 6969,
) -> http.server.ThreadingHTTPServer:
    atlas_root = Path(atlas_root).expanduser()
    return http.server.ThreadingHTTPServer(
        (host, port),
        _graph_handler_factory(atlas_root, state),
    )


def spawn_graph_daemon(
 atlas_root: Path | str,
 *,
 port: int = 6969,
 open_in_browser: bool = False,
 plugin_names: tuple[str, ...] = (),
) -> dict[str, Any]:
    atlas_root = Path(atlas_root).expanduser()
    pid_path, log_path = daemon_artifact_paths(atlas_root, port=port)
    existing_pid = _existing_daemon_pid(pid_path)
    if existing_pid is not None:
        raise click.ClickException(
            f"graph daemon already running on port {port} (pid {existing_pid})"
        )

    command = [
        sys.executable,
        "-m",
        "cartographer.cli",
        "graph",
        "--serve",
        "--port",
        str(port),
    ]
    if open_in_browser:
        command.append("--open")
    for plugin_name in plugin_names:
        command.extend(["--plugin", plugin_name])

    env = os.environ.copy()
    env["CARTOGRAPHER_ROOT"] = str(atlas_root)

    popen_kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": None,
        "stderr": None,
        "env": env,
        "cwd": str(atlas_root),
        "close_fds": True,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        )
    else:
        popen_kwargs["start_new_session"] = True

    with log_path.open("ab") as log_file:
        popen_kwargs["stdout"] = log_file
        popen_kwargs["stderr"] = log_file
        process = subprocess.Popen(command, **popen_kwargs)

    pid_path.write_text(f"{process.pid}\n", encoding="utf-8")
    return {
        "pid": process.pid,
        "pid_path": pid_path,
        "log_path": log_path,
        "url": f"http://localhost:{port}",
    }


def daemon_status(atlas_root: Path | str, *, port: int = 6969) -> dict[str, Any]:
    atlas_root = Path(atlas_root).expanduser()
    pid_path, log_path = daemon_artifact_paths(atlas_root, port=port)
    recorded_pid = _read_pid_file(pid_path)
    pid = _existing_daemon_pid(pid_path)
    stale = recorded_pid is not None and pid is None
    if stale:
        pid_path.unlink(missing_ok=True)
    return {
        "running": pid is not None,
        "pid": pid,
        "port": port,
        "url": f"http://localhost:{port}",
        "pid_path": pid_path,
        "log_path": log_path,
        "server_status": _server_status(port) if pid is not None else None,
        "stale_pid": recorded_pid if stale else None,
    }


def stop_graph_daemon(
    atlas_root: Path | str,
    *,
    port: int = 6969,
    timeout: float = 5.0,
) -> dict[str, Any]:
    atlas_root = Path(atlas_root).expanduser()
    status_payload = daemon_status(atlas_root, port=port)
    pid_path = Path(status_payload["pid_path"])
    pid = status_payload["pid"]
    if pid is None:
        return {
            **status_payload,
            "stopped": False,
            "forced": False,
        }

    forced = False
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pid_path.unlink(missing_ok=True)
        return {
            **status_payload,
            "running": False,
            "stopped": True,
            "forced": False,
        }

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_is_running(pid):
            break
        time.sleep(0.1)

    if _pid_is_running(pid) and os.name != "nt":
        forced = True
        os.kill(pid, signal.SIGKILL)
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if not _pid_is_running(pid):
                break
            time.sleep(0.05)

    if _pid_is_running(pid):
        raise click.ClickException(
            f"graph daemon on port {port} did not stop cleanly"
        )

    pid_path.unlink(missing_ok=True)
    return {
        **status_payload,
        "running": False,
        "stopped": True,
        "forced": forced,
    }


def serve_graph(
    atlas_root: Path | str,
    *,
    port: int = 6969,
    open_in_browser: bool = False,
    plugin_names: tuple[str, ...] = (),
) -> None:
    atlas_root = Path(atlas_root).expanduser()
    state = GraphState(plugin_names=plugin_names)
    regenerate_graph(
        state,
        atlas_root,
        force_rebuild=False,
        announce_rebuild=True,
        plugin_names=plugin_names,
    )

    stop_event = threading.Event()
    watcher = threading.Thread(
        target=watch_atlas,
        kwargs={
            "atlas_root": atlas_root,
            "state": state,
            "stop_event": stop_event,
        },
        daemon=True,
    )
    server = build_graph_http_server(atlas_root, state, port=port)
    url = f"http://localhost:{server.server_port}"

    click.echo(f"serving atlas graph at {url}")
    watcher.start()

    if open_in_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        click.echo("\nstopping graph server")
    finally:
        stop_event.set()
        server.server_close()
        watcher.join(timeout=2.0)
