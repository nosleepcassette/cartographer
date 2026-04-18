from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .blocks import ATTR_PATTERN, BLOCK_PATTERN
from .notes import Note, parse_link_target


WIRE_PATTERN = re.compile(r"<!--\s*cart:wire(?P<attrs>[^>]*)-->")

VALID_WIRE_PREDICATES = (
    "relates_to",
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
    "active-project",
    "core-infrastructure",
)

VALID_EMOTIONAL_VALENCES = ("positive", "negative", "mixed", "neutral")
VALID_ENERGY_IMPACTS = ("draining", "energizing", "neutral", "conflicted")
VALID_AVOIDANCE_RISKS = ("high", "medium", "low", "none")
VALID_CURRENT_STATES = (
    "active",
    "grieving",
    "building",
    "recovering",
    "suspended",
    "provisional",
)


def _parse_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_optional_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return None


def _normalize_text_attr(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = html.unescape(value).strip()
    return normalized or None


def _quote_attr(value: str) -> str:
    return html.escape(value, quote=True)


@dataclass(slots=True)
class WireComment:
    source_note: str
    source_block: str | None
    target_note: str
    target_block: str | None
    predicate: str
    bidirectional: bool
    relationship: str | None
    emotional_valence: str | None
    energy_impact: str | None
    avoidance_risk: str | None
    growth_edge: bool | None
    current_state: str | None
    since: str | None
    until: str | None
    valence_note: str | None
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
    relationship: str | None = None,
    emotional_valence: str | None = None,
    energy_impact: str | None = None,
    avoidance_risk: str | None = None,
    growth_edge: bool | None = None,
    current_state: str | None = None,
    since: str | None = None,
    until: str | None = None,
    valence_note: str | None = None,
) -> str:
    target = target_note if target_block is None else f"{target_note}#{target_block}"
    attrs = [f'target="{_quote_attr(target)}"', f'predicate="{_quote_attr(predicate)}"']
    if bidirectional:
        attrs.append('bidirectional="true"')
    if relationship:
        attrs.append(f'relationship="{_quote_attr(relationship)}"')
    if emotional_valence:
        attrs.append(f'emotional_valence="{_quote_attr(emotional_valence)}"')
    if energy_impact:
        attrs.append(f'energy_impact="{_quote_attr(energy_impact)}"')
    if avoidance_risk:
        attrs.append(f'avoidance_risk="{_quote_attr(avoidance_risk)}"')
    if growth_edge is not None:
        attrs.append(f'growth_edge="{"true" if growth_edge else "false"}"')
    if current_state:
        attrs.append(f'current_state="{_quote_attr(current_state)}"')
    if since:
        attrs.append(f'since="{_quote_attr(since)}"')
    if until:
        attrs.append(f'until="{_quote_attr(until)}"')
    if valence_note:
        attrs.append(f'valence_note="{_quote_attr(valence_note)}"')
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
        predicate = _normalize_text_attr(attrs.get("predicate")) or _normalize_text_attr(
            attrs.get("relationship")
        )
        relationship = _normalize_text_attr(attrs.get("relationship"))
        emotional_valence = _normalize_text_attr(attrs.get("emotional_valence"))
        energy_impact = _normalize_text_attr(attrs.get("energy_impact"))
        avoidance_risk = _normalize_text_attr(attrs.get("avoidance_risk"))
        growth_edge = _parse_optional_bool(attrs.get("growth_edge"))
        current_state = _normalize_text_attr(attrs.get("current_state"))
        since = _normalize_text_attr(attrs.get("since"))
        until = _normalize_text_attr(attrs.get("until"))
        valence_note = _normalize_text_attr(attrs.get("valence_note"))
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
        if emotional_valence is not None and emotional_valence not in VALID_EMOTIONAL_VALENCES:
            issues.append(
                WireIssue(
                    path=path_text,
                    line=line,
                    code="invalid_emotional_valence",
                    message=f"invalid emotional valence: {emotional_valence}",
                    raw=match.group(0),
                )
            )
        if energy_impact is not None and energy_impact not in VALID_ENERGY_IMPACTS:
            issues.append(
                WireIssue(
                    path=path_text,
                    line=line,
                    code="invalid_energy_impact",
                    message=f"invalid energy impact: {energy_impact}",
                    raw=match.group(0),
                )
            )
        if avoidance_risk is not None and avoidance_risk not in VALID_AVOIDANCE_RISKS:
            issues.append(
                WireIssue(
                    path=path_text,
                    line=line,
                    code="invalid_avoidance_risk",
                    message=f"invalid avoidance risk: {avoidance_risk}",
                    raw=match.group(0),
                )
            )
        if attrs.get("growth_edge") is not None and growth_edge is None:
            issues.append(
                WireIssue(
                    path=path_text,
                    line=line,
                    code="invalid_growth_edge",
                    message=f"invalid growth_edge value: {attrs.get('growth_edge')}",
                    raw=match.group(0),
                )
            )
        if current_state is not None and current_state not in VALID_CURRENT_STATES:
            issues.append(
                WireIssue(
                    path=path_text,
                    line=line,
                    code="invalid_current_state",
                    message=f"invalid current state: {current_state}",
                    raw=match.group(0),
                )
            )
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
                relationship=relationship,
                emotional_valence=emotional_valence,
                energy_impact=energy_impact,
                avoidance_risk=avoidance_risk,
                growth_edge=growth_edge,
                current_state=current_state,
                since=since,
                until=until,
                valence_note=valence_note,
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
