#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from cartographer.daily_brief import build_daily_brief


def _bool_or_none(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def main() -> None:
    payload = json.load(sys.stdin)
    atlas_root = Path(os.environ["CARTOGRAPHER_ROOT"]).expanduser()
    args = payload.get("args", {})
    output_format = str(args.get("format", "markdown"))
    output = build_daily_brief(
        atlas_root,
        format=output_format,
        include_temporal=_bool_or_none(args.get("temporal")),
    )
    json.dump({"output": output, "writes": [], "errors": []}, sys.stdout)


if __name__ == "__main__":
    main()
