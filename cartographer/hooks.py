from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def atlas_hook_dir(atlas_root: Path) -> Path:
    return atlas_root / ".cartographer" / "hooks"


def ensure_hook_dir(atlas_root: Path) -> Path:
    directory = atlas_hook_dir(atlas_root)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def resolve_hook_path(atlas_root: Path, name: str) -> Path | None:
    directory = ensure_hook_dir(atlas_root)
    for candidate in (directory / name, directory / f"{name}.py"):
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def run_hook(atlas_root: Path, name: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    hook_path = resolve_hook_path(atlas_root, name)
    if hook_path is None:
        return None
    env = os.environ.copy()
    env["CARTOGRAPHER_ROOT"] = str(atlas_root)
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{PACKAGE_ROOT}{os.pathsep}{existing_pythonpath}"
        if existing_pythonpath
        else str(PACKAGE_ROOT)
    )
    command = [sys.executable, str(hook_path)] if hook_path.suffix == ".py" else [str(hook_path)]
    result = subprocess.run(
        command,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=atlas_root,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or f"hook failed: {name}"
        raise RuntimeError(message)
    raw = result.stdout.strip()
    return None if not raw else json.loads(raw)
