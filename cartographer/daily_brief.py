from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from .agent_memory import iter_learning_blocks
from .notes import Note
from .patterns import entries_since, latest_entry, load_state_log, recent_entries, summarize_patterns
from .tasks import iter_tasks, sort_tasks


SECTION_PATTERN = re.compile(
    r"^## (?P<title>.+)\n(?P<body>.*?)(?=^## |\Z)",
    re.MULTILINE | re.DOTALL,
)


def _extract_section(body: str, title: str) -> str:
    for match in SECTION_PATTERN.finditer(body):
        if match.group("title").strip().lower() == title.lower():
            return match.group("body").strip()
    return ""


def _recent_learning_lines(root: Path, *, days: int) -> list[str]:
    cutoff = date.today() - timedelta(days=days)
    lines: list[str] = []
    for item in iter_learning_blocks(root):
        attrs = item.attrs
        learned_on = attrs.get("date")
        if not learned_on:
            continue
        try:
            learned_date = date.fromisoformat(learned_on)
        except ValueError:
            continue
        if learned_date < cutoff:
            continue
        rejected = attrs.get("rejected") == "1"
        confirmed = attrs.get("confirmed") == "1"
        try:
            confidence = float(attrs.get("confidence", "0"))
        except ValueError:
            confidence = 0.0
        if rejected or (not confirmed and confidence < 0.75):
            continue
        source_agent = attrs.get("source_agent") or item.path.parts[-3]
        lines.append(f"- [{source_agent}/{item.path.stem}] {item.content}")
    return lines[:8]


def _active_arcs_lines(root: Path) -> list[str]:
    entries = entries_since(load_state_log(root), (date.today() - timedelta(days=7)).isoformat())
    if not entries:
        return ["- none tracked yet"]
    counts: dict[str, int] = {}
    for entry in entries:
        for arc in entry.arcs_active:
            counts[arc] = counts.get(arc, 0) + 1
    if not counts:
        return ["- none tracked yet"]
    return [f"- {arc} ({count})" for arc, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:6]]


def build_daily_brief(root: Path, *, format: str = "markdown") -> str:
    open_tasks = sort_tasks(iter_tasks(root, include_done=False))
    tasks = [
        task
        for task in open_tasks
        if task.priority in {"P0", "P1"}
    ][:8]
    if not tasks:
        tasks = open_tasks[:8]
    task_lines = [
        f"- [{task.priority}] {task.text}" + (f" ({task.project})" if task.project else "")
        for task in tasks
    ] or ["- none"]

    last_state = latest_entry(root)
    if last_state is None:
        state_lines = ["- no mapsOS state tracked yet"]
    else:
        state_lines = [
            f"- state: {last_state.state} ({last_state.day})",
            f"- sleep: {last_state.sleep or 'unknown'}, energy: {last_state.energy or 'unknown'}, pain: {last_state.pain or 'unknown'}",
        ]

    pattern_entries = recent_entries(load_state_log(root), count=5)
    pattern_summary = summarize_patterns(pattern_entries)
    pattern_lines = [f"- {line}" if index > 0 else f"- {line}" for index, line in enumerate(pattern_summary.splitlines())] if pattern_entries else ["- no pattern data yet"]

    learning_lines = _recent_learning_lines(root, days=7) or ["- none"]

    master_summary_path = root / "agents" / "MASTER_SUMMARY.md"
    open_questions_lines = ["- none captured"]
    if master_summary_path.exists():
        master_note = Note.from_file(master_summary_path)
        open_questions = _extract_section(master_note.body, "open questions")
        extracted = [line for line in open_questions.splitlines() if line.strip()]
        if extracted:
            open_questions_lines = [line if line.startswith("- ") else f"- {line}" for line in extracted[:8]]

    sections = [
        f"# atlas brief — {date.today().isoformat()}",
        "",
        "## open tasks (P0-P1)",
        *task_lines,
        "",
        "## active arcs",
        *_active_arcs_lines(root),
        "",
        "## last mapsOS state",
        *state_lines,
        "",
        "## recent patterns (last 5 sessions)",
        *pattern_lines,
        "",
        "## recent learnings (last 7 days)",
        *learning_lines,
        "",
        "## open questions",
        *open_questions_lines,
    ]
    markdown = "\n".join(sections).rstrip() + "\n"
    if format == "markdown":
        return markdown
    if format == "plain":
        return re.sub(r"^#\s*", "", markdown, flags=re.MULTILINE)
    raise ValueError(f"unsupported brief format: {format}")
