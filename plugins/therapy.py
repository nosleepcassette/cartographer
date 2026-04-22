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


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def main() -> None:
    payload = json.load(sys.stdin)
    args = payload.get("args", {})
    argv = list(args.get("_argv", [])) if isinstance(args, dict) else []
    command = str(argv[0] if argv else args.get("command") or "review")

    if command == "review":
        command_args = ["therapy", "review", "--json"]
        if _truthy(args.get("temporal")):
            command_args.append("--temporal")
        result = _run_cart(command_args)
    elif command == "counter-evidence":
        claim = str(args.get("claim") or " ".join(argv[1:])).strip()
        if not claim:
            result = {
                "output": "",
                "payload": None,
                "writes": [],
                "errors": ["therapy counter-evidence requires claim=<text> or trailing words"],
            }
        else:
            result = _run_cart(["therapy", "counter-evidence", claim, "--json"])
    else:
        result = {
            "output": "",
            "payload": None,
            "writes": [],
            "errors": [f"unknown therapy plugin command: {command}"],
        }

    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
