from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from .mapsos import default_export_paths, load_mapsos_payload


def therapy_export_dir(atlas_root: Path) -> Path:
    return atlas_root / "notes" / "therapy" / "exports"


def therapy_review_dir(atlas_root: Path) -> Path:
    return atlas_root / "notes" / "therapy" / "reviews"


def default_export_path(atlas_root: Path, *, fmt: str) -> Path:
    extension = "json" if fmt == "json" else "md"
    return therapy_export_dir(atlas_root) / f"notes-therapy-handoff-{date.today().isoformat()}.{extension}"


def default_review_path(atlas_root: Path, *, fmt: str) -> Path:
    extension = "json" if fmt == "json" else "md"
    return therapy_review_dir(atlas_root) / f"notes-therapy-review-{date.today().isoformat()}.{extension}"


def therapy_plugin_dir(atlas_root: Path) -> Path:
    override = os.environ.get("CART_THERAPY_PLUGIN_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return atlas_root / "agents" / "cassette" / "skills" / "therapy-plugin"


def therapy_plugin_status(atlas_root: Path) -> dict[str, Any]:
    plugin_dir = therapy_plugin_dir(atlas_root)
    scripts_dir = plugin_dir / "scripts"
    expected = {
        "skill": plugin_dir / "SKILL.md",
        "patterns": plugin_dir / "patterns.yaml",
        "interventions": plugin_dir / "interventions.yaml",
        "detect": scripts_dir / "pattern-detect.py",
        "counter_evidence": scripts_dir / "counter-evidence.py",
    }
    missing = [name for name, path in expected.items() if not path.exists()]
    return {
        "dir": str(plugin_dir),
        "available": not missing,
        "missing": missing,
        "paths": {name: str(path) for name, path in expected.items()},
    }


def _require_therapy_plugin(atlas_root: Path) -> dict[str, Any]:
    status = therapy_plugin_status(atlas_root)
    if not status["available"]:
        missing = ", ".join(status["missing"]) or "unknown"
        raise FileNotFoundError(
            f"therapy plugin is unavailable at {status['dir']} (missing: {missing})"
        )
    return status


def _run_therapy_script(atlas_root: Path, script_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    status = _require_therapy_plugin(atlas_root)
    script_path = Path(status["paths"][script_name])
    result = subprocess.run(
        [sys.executable, str(script_path)],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or f"therapy script failed: {script_name}"
        raise RuntimeError(message)
    try:
        decoded = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"therapy script returned invalid JSON: {script_name}") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError(f"therapy script must return an object: {script_name}")
    return decoded


def detect_therapy_patterns(atlas_root: Path, content: str) -> list[dict[str, Any]]:
    payload = _run_therapy_script(atlas_root, "detect", {"content": content})
    patterns = payload.get("patterns")
    if not isinstance(patterns, list):
        return []
    return [pattern for pattern in patterns if isinstance(pattern, dict)]


def counter_evidence_payload(atlas_root: Path, claim: str) -> dict[str, Any]:
    return _run_therapy_script(atlas_root, "counter_evidence", {"claim": claim})


def _load_interventions(atlas_root: Path) -> dict[str, Any]:
    status = _require_therapy_plugin(atlas_root)
    interventions_path = Path(status["paths"]["interventions"])
    raw = yaml.safe_load(interventions_path.read_text(encoding="utf-8")) or {}
    return raw if isinstance(raw, dict) else {}


def latest_mapsos_state() -> dict[str, Any]:
    exports = default_export_paths(latest=1)
    if not exports:
        return {}
    try:
        payload = load_mapsos_payload(str(exports[-1]))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _summarize_mapsos_state(payload: dict[str, Any]) -> list[str]:
    if not payload:
        return []
    lines: list[str] = []
    state = payload.get("state")
    if isinstance(state, str) and state.strip():
        lines.append(f"STATE: {state.strip()}")
    body = payload.get("body")
    if isinstance(body, dict):
        for key in ("energy", "sleep", "pain"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                lines.append(f"BODY {key}: {value.strip()}")
    arcs = payload.get("arcs")
    if isinstance(arcs, list):
        for arc in arcs[:4]:
            if isinstance(arc, str) and arc.strip():
                lines.append(f"ARC: {arc.strip()}")
            elif isinstance(arc, dict):
                label = arc.get("name") or arc.get("label") or arc.get("title")
                if isinstance(label, str) and label.strip():
                    lines.append(f"ARC: {label.strip()}")
    return lines


def build_therapy_review_context(
    *,
    working_set_entries: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    mapsos_state: dict[str, Any],
) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []
    lines: list[str] = []

    for line in _summarize_mapsos_state(mapsos_state):
        sources.append({"kind": "mapsos", "label": "latest mapsOS state", "content": line})
        lines.append(line)

    for entry in working_set_entries:
        body = str(entry.get("body") or "").strip()
        content = f"{entry['title']}" + (f" — {body}" if body else "")
        sources.append(
            {
                "kind": "working-set",
                "label": str(entry.get("title") or ""),
                "content": content,
                "provenance": list(entry.get("provenance") or []),
                "verification_needed": bool(entry.get("verification_needed")),
            }
        )
        lines.append(content)

    for session in sessions:
        summary = str(session.get("summary_preview") or "").strip()
        title = str(session.get("title") or session.get("id") or "session")
        if not summary:
            continue
        content = f"{title} — {summary}"
        sources.append(
            {
                "kind": "session",
                "label": title,
                "content": content,
                "path": str(session.get("path") or ""),
            }
        )
        lines.append(content)

    for task in tasks:
        text = str(task.get("text") or "").strip()
        if not text:
            continue
        priority = str(task.get("priority") or "").strip()
        content = f"OPEN TASK [{priority or 'task'}] {text}"
        sources.append(
            {
                "kind": "task",
                "label": text,
                "content": content,
                "path": str(task.get("path") or ""),
            }
        )
        lines.append(content)

    return {
        "content": "\n".join(lines).strip(),
        "sources": sources,
    }


def _matching_sources(
    sources: list[dict[str, Any]],
    keyword: str,
) -> list[dict[str, Any]]:
    needle = keyword.strip().lower()
    if not needle:
        return []
    matches: list[dict[str, Any]] = []
    for source in sources:
        content = str(source.get("content") or "")
        if needle in content.lower():
            matches.append(source)
    return matches


def build_therapy_review_payload(
    atlas_root: Path,
    *,
    working_set_entries: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    role: str,
    scope: str,
) -> dict[str, Any]:
    plugin = therapy_plugin_status(atlas_root)
    mapsos_state = latest_mapsos_state()
    context = build_therapy_review_context(
        working_set_entries=working_set_entries,
        sessions=sessions,
        tasks=tasks,
        mapsos_state=mapsos_state,
    )
    patterns: list[dict[str, Any]] = []
    if context["content"]:
        detected = detect_therapy_patterns(atlas_root, context["content"])
        interventions = _load_interventions(atlas_root)
        for pattern in detected:
            keyword = str(pattern.get("keyword_found") or "")
            pattern_name = str(pattern.get("pattern") or "")
            matching = _matching_sources(list(context["sources"]), keyword)[:3]
            claim = (
                str(matching[0].get("content") or "")
                if matching
                else keyword or pattern_name
            )
            counter = counter_evidence_payload(atlas_root, claim) if claim else {}
            intervention_items = interventions.get(pattern_name, {}).get("interventions", [])
            if not isinstance(intervention_items, list):
                intervention_items = []
            patterns.append(
                {
                    "pattern": pattern_name,
                    "keyword_found": keyword,
                    "counter_query": str(pattern.get("counter_query") or ""),
                    "matches": matching,
                    "counter_evidence": counter,
                    "interventions": [item for item in intervention_items if isinstance(item, dict)][:3],
                }
            )
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "role": role,
        "scope": scope,
        "plugin": plugin,
        "mapsos_state": mapsos_state,
        "working_set_entry_count": len(working_set_entries),
        "session_count": len(sessions),
        "task_count": len(tasks),
        "context": context,
        "pattern_count": len(patterns),
        "patterns": patterns,
    }


def render_therapy_review_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# Therapy Review — {date.today().isoformat()}",
        "",
        "## Scope",
        "",
        f"- role: {payload['role']}",
        f"- scope: {payload['scope']}",
        f"- plugin dir: {payload['plugin']['dir']}",
        f"- patterns detected: {payload['pattern_count']}",
        "",
        "## Patterns",
        "",
    ]
    patterns = payload.get("patterns") or []
    if patterns:
        for item in patterns:
            lines.append(f"- {item.get('pattern') or 'unknown'}")
            keyword = str(item.get("keyword_found") or "").strip()
            if keyword:
                lines.append(f"  - keyword: {keyword}")
            counter = item.get("counter_evidence") or {}
            queries = counter.get("counter_queries") if isinstance(counter, dict) else []
            if isinstance(queries, list) and queries:
                lines.append("  - counter-evidence:")
                for query in queries[:4]:
                    lines.append(f"    - {query}")
            matches = item.get("matches") or []
            if matches:
                lines.append("  - matched sources:")
                for match in matches[:3]:
                    lines.append(f"    - {match.get('label')}: {match.get('content')}")
    else:
        lines.append("- none")

    lines.extend(["", "## Context", ""])
    content = str(payload.get("context", {}).get("content") or "").strip()
    if content:
        lines.append("```text")
        lines.append(content)
        lines.append("```")
    else:
        lines.append("- no therapy context compiled")
    return "\n".join(lines).rstrip() + "\n"


def write_therapy_review(
    atlas_root: Path,
    *,
    payload: dict[str, Any],
    fmt: str,
    destination: Path | None = None,
) -> Path:
    output_path = destination or default_review_path(atlas_root, fmt=fmt)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        output_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    else:
        output_path.write_text(render_therapy_review_markdown(payload), encoding="utf-8")
    return output_path


def build_therapy_handoff_payload(
    *,
    working_set_entries: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
    role: str,
    scope: str,
) -> dict[str, Any]:
    provenance = sorted(
        {
            str(source)
            for entry in working_set_entries
            for source in entry.get("provenance", [])
            if source
        }
    )
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "role": role,
        "scope": scope,
        "entry_count": len(working_set_entries),
        "verification_needed_count": sum(
            1 for entry in working_set_entries if bool(entry.get("verification_needed"))
        ),
        "entries": working_set_entries,
        "recent_sessions": sessions,
        "provenance": provenance,
    }


def render_therapy_handoff_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# Therapy Handoff — {date.today().isoformat()}",
        "",
        "## Scope",
        "",
        f"- role: {payload['role']}",
        f"- scope: {payload['scope']}",
        f"- working-set entries: {payload['entry_count']}",
        f"- verification needed: {payload['verification_needed_count']}",
        "",
        "## Working Set",
        "",
    ]
    if payload["entries"]:
        for entry in payload["entries"]:
            verification = " [verify]" if entry.get("verification_needed") else ""
            body = str(entry.get("body") or "").strip()
            lines.append(f"- {entry['title']}{verification}")
            if body:
                lines.append(f"  - note: {body}")
            provenance = entry.get("provenance") or []
            if provenance:
                lines.append(
                    "  - provenance: " + ", ".join(str(item) for item in provenance)
                )
    else:
        lines.append("- none")

    lines.extend(["", "## Recent Sessions", ""])
    if payload["recent_sessions"]:
        for session in payload["recent_sessions"]:
            summary = str(session.get("summary_preview") or "").strip()
            suffix = f" — {summary}" if summary else ""
            lines.append(
                f"- {session.get('date') or 'unknown-date'} · {session.get('agent') or 'unknown-agent'} · {session.get('title') or session.get('id')}{suffix}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Provenance", ""])
    if payload["provenance"]:
        for source in payload["provenance"]:
            lines.append(f"- {source}")
    else:
        lines.append("- none")

    return "\n".join(lines).rstrip() + "\n"


def write_therapy_handoff(
    atlas_root: Path,
    *,
    payload: dict[str, Any],
    fmt: str,
    destination: Path | None = None,
) -> Path:
    output_path = destination or default_export_path(atlas_root, fmt=fmt)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        output_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    else:
        output_path.write_text(render_therapy_handoff_markdown(payload), encoding="utf-8")
    return output_path
