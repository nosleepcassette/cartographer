from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

from .hooks import run_hook


BUILTIN_PLUGIN_DIR = Path(__file__).resolve().parent.parent / "plugins"
PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def atlas_plugin_dir(atlas_root: Path) -> Path:
    return atlas_root / ".cartographer" / "plugins"


def sync_builtin_plugins(atlas_root: Path) -> list[Path]:
    target_dir = atlas_plugin_dir(atlas_root)
    target_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for source in sorted(BUILTIN_PLUGIN_DIR.glob("*.py")):
        target = target_dir / source.name
        should_copy = not target.exists() or source.read_text(encoding="utf-8") != target.read_text(
            encoding="utf-8"
        )
        if should_copy:
            shutil.copy2(source, target)
            target.chmod(target.stat().st_mode | stat.S_IXUSR)
            written.append(target)
    return written


def list_plugins(atlas_root: Path) -> list[str]:
    sync_builtin_plugins(atlas_root)
    plugins: set[str] = set()
    for path in atlas_plugin_dir(atlas_root).iterdir():
        if path.is_file() and not path.name.startswith("."):
            plugins.add(path.stem)
    return sorted(plugins)


def resolve_plugin_path(atlas_root: Path, name: str) -> Path:
    sync_builtin_plugins(atlas_root)
    candidates = [
        atlas_plugin_dir(atlas_root) / name,
        atlas_plugin_dir(atlas_root) / f"{name}.py",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    available = ", ".join(list_plugins(atlas_root)) or "none"
    raise FileNotFoundError(f"plugin not found: {name}. available: {available}")


def parse_plugin_args(args: tuple[str, ...] | list[str]) -> dict[str, Any]:
    parsed: dict[str, Any] = {"_argv": list(args)}
    for token in args:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        parsed[key] = value
    return parsed


def _pythonpath_env() -> str:
    existing = os.environ.get("PYTHONPATH")
    if existing:
        return f"{PACKAGE_ROOT}{os.pathsep}{existing}"
    return str(PACKAGE_ROOT)


def _plugin_command(plugin_path: Path) -> list[str]:
    if plugin_path.suffix == ".py":
        return [sys.executable, str(plugin_path)]
    return [str(plugin_path)]


def _normalize_write_path(atlas_root: Path, path_value: str) -> Path:
    raw_path = Path(path_value).expanduser()
    destination = raw_path if raw_path.is_absolute() else atlas_root / raw_path
    resolved_root = atlas_root.resolve()
    resolved_destination = destination.resolve()
    if resolved_destination != resolved_root and resolved_root not in resolved_destination.parents:
        raise ValueError(f"write path escapes atlas root: {path_value}")
    return resolved_destination


def apply_writes(
    atlas_root: Path,
    writes: list[dict[str, Any]],
    *,
    plugin_name: str,
) -> list[str]:
    applied: list[str] = []
    resolved_root = atlas_root.resolve()
    for write in writes:
        destination = _normalize_write_path(atlas_root, str(write["path"]))
        content = str(write.get("content", ""))
        payload = {
            "plugin": plugin_name,
            "path": str(destination),
            "relative_path": str(destination.relative_to(resolved_root)),
        }
        run_hook(atlas_root, "pre-write", payload)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        run_hook(atlas_root, "post-write", payload)
        applied.append(str(destination))
    return applied


def run_plugin(
    atlas_root: Path,
    name: str,
    payload: dict[str, Any],
    *,
    apply_plugin_writes: bool = True,
) -> dict[str, Any]:
    plugin_path = resolve_plugin_path(atlas_root, name)
    env = os.environ.copy()
    env["CARTOGRAPHER_ROOT"] = str(atlas_root)
    env["PYTHONPATH"] = _pythonpath_env()
    result = subprocess.run(
        _plugin_command(plugin_path),
        input=json.dumps(payload, default=str),
        capture_output=True,
        text=True,
        cwd=atlas_root,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or f"plugin failed: {name}"
        raise RuntimeError(message)
    raw_output = result.stdout.strip()
    if not raw_output:
        plugin_result: dict[str, Any] = {"output": "", "writes": [], "errors": []}
    else:
        try:
            plugin_result = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"plugin returned invalid JSON: {name}") from exc
    writes = plugin_result.get("writes") or []
    if not isinstance(writes, list):
        raise RuntimeError(f"plugin writes payload must be a list: {name}")
    if apply_plugin_writes:
        plugin_result["applied_writes"] = apply_writes(
            atlas_root,
            writes,
            plugin_name=name,
        )
    else:
        plugin_result["applied_writes"] = []
    return plugin_result
