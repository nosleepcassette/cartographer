#!/usr/bin/env python3
from __future__ import annotations

import json
import sys


def main() -> None:
    payload = json.load(sys.stdin)
    notes = payload.get("notes", [])
    items: list[str] = []
    for note in notes[:10]:
        title = note.get("frontmatter", {}).get("title") or note.get("id") or "untitled"
        snippet = " ".join(str(note.get("content", "")).split()[:18])
        items.append(f"- {title}: {snippet}".rstrip(": "))
    output = "# daily brief\n\n" + ("\n".join(items) if items else "- no notes provided")
    json.dump({"output": output, "writes": [], "errors": []}, sys.stdout)


if __name__ == "__main__":
    main()
