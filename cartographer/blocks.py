from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field


BLOCK_PATTERN = re.compile(
    r'<!-- cart:block id="(?P<id>[^"]+)"(?P<attrs>[^>]*) -->'
    r"(?P<content>.*?)"
    r"<!-- /cart:block -->",
    re.DOTALL,
)
ATTR_PATTERN = re.compile(r'(\w+)="([^"]*)"')


@dataclass(slots=True)
class Block:
    id: str
    content: str
    type: str = "note"
    attrs: dict[str, str] = field(default_factory=dict)


def generate_block_id(prefix: str = "b") -> str:
    return f"{prefix}{uuid.uuid4().hex[:6]}"


def parse_block_attrs(raw_attrs: str) -> dict[str, str]:
    attrs = {key: value for key, value in ATTR_PATTERN.findall(raw_attrs)}
    if "type" not in attrs:
        attrs["type"] = "note"
    return attrs


def parse_blocks(text: str) -> list[Block]:
    blocks: list[Block] = []
    for match in BLOCK_PATTERN.finditer(text):
        attrs = parse_block_attrs(match.group("attrs"))
        blocks.append(
            Block(
                id=match.group("id"),
                content=match.group("content").strip(),
                type=attrs.get("type", "note"),
                attrs=attrs,
            )
        )
    return blocks


def insert_missing_block_ids(text: str) -> str:
    if not text.strip():
        return text
    paragraphs = re.split(r"(\n\s*\n)", text)
    rewritten: list[str] = []
    in_code_block = False
    for chunk in paragraphs:
        if not chunk:
            continue
        if re.fullmatch(r"\n\s*\n", chunk):
            rewritten.append(chunk)
            continue
        stripped = chunk.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            rewritten.append(chunk)
            continue
        if in_code_block or not stripped:
            rewritten.append(chunk)
            continue
        if BLOCK_PATTERN.search(chunk):
            rewritten.append(chunk)
            continue
        if stripped.startswith(
            ("<!--", "#", "- ", "* ", "+ ", ">", "|", "```")
        ):
            rewritten.append(chunk)
            continue
        block_id = generate_block_id("b")
        rewritten.append(
            f'<!-- cart:block id="{block_id}" -->\n{stripped}\n<!-- /cart:block -->'
        )
    output = "".join(rewritten)
    if not output.endswith("\n"):
        output += "\n"
    return output
