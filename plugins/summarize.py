#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys


def clean_markdown(text: str) -> str:
    text = re.sub(r"<!-- cart:block[^>]* -->", " ", text)
    text = text.replace("<!-- /cart:block -->", " ")
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"^#+\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def main() -> None:
    payload = json.load(sys.stdin)
    args = payload.get("args", {})
    max_words = int(args.get("max_words", 300))
    notes = payload.get("notes", [])
    lines: list[str] = []
    for note in notes:
        title = note.get("frontmatter", {}).get("title") or note.get("id") or note.get("path")
        note_type = note.get("frontmatter", {}).get("type", "note")
        body = clean_markdown(str(note.get("content", "")))
        excerpt = " ".join(body.split()[:28])
        if excerpt:
            lines.append(f"- [{note_type}] {title}: {excerpt}")
        else:
            lines.append(f"- [{note_type}] {title}")
    if not lines:
        output = "no notes matched"
    else:
        summary = "\n".join(lines)
        words = summary.split()
        output = " ".join(words[:max_words])
    json.dump({"output": output, "writes": [], "errors": []}, sys.stdout)


if __name__ == "__main__":
    main()
