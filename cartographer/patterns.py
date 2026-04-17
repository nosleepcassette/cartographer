from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from .notes import Note


STATE_LOG_ROW_PATTERN = re.compile(
    r"^\|\s*(?P<date>\d{4}-\d{2}-\d{2})\s*\|"
    r"\s*(?P<state>[^|]*)\|"
    r"\s*(?P<sleep>[^|]*)\|"
    r"\s*(?P<energy>[^|]*)\|"
    r"\s*(?P<pain>[^|]*)\|"
    r"\s*(?P<arcs>[^|]*)\|"
    r"\s*(?P<source>[^|]*)\|?\s*$",
    re.MULTILINE,
)

GOOD_SLEEP_KEYWORDS = ("solid", "deep", "ok", "good", "rested", "restorative")
DISRUPTED_SLEEP_KEYWORDS = ("none", "poor", "disrupt", "insomnia", "fragment", "deplet", "off")
HIGH_PAIN_KEYWORDS = ("high", "severe", "flare", "spike")


@dataclass(slots=True)
class StateLogEntry:
    day: str
    state: str
    sleep: str
    energy: str
    pain: str
    arcs_active: list[str]
    source: str = "mapsOS"


def state_log_path(root: Path) -> Path:
    return root / "agents" / "mapsOS" / "state-log.md"


def load_state_log(root: Path) -> list[StateLogEntry]:
    path = state_log_path(root)
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    entries: list[StateLogEntry] = []
    for match in STATE_LOG_ROW_PATTERN.finditer(text):
        if match.group("date") == "---":
            continue
        arcs = [item.strip() for item in match.group("arcs").split(",") if item.strip() and item.strip() != "none"]
        entries.append(
            StateLogEntry(
                day=match.group("date").strip(),
                state=match.group("state").strip(),
                sleep=match.group("sleep").strip(),
                energy=match.group("energy").strip(),
                pain=match.group("pain").strip(),
                arcs_active=arcs,
                source=match.group("source").strip() or "mapsOS",
            )
        )
    return sorted(entries, key=lambda item: item.day)


def recent_entries(entries: list[StateLogEntry], *, count: int) -> list[StateLogEntry]:
    return entries[-count:] if count > 0 else entries[:]


def entries_since(entries: list[StateLogEntry], since: str | None) -> list[StateLogEntry]:
    if since is None:
        return entries[:]
    cutoff = datetime.fromisoformat(since).date()
    return [entry for entry in entries if datetime.fromisoformat(entry.day).date() >= cutoff]


def latest_entry(root: Path) -> StateLogEntry | None:
    entries = load_state_log(root)
    return entries[-1] if entries else None


def _normalized_value(entry: StateLogEntry, field: str) -> str:
    value = getattr(entry, field, "")
    normalized = value.strip() if isinstance(value, str) else str(value).strip()
    return normalized or "unknown"


def field_frequencies(entries: list[StateLogEntry], field: str) -> Counter[str]:
    if field == "arcs_active":
        counts: Counter[str] = Counter()
        for entry in entries:
            counts.update(entry.arcs_active)
        return counts
    return Counter(_normalized_value(entry, field) for entry in entries)


def _bar(count: int, total: int) -> str:
    if count <= 0 or total <= 0:
        return ""
    width = max(1, round((count / total) * 12))
    return "▓" * width


def _sleep_disrupted(value: str) -> bool:
    lowered = value.lower()
    if any(keyword in lowered for keyword in GOOD_SLEEP_KEYWORDS):
        return False
    return any(keyword in lowered for keyword in DISRUPTED_SLEEP_KEYWORDS)


def _high_pain(value: str) -> bool:
    lowered = value.lower()
    return any(keyword in lowered for keyword in HIGH_PAIN_KEYWORDS)


def summarize_patterns(entries: list[StateLogEntry], field: str | None = None) -> str:
    if not entries:
        return "state log: 0 sessions"
    target_field = field or "state"
    if target_field in {"state", "sleep", "energy", "pain", "arcs", "arcs_active"}:
        normalized_field = "arcs_active" if target_field == "arcs" else target_field
    else:
        raise ValueError(f"unsupported patterns field: {field}")
    counts = field_frequencies(entries, normalized_field)
    total = len(entries) if normalized_field != "arcs_active" else max(sum(counts.values()), 1)
    lines = [f"state log: {len(entries)} sessions" if field is None else f"{normalized_field}: {len(entries)} sessions"]
    for value, count in counts.most_common():
        lines.append(f"  {value}: {count:>3}  {_bar(count, total)}".rstrip())
    if field is not None:
        return "\n".join(lines)
    sleep_disruption = sum(1 for entry in entries if _sleep_disrupted(entry.sleep))
    high_pain = sum(1 for entry in entries if _high_pain(entry.pain))
    arc_counts = field_frequencies(entries, "arcs_active")
    lines.append(f"sleep disruption: {sleep_disruption}/{len(entries)} sessions")
    lines.append(f"high pain: {high_pain}/{len(entries)} sessions")
    if arc_counts:
        top_arcs = ", ".join(f"{arc} ({count})" for arc, count in arc_counts.most_common(5))
        lines.append(f"most active arcs: {top_arcs}")
    else:
        lines.append("most active arcs: none")
    return "\n".join(lines)


def render_state_log_note(entries: list[StateLogEntry]) -> Note:
    today = date.today().isoformat()
    body_lines = [
        "# mapsOS state log",
        "",
        "## state log",
        "",
        "| date | state | sleep | energy | pain | arcs active | source |",
        "|---|---|---|---|---|---|---|",
    ]
    for entry in entries:
        arcs = ", ".join(entry.arcs_active) if entry.arcs_active else "none"
        body_lines.append(
            f"| {entry.day} | {entry.state or 'unknown'} | {entry.sleep or 'unknown'} | "
            f"{entry.energy or 'unknown'} | {entry.pain or 'unknown'} | {arcs} | {entry.source or 'mapsOS'} |"
        )
    return Note(
        path=Path("agents") / "mapsOS" / "state-log.md",
        frontmatter={
            "id": "mapsos-state-log",
            "title": "mapsOS State Log",
            "type": "note",
            "source": "mapsOS",
            "created": today,
            "modified": today,
        },
        body="\n".join(body_lines).rstrip() + "\n",
    )
