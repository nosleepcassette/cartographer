from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .blocks import ATTR_PATTERN, BLOCK_PATTERN
from .notes import Note, parse_link_target


WIRE_PATTERN = re.compile(r"<!--\s*cart:wire(?P<attrs>[^>]*)-->")

VALID_WIRE_PREDICATES = (
    "supports",
    "qualifies",
    "contradicts",
    "precedes",
    "follows",
    "part_of",
    "depends_on",
    "grounds",
    "intensifies_with",
    "co_occurs_with",
    "triggered_by",
    "relates_to_goal",
    "relates_to_person",
    "intention_outcome",
    "resistance_against",
)


def _parse_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class WireComment:
    source_note: str
    source_block: str | None
    target_note: str
    target_block: str | None
    predicate: str
    bidirectional: bool
    path: str
    line: int
    raw: str
    start: int
    end: int

    def payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("raw", None)
        payload.pop("start", None)
        payload.pop("end", None)
        return payload


@dataclass(slots=True)
class WireIssue:
    path: str
    line: int
    code: str
    message: str
    raw: str

    def payload(self) -> dict[str, Any]:
        return asdict(self)


def render_wire_comment(
    *,
    target_note: str,
    target_block: str | None,
    predicate: str,
    bidirectional: bool = False,
) -> str:
    target = target_note if target_block is None else f"{target_note}#{target_block}"
    attrs = [f'target="{target}"', f'predicate="{predicate}"']
    if bidirectional:
        attrs.append('bidirectional="true"')
    return f"<!-- cart:wire {' '.join(attrs)} -->"


def parse_wire_comments(
    body: str,
    *,
    note_id: str,
    path: Path | None = None,
) -> tuple[list[WireComment], list[WireIssue]]:
    block_spans: list[tuple[int, int, str]] = []
    for match in BLOCK_PATTERN.finditer(body):
        block_spans.append((match.start(), match.end(), match.group("id")))

    wires: list[WireComment] = []
    issues: list[WireIssue] = []
    path_text = "" if path is None else str(path)

    for match in WIRE_PATTERN.finditer(body):
        attrs = {key: value for key, value in ATTR_PATTERN.findall(match.group("attrs"))}
        target_raw = attrs.get("target", "").strip()
        predicate = attrs.get("predicate", "").strip()
        line = body.count("\n", 0, match.start()) + 1
        if not target_raw:
            issues.append(
                WireIssue(
                    path=path_text,
                    line=line,
                    code="missing_target",
                    message="wire comment is missing target",
                    raw=match.group(0),
                )
            )
            continue
        if not predicate:
            issues.append(
                WireIssue(
                    path=path_text,
                    line=line,
                    code="missing_predicate",
                    message="wire comment is missing predicate",
                    raw=match.group(0),
                )
            )
            continue
        target_note, target_block = parse_link_target(target_raw)
        if not target_note:
            issues.append(
                WireIssue(
                    path=path_text,
                    line=line,
                    code="invalid_target",
                    message="wire target could not be parsed",
                    raw=match.group(0),
                )
            )
            continue
        source_block = None
        for block_start, block_end, block_id in block_spans:
            if block_start <= match.start() <= block_end:
                source_block = block_id
                break
        wires.append(
            WireComment(
                source_note=note_id,
                source_block=source_block,
                target_note=target_note,
                target_block=target_block,
                predicate=predicate,
                bidirectional=_parse_bool(attrs.get("bidirectional")),
                path=path_text,
                line=line,
                raw=match.group(0),
                start=match.start(),
                end=match.end(),
            )
        )
    return wires, issues


def insert_wire_comment(note: Note, *, source_block: str | None, comment: str) -> None:
    if source_block is None:
        body = note.body.rstrip()
        note.body = f"{body}\n\n{comment}\n" if body else f"{comment}\n"
        return

    for match in BLOCK_PATTERN.finditer(note.body):
        if match.group("id") != source_block:
            continue
        insert_at = match.end("content")
        prefix = "" if match.group("content").endswith("\n") else "\n"
        suffix = "" if comment.endswith("\n") else "\n"
        note.body = (
            note.body[:insert_at]
            + f"{prefix}{comment}{suffix}"
            + note.body[insert_at:]
        )
        return
    raise ValueError(f"source block not found: {source_block}")


def remove_wire_spans(body: str, spans: list[tuple[int, int]]) -> str:
    updated = body
    for start, end in sorted(spans, reverse=True):
        removal_start = start
        while removal_start > 0 and updated[removal_start - 1] in {" ", "\t"}:
            removal_start -= 1
        removal_end = end
        while removal_end < len(updated) and updated[removal_end] in {" ", "\t"}:
            removal_end += 1
        if removal_end < len(updated) and updated[removal_end] == "\n":
            removal_end += 1
        updated = updated[:removal_start] + updated[removal_end:]
    return re.sub(r"\n{3,}", "\n\n", updated).rstrip() + "\n"
