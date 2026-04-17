from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .blocks import Block, insert_missing_block_ids, parse_blocks


FRONTMATTER_PATTERN = re.compile(r"\A---\n(?P<frontmatter>.*?)\n---\n?", re.DOTALL)
WIKILINK_PATTERN = re.compile(r"!?\[\[([^\]]+)\]\]")


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = FRONTMATTER_PATTERN.match(text)
    if not match:
        return {}, text
    raw_frontmatter = match.group("frontmatter")
    data = yaml.safe_load(raw_frontmatter) or {}
    if not isinstance(data, dict):
        data = {}
    body = text[match.end() :]
    return data, body


def render(frontmatter: dict[str, Any], body: str) -> str:
    payload = yaml.safe_dump(
        frontmatter,
        sort_keys=False,
        allow_unicode=False,
        default_flow_style=False,
    ).strip()
    rendered = f"---\n{payload}\n---\n\n{body.lstrip()}" if payload else body
    if not rendered.endswith("\n"):
        rendered += "\n"
    return rendered


def parse_link_target(target: str) -> tuple[str, str | None]:
    clean_target = target.split("|", 1)[0].strip()
    if "#" in clean_target:
        note_id, block_id = clean_target.split("#", 1)
        return note_id.strip(), block_id.strip()
    return clean_target, None


def extract_wikilinks(text: str) -> list[tuple[str, str | None]]:
    links: list[tuple[str, str | None]] = []
    for match in WIKILINK_PATTERN.finditer(text):
        raw_target = match.group(1).strip()
        if not raw_target:
            continue
        note_id, block_id = parse_link_target(raw_target)
        if note_id:
            links.append((note_id, block_id))
    return links


@dataclass(slots=True)
class Note:
    path: Path
    frontmatter: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    blocks: list[Block] = field(default_factory=list)

    @classmethod
    def from_file(cls, path: Path) -> "Note":
        text = path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(text)
        blocks = parse_blocks(body)
        return cls(path=path, frontmatter=frontmatter, body=body, blocks=blocks)

    def write(self, ensure_blocks: bool = False) -> None:
        if ensure_blocks and self.frontmatter.get("auto_blocks"):
            self.body = insert_missing_block_ids(self.body)
        self.blocks = parse_blocks(self.body)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            render(self.frontmatter, self.body),
            encoding="utf-8",
        )
