from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .agent_memory import LearningItem
from .session_import import ENTITY_PATTERNS, PROJECT_PATTERNS


DATE_FROM_FILENAME = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2})")
BLOCKQUOTE_PATTERN = re.compile(r"^>\s*(?P<quote>.+)$", re.MULTILINE)
TASK_CHECKBOX_PATTERN = re.compile(r"^- \[(?P<done>[ xX])\] (?P<text>.+)$", re.MULTILINE)
HEADING_PATTERN = re.compile(r"^## (?P<title>.+)$", re.MULTILINE)
SUBHEADING_PATTERN = re.compile(r"^### (?P<title>.+)$", re.MULTILINE)
STATE_PATTERN = re.compile(r"^\s*-\s*\*\*STATE:\*\*\s*(?P<value>.+?)\s*$", re.MULTILINE)
BODY_PATTERN = re.compile(r"^\s*-\s*\*\*BODY:\*\*\s*(?P<value>.+?)\s*$", re.MULTILINE)
INLINE_LABEL_PATTERN = re.compile(r"\*\*(?P<label>[^:*]+):\*\*")
TAG_PATTERN = re.compile(r"@(?P<tag>[a-zA-Z0-9_-]+)")

ARC_KEYWORD_PATTERNS = {
    "health": [
        r"\btherapist\b",
        r"\bsleep\b",
        r"\bfibromyalgia\b",
        r"\bpain\b",
        r"\bcymbalta\b",
        r"\bmirtazapine\b",
        r"\badderall\b",
        r"\bkaiser\b",
    ],
    "income": [
        r"\brent\b",
        r"\bverizon\b",
        r"\bmoney\b",
        r"\bdeposit\b",
        r"\binvoice\b",
        r"\bglide(?:sf)?\b",
    ],
    "relationship": [
        r"\bmaggie\b",
        r"\bsarah\b",
        r"\bemma(?:-x)?\b",
        r"\bbrennan\b",
        r"\brelationship\b",
        r"\bcrush\b",
    ],
    "grief": [
        r"\bgrief\b",
        r"\bgrieving\b",
        r"\bdad anniversary\b",
        r"\bfather\b",
    ],
    "readings": [
        r"\betsy\b",
        r"\breading(?:s)?\b",
        r"\bshowcase\b",
        r"\bastrological\b",
    ],
}

SECTION_TOPIC_OVERRIDES = {
    "self-doubt protocol": "self-doubt-protocol",
    "pattern watching (for therapist)": "pattern-watching",
    "pattern watching": "pattern-watching",
}

SECTION_CONFIDENCE = {
    "self-doubt-protocol": 0.95,
    "pattern-watching": 0.80,
}


@dataclass(slots=True)
class ParsedMapsOSIntake:
    path: Path
    date: str
    session_id: str
    payload: dict[str, Any]
    learnings: list[LearningItem]
    people: list[str]
    quotes: list[str]


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "mapsos"


def _normalize_lines(lines: list[str]) -> list[str]:
    normalized: list[str] = []
    for line in lines:
        stripped = re.sub(r"\s+", " ", line.strip())
        if stripped:
            normalized.append(stripped)
    return normalized


def _extract_session_date(path: Path, text: str) -> str:
    match = DATE_FROM_FILENAME.search(path.name)
    if match:
        return match.group("date")
    session_date_match = re.search(
        r"Session date:\s*(?P<value>[A-Za-z]+ \d{1,2}, \d{4})",
        text,
        re.IGNORECASE,
    )
    if session_date_match:
        return datetime.strptime(session_date_match.group("value"), "%B %d, %Y").date().isoformat()
    return datetime.today().date().isoformat()


def _section_body(text: str, heading: str) -> str | None:
    match = re.search(
        rf"^## {re.escape(heading)}\n(?P<body>.*?)(?=^## |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        return None
    body = match.group("body").strip()
    return body or None


def _top_level_sections(text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    matches = list(HEADING_PATTERN.finditer(text))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group("title").strip()] = text[start:end].strip()
    return sections


def _subsection_bodies(text: str) -> dict[str, str]:
    blocks: dict[str, str] = {}
    matches = list(SUBHEADING_PATTERN.finditer(text))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks[match.group("title").strip()] = text[start:end].strip()
    return blocks


def _extract_summary(text: str) -> str:
    sections = _subsection_bodies(_section_body(text, "Chronological Log") or "")
    if sections:
        last_heading = list(sections)[-1]
        lines = _normalize_lines(sections[last_heading].splitlines())
        bullet_lines = [
            line[2:].strip()
            for line in lines
            if line.startswith("- ") and "STATE:" not in line and "BODY:" not in line and "SPIRIT:" not in line
        ]
        if bullet_lines:
            return " ".join(bullet_lines[:3])
    wins = _section_body(text, "Wins")
    if wins:
        lines = _normalize_lines([line[2:].strip() for line in wins.splitlines() if line.strip().startswith("- ")])
        if lines:
            return "Wins: " + "; ".join(lines[:3])
    return "Narrative mapsOS intake imported from markdown."


def _extract_body_metrics(text: str) -> dict[str, str]:
    metrics: dict[str, str] = {}
    for match in BODY_PATTERN.finditer(text):
        parts = [part.strip() for part in match.group("value").split(",")]
        for part in parts:
            if ":" not in part:
                continue
            key, value = part.split(":", 1)
            normalized_key = key.strip().lower()
            normalized_value = value.strip()
            if normalized_key in {"sleep", "energy", "pain"} and normalized_value:
                metrics[normalized_key] = normalized_value
    return metrics


def _extract_tasks_from_section(section: str | None, *, numbered: bool = False) -> list[dict[str, str]]:
    if not section:
        return []
    tasks: list[dict[str, str]] = []
    for index, raw_line in enumerate(section.splitlines(), start=1):
        line = raw_line.strip()
        if numbered:
            match = re.match(r"^\d+\.\s+(?P<text>.+)$", line)
            if not match:
                continue
            title = match.group("text").strip()
            if title:
                tasks.append(
                    {
                        "id": f"active-goal-{index}",
                        "title": title,
                        "status": "open",
                    }
                )
            continue
        checkbox = TASK_CHECKBOX_PATTERN.match(line)
        if checkbox:
            tasks.append(
                {
                    "id": f"checkbox-{index}",
                    "title": checkbox.group("text").strip(),
                    "status": "done" if checkbox.group("done").lower() == "x" else "open",
                }
            )
            continue
        if not line.startswith("- "):
            continue
        title = re.sub(r"^\[\d+\]\s*", "", line[2:].strip())
        if not title:
            continue
        task: dict[str, str] = {
            "id": f"task-{index}",
            "title": title,
            "status": "open",
        }
        tag_match = TAG_PATTERN.search(title)
        if tag_match:
            task["arc"] = tag_match.group("tag")
        tasks.append(task)
    return tasks


def _extract_arcs(text: str, tasks: list[dict[str, str]]) -> list[str]:
    lowered = text.lower()
    arcs: list[str] = []
    for project_slug, metadata in PROJECT_PATTERNS.items():
        patterns = metadata.get("patterns", [])
        if isinstance(patterns, list) and any(re.search(pattern, lowered, re.IGNORECASE) for pattern in patterns):
            title = metadata.get("title") or project_slug
            arcs.append(str(title))
    for task in tasks:
        arc = task.get("arc")
        if arc:
            arcs.append(arc)
    for arc, patterns in ARC_KEYWORD_PATTERNS.items():
        if any(re.search(pattern, lowered, re.IGNORECASE) for pattern in patterns):
            arcs.append(arc)
    for match in INLINE_LABEL_PATTERN.finditer(text):
        label = _slugify(match.group("label"))
        if label in {"financial", "money"}:
            arcs.append("income")
        elif label in {"dad-anniversary", "grief"}:
            arcs.append("grief")
        elif label == "etsy":
            arcs.append("readings")
    return list(dict.fromkeys(arcs))


def _extract_people(text: str) -> list[str]:
    people: list[str] = []
    people_section = _section_body(text, "People in Orbit")
    if people_section:
        for raw_line in people_section.splitlines():
            if "|" not in raw_line or raw_line.strip().startswith("| Name"):
                continue
            cells = [cell.strip() for cell in raw_line.strip().strip("|").split("|")]
            if cells and cells[0] and cells[0] != "------":
                people.append(cells[0])
    lowered = text.lower()
    for slug, metadata in ENTITY_PATTERNS.items():
        patterns = metadata.get("patterns", [])
        if isinstance(patterns, list) and any(re.search(pattern, lowered, re.IGNORECASE) for pattern in patterns):
            people.append(str(metadata.get("title") or slug))
    return list(dict.fromkeys(person for person in people if person))


def _extract_quotes(text: str) -> list[str]:
    quotes = [match.group("quote").strip() for match in BLOCKQUOTE_PATTERN.finditer(text)]
    return list(dict.fromkeys(quote for quote in quotes if quote))


def _extract_section_learnings(
    section_name: str,
    section_body: str,
    *,
    intake_date: str,
    session_id: str,
) -> list[LearningItem]:
    normalized_topic = SECTION_TOPIC_OVERRIDES.get(section_name.lower())
    if normalized_topic is None:
        return []
    lines = [
        re.sub(r"^- ", "", line.strip())
        for line in section_body.splitlines()
        if line.strip().startswith("- ")
    ]
    confidence = SECTION_CONFIDENCE.get(normalized_topic, 0.75)
    return [
        LearningItem(
            topic=normalized_topic,
            text=line,
            confidence=confidence,
            confidence_label="high" if confidence >= 0.9 else "medium",
            source="mapsos-intake",
            source_session=session_id,
            source_agent="mapsOS",
            date=intake_date,
        )
        for line in lines
        if line
    ]


def _extract_direct_learnings(text: str, *, intake_date: str, session_id: str) -> list[LearningItem]:
    items: list[LearningItem] = []
    medical_context = _section_body(text, "Medical Context") or ""
    if "priority-0 therapist intake material" in medical_context.lower():
        items.append(
            LearningItem(
                topic="therapist-intake",
                text="Trauma nightmares and sleep disruption are priority-0 therapist intake material.",
                confidence=0.90,
                confidence_label="high",
                source="mapsos-intake",
                source_session=session_id,
                source_agent="mapsOS",
                date=intake_date,
            )
        )
    return items


def parse_mapsos_intake(path: str | Path) -> ParsedMapsOSIntake:
    intake_path = Path(path).expanduser()
    text = intake_path.read_text(encoding="utf-8")
    intake_date = _extract_session_date(intake_path, text)
    session_id = f"mapsos-intake-{intake_date}-{_slugify(intake_path.stem)}"
    state_matches = [match.group("value").strip() for match in STATE_PATTERN.finditer(text)]
    tasks = []
    tasks.extend(_extract_tasks_from_section(_section_body(text, "Active Goals"), numbered=True))
    tasks.extend(_extract_tasks_from_section(_section_body(text, "Nota Tasks Added")))
    for index, match in enumerate(TASK_CHECKBOX_PATTERN.finditer(text), start=len(tasks) + 1):
        tasks.append(
            {
                "id": f"checkbox-{index}",
                "title": match.group("text").strip(),
                "status": "done" if match.group("done").lower() == "x" else "open",
            }
        )
    quotes = _extract_quotes(text)
    people = _extract_people(text)
    body = _extract_body_metrics(text)
    arcs = _extract_arcs(text, tasks)
    learnings: list[LearningItem] = []
    for section_name, section_body in _top_level_sections(text).items():
        learnings.extend(
            _extract_section_learnings(
                section_name,
                section_body,
                intake_date=intake_date,
                session_id=session_id,
            )
        )
    for section_name, section_body in _subsection_bodies(text).items():
        learnings.extend(
            _extract_section_learnings(
                section_name,
                section_body,
                intake_date=intake_date,
                session_id=session_id,
            )
        )
    learnings.extend(_extract_direct_learnings(text, intake_date=intake_date, session_id=session_id))
    payload: dict[str, Any] = {
        "date": intake_date,
        "state": state_matches[-1] if state_matches else "unknown",
        "body": body,
        "arcs": arcs,
        "tasks": tasks,
        "summary": _extract_summary(text),
        "quotes": quotes,
        "people": people,
        "source_type": "markdown-intake",
        "source_path": str(intake_path),
        "source_session": session_id,
        "source_agent": "mapsOS",
        "notes": f"Imported from {intake_path.name}",
    }
    return ParsedMapsOSIntake(
        path=intake_path,
        date=intake_date,
        session_id=session_id,
        payload=payload,
        learnings=learnings,
        people=people,
        quotes=quotes,
    )
