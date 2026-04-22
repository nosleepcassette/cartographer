#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import sys


def main() -> None:
    payload = json.load(sys.stdin)
    args = payload.get("args", {})
    argv = list(args.get("_argv", [])) if isinstance(args, dict) else []
    command = str(argv[0] if argv else args.get("command") or "status")
    plugin_dir = Path(
        os.environ.get("CART_AVOIDANCE_PLUGIN_DIR", "").strip()
        or (Path(os.environ.get("CARTOGRAPHER_ROOT", "~/atlas")).expanduser() / "agents" / "cassette" / "skills" / "avoidance-intervention")
    ).expanduser()
    status = {
        "available": plugin_dir.exists(),
        "dir": str(plugin_dir),
        "command": command,
    }
    errors = [] if status["available"] else [
        f"avoidance plugin unavailable at {plugin_dir}; install or point CART_AVOIDANCE_PLUGIN_DIR at a plugin checkout"
    ]
    json.dump(
        {
            "output": json.dumps(status, ensure_ascii=False),
            "payload": status,
            "writes": [],
            "errors": errors,
        },
        sys.stdout,
    )


if __name__ == "__main__":
    main()
