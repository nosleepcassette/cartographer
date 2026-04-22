#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys


def _run_cart(arguments: list[str]) -> dict[str, object]:
    env = os.environ.copy()
    result = subprocess.run(
        [sys.executable, "-m", "cartographer.cli", *arguments],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    output = result.stdout.strip()
    errors: list[str] = []
    payload = None
    if result.returncode != 0:
        message = result.stderr.strip() or output or f"cart {' '.join(arguments)} failed"
        errors.append(message)
    elif output:
        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            payload = None
    return {
        "output": output,
        "payload": payload,
        "writes": [],
        "errors": errors,
    }


def main() -> None:
    payload = json.load(sys.stdin)
    args = payload.get("args", {})
    argv = list(args.get("_argv", [])) if isinstance(args, dict) else []
    command = str(argv[0] if argv else args.get("command") or "detect")

    command_args = ["temporal-patterns", "--json"]
    signal = str(args.get("signal") or "").strip()
    if signal:
        command_args.extend(["--signal", signal])
    lead = str(args.get("lead") or "").strip()
    if lead:
        command_args.extend(["--lead", lead])
    min_n = str(args.get("min_n") or args.get("min-n") or "").strip()
    if min_n:
        command_args.extend(["--min-n", min_n])
    if command == "report" or str(args.get("write") or "").strip().lower() in {"1", "true", "yes", "on"}:
        command_args.append("--write")

    result = _run_cart(command_args)
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
