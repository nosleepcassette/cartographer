from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any


def therapy_export_dir(atlas_root: Path) -> Path:
    return atlas_root / "notes" / "therapy" / "exports"


def default_export_path(atlas_root: Path, *, fmt: str) -> Path:
    extension = "json" if fmt == "json" else "md"
    return therapy_export_dir(atlas_root) / f"notes-therapy-handoff-{date.today().isoformat()}.{extension}"


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
