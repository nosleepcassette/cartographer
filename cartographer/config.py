from __future__ import annotations

import copy
import os
import tomllib
from pathlib import Path
from typing import Any, Mapping


DEFAULT_CONFIG: dict[str, Any] = {
    "cartographer": {"version": 1, "root": "~/atlas"},
    "editor": {"command": ""},
    "index": {"auto_update": True, "full_text": True},
    "agents": {
        "hermes": {
            "path": "agents/hermes",
            "summary": "agents/hermes/SUMMARY.md",
        }
    },
    "ignore": {
        "dirs": [
            ".obsidian",
            ".git",
            "__pycache__",
            "node_modules",
            ".cartographer",
        ],
        "extensions": [".DS_Store"],
    },
    "vimwiki": {"sync": True},
    "obsidian": {
        "enabled": True,
        "vault": "~/vaults",
        "external_vault": "",
    },
    "sync": {"method": "git"},
    "daily": {"mode": "bidirectional"},
    "qmd": {
        "enabled": "auto",
        "default_collection": "",
        "min_score": 0.35,
        "incremental_on_save": True,
    },
    "mapsos": {
        "tasks_file": "tasks/mapsos.md",
        "snapshot_dir": "agents/mapsOS",
        "state_log": "agents/mapsOS/state-log.md",
        "intake_index": "agents/mapsOS/intake-index.md",
        "intake_dir": "~/dev/mapsOS/intakes",
        "export_dir": "~/.mapsOS/exports",
    },
    "graph": {
        "theme_preset": "antiquarian",
        "show_people": True,
        "always_visible_people": ["maps", "cassette"],
        "visible_people": [],
        "hidden_people": [],
        "privacy": {
            "mode": "off",
            "never_redact_ids": ["maps", "cassette"],
            "person_order": ["maps", "maggie", "sarah"],
        },
    },
}


def user_config_path() -> Path:
    return Path.home() / ".cartographer" / "config.toml"


def atlas_config_path(root: str | Path) -> Path:
    return Path(root).expanduser() / ".cartographer" / "config.toml"


def _deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
            continue
        base[key] = copy.deepcopy(value)
    return base


def _quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_format_value(item) for item in value) + "]"
    if value is None:
        return '""'
    return _quote(str(value))


def _iter_tables(data: Mapping[str, Any], prefix: tuple[str, ...] = ()):
    scalar_items: dict[str, Any] = {}
    nested_items: dict[str, Mapping[str, Any]] = {}
    for key, value in data.items():
        if isinstance(value, Mapping):
            nested_items[key] = value
        else:
            scalar_items[key] = value
    yield prefix, scalar_items
    for key, value in nested_items.items():
        yield from _iter_tables(value, prefix + (key,))


def dump_toml(data: Mapping[str, Any]) -> str:
    parts: list[str] = []
    first = True
    for prefix, items in _iter_tables(data):
        if not items and not prefix:
            continue
        if not first:
            parts.append("")
        first = False
        if prefix:
            parts.append(f"[{'.'.join(prefix)}]")
        for key, value in items.items():
            parts.append(f"{key} = {_format_value(value)}")
    return "\n".join(parts).rstrip() + "\n"


def load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    if not isinstance(data, dict):
        return {}
    return data


def default_config(root: str | Path | None = None) -> dict[str, Any]:
    config = copy.deepcopy(DEFAULT_CONFIG)
    env_root = os.environ.get("CARTOGRAPHER_ROOT")
    if env_root:
        config["cartographer"]["root"] = str(Path(env_root).expanduser())
    if root is not None:
        config["cartographer"]["root"] = str(Path(root).expanduser())
    return config


def load_config(root: str | Path | None = None) -> dict[str, Any]:
    config = default_config(root=root)
    paths = [user_config_path()]
    atlas_root = Path(root).expanduser() if root is not None else None
    if atlas_root is None:
        atlas_root = Path(config["cartographer"]["root"]).expanduser()
    paths.append(atlas_config_path(atlas_root))
    for path in paths:
        if path.exists():
            _deep_merge(config, load_toml(path))
    if root is not None:
        config["cartographer"]["root"] = str(Path(root).expanduser())
    return config


def save_config(
    config: Mapping[str, Any],
    *,
    root: str | Path | None = None,
    path: str | Path | None = None,
) -> Path:
    if path is not None:
        destination = Path(path).expanduser()
    elif root is not None:
        destination = atlas_config_path(root)
    else:
        destination = user_config_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(dump_toml(config), encoding="utf-8")
    return destination


def atlas_root(config: Mapping[str, Any]) -> Path:
    root = config.get("cartographer", {}).get("root", "~/atlas")
    return Path(str(root)).expanduser()
