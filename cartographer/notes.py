from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .blocks import Block, insert_missing_block_ids, parse_blocks


FRONTMATTER_PATTERN = re.compile(r"\A---\n(?P<frontmatter>.*?)\n---\n?", re.DOTALL)
WIKILINK_PATTERN = re.compile(r"!?\[\[([^\]]+)\]\]")

LOCK_TIMEOUT = 10.0
LOCK_POLL_INTERVAL = 0.1


def _acquire_lock(path: Path) -> Path:
    lock_dir = path.parent / ".cartographer" / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{path.name}.lock"
    start_time = time.time()
    while lock_path.exists():
        if time.time() - start_time > LOCK_TIMEOUT:
            raise RuntimeError(f"lock timeout acquiring lock for {path}")
        time.sleep(LOCK_POLL_INTERVAL)
    lock_path.write_text(str(os.getpid()), encoding="utf-8")
    return lock_path


def _release_lock(lock_path: Path) -> None:
    if lock_path.exists():
        lock_path.unlink()


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
        try:
            from .guardrails import guardrails_pre_write

            guardrails_pre_write(self)
        except ImportError:
            pass
        lock_path = _acquire_lock(self.path)
        try:
            self.path.write_text(
                render(self.frontmatter, self.body),
                encoding="utf-8",
            )
        finally:
            _release_lock(lock_path)
