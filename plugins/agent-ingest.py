#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from cartographer.agent_memory import build_agent_ingest_result


def main() -> None:
    payload = json.load(sys.stdin)
    atlas_root = Path(os.environ["CARTOGRAPHER_ROOT"]).expanduser()
    args = payload.get("args", {})
    agent = str(args.get("agent", "hermes"))
    source_path = str(args.get("source_path", "session.json"))
    session_data = payload.get("session", {})
    result = build_agent_ingest_result(atlas_root, agent, source_path, session_data)
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
