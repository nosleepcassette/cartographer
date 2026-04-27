from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

from ..hooks import run_hook

try:
    import lupa

    LUPA_AVAILABLE = True
except ImportError:
    LUPA_AVAILABLE = False


BUILTIN_PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent / "plugins"
PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent
MANIFEST_NAME = "manifest.json"


def atlas_plugin_dir(atlas_root: Path) -> Path:
    return atlas_root / ".cartographer" / "plugins"


def sync_builtin_plugins(atlas_root: Path) -> list[Path]:
    target_dir = atlas_plugin_dir(atlas_root)
    target_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    sources = sorted(BUILTIN_PLUGIN_DIR.glob("*.py")) + sorted(
        BUILTIN_PLUGIN_DIR.glob("*.json")
    )
    for source in sources:
        target = target_dir / source.name
        should_copy = not target.exists() or source.read_text(
            encoding="utf-8"
        ) != target.read_text(encoding="utf-8")
        if should_copy:
            shutil.copy2(source, target)
            if source.suffix == ".py":
                target.chmod(target.stat().st_mode | stat.S_IXUSR)
            written.append(target)
    return written


def _plugin_manifest_entries(atlas_root: Path) -> dict[str, dict[str, Any]]:
    manifest_path = atlas_plugin_dir(atlas_root) / MANIFEST_NAME
    if not manifest_path.exists():
        return {}
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    plugins = raw.get("plugins", {})
    if not isinstance(plugins, dict):
        return {}
    return {
        str(name): entry
        for name, entry in plugins.items()
        if isinstance(entry, dict)
    }


def list_plugins(atlas_root: Path) -> list[str]:
    sync_builtin_plugins(atlas_root)
    plugins: set[str] = set()
    plugins.update(_plugin_manifest_entries(atlas_root).keys())
    for path in atlas_plugin_dir(atlas_root).iterdir():
        if not path.is_file() or path.name.startswith(".") or path.name.startswith("_"):
            continue
        if path.name == MANIFEST_NAME or path.suffix == ".json":
            continue
        plugins.add(path.stem if path.suffix else path.name)
    return sorted(plugins)


def resolve_plugin_path(atlas_root: Path, name: str) -> Path:
    sync_builtin_plugins(atlas_root)
    manifest_entry = _plugin_manifest_entries(atlas_root).get(name, {})
    executable = str(manifest_entry.get("executable") or "").strip()
    if executable:
        manifest_candidate = atlas_plugin_dir(atlas_root) / executable
        if manifest_candidate.exists() and manifest_candidate.is_file():
            return manifest_candidate
    candidates = [
        atlas_plugin_dir(atlas_root) / name,
        atlas_plugin_dir(atlas_root) / f"{name}.py",
        atlas_plugin_dir(atlas_root) / f"{name}.lua",
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
    if (
        resolved_destination != resolved_root
        and resolved_root not in resolved_destination.parents
    ):
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
    if plugin_path.suffix == ".lua":
        return _run_lua_plugin(atlas_root, plugin_path, payload, apply_plugin_writes)
    return _run_python_plugin(atlas_root, plugin_path, payload, apply_plugin_writes)


def _run_python_plugin(
    atlas_root: Path,
    plugin_path: Path,
    payload: dict[str, Any],
    apply_plugin_writes: bool,
) -> dict[str, Any]:
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
        message = (
            result.stderr.strip()
            or result.stdout.strip()
            or f"plugin failed: {plugin_path.stem}"
        )
        raise RuntimeError(message)
    raw_output = result.stdout.strip()
    if not raw_output:
        plugin_result: dict[str, Any] = {"output": "", "writes": [], "errors": []}
    else:
        try:
            plugin_result = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"plugin returned invalid JSON: {plugin_path.stem}"
            ) from exc
    writes = plugin_result.get("writes") or []
    if not isinstance(writes, list):
        raise RuntimeError(f"plugin writes payload must be a list: {plugin_path.stem}")
    if apply_plugin_writes:
        plugin_result["applied_writes"] = apply_writes(
            atlas_root,
            writes,
            plugin_name=plugin_path.stem,
        )
    else:
        plugin_result["applied_writes"] = []
    return plugin_result


def _run_lua_plugin(
    atlas_root: Path,
    plugin_path: Path,
    payload: dict[str, Any],
    apply_plugin_writes: bool,
) -> dict[str, Any]:
    if not LUPA_AVAILABLE:
        raise RuntimeError("lupa not installed: pip install lupa")
    from lupa import LuaRuntime

    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().cartographer = _LuaCartographerBridge(atlas_root)
    lua_code = plugin_path.read_text(encoding="utf-8")
    lua_func = lua.eval(f"function(main) return main(...) end")
    lua_payload = _dict_to_lua_table(lua, payload)
    try:
        lua_result = lua_func(lua_payload)
    except Exception as exc:
        raise RuntimeError(f"lua plugin error: {exc}") from exc
    if lua_result is None:
        lua_result = {}
    plugin_result = _lua_table_to_dict(lua_result)
    if not isinstance(plugin_result, dict):
        raise RuntimeError(f"lua plugin must return a table, got {type(plugin_result)}")
    writes = plugin_result.get("writes") or []
    if not isinstance(writes, list):
        raise RuntimeError(f"plugin writes payload must be a list: {plugin_path.stem}")
    if apply_plugin_writes:
        plugin_result["applied_writes"] = apply_writes(
            atlas_root,
            writes,
            plugin_name=plugin_path.stem,
        )
    else:
        plugin_result["applied_writes"] = []
    return plugin_result


class _LuaCartographerBridge:
    def __init__(self, atlas_root: Path):
        self.atlas_root = atlas_root

    def query(self, expression: str) -> list[str]:
        from .index import Index

        index = Index(self.atlas_root)
        return index.query(expression)

    def read_note(self, note_id: str) -> dict[str, Any] | None:
        from .index import Index
        from .notes import Note

        index = Index(self.atlas_root)
        note_path = index.find_note_path(note_id)
        if note_path is None or not note_path.exists():
            return None
        note = Note.from_file(note_path)
        return {
            "id": note_id,
            "path": str(note.path),
            "frontmatter": note.frontmatter,
            "body": note.body,
        }

    def write_note(
        self, note_id: str, content: str, frontmatter: dict[str, Any] | None = None
    ) -> str:
        from .index import Index
        from .notes import Note, render

        index = Index(self.atlas_root)
        note_path = index.find_note_path(note_id)
        if note_path is None:
            raise RuntimeError(f"note not found: {note_id}")
        note = Note.from_file(note_path)
        if frontmatter:
            note.frontmatter.update(frontmatter)
        note.body = content
        note.write()
        return str(note.path)


def _dict_to_lua_table(lua: "lupa.LuaRuntime", data: Any) -> Any:
    if isinstance(data, dict):
        table = lua.table()
        for key, value in data.items():
            table[key] = _dict_to_lua_table(lua, value)
        return table
    if isinstance(data, list):
        table = lua.table()
        for i, item in enumerate(data, start=1):
            table[i] = _dict_to_lua_table(lua, item)
        return table
    return data


def _lua_table_to_dict(table: Any) -> Any:
    if hasattr(table, "items"):
        result = {}
        for key, value in table.items():
            result[key] = _lua_table_to_dict(value)
        return result
    if hasattr(table, "__iter__") and not isinstance(table, (str, bytes)):
        try:
            return [_lua_table_to_dict(item) for item in table]
        except Exception:
            pass
    return table
