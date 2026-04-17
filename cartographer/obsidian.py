from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping


DEFAULT_VAULT_PATHS = [
    Path.home() / "vaults",
    Path.home() / "Documents" / "vaults",
    Path.home() / "Obsidian",
]

DEFAULT_APP_CONFIG = {
    "alwaysUpdateLinks": True,
    "attachmentFolderPath": "ref/assets",
    "newFileLocation": "current",
    "useMarkdownLinks": False,
}

DEFAULT_CORE_PLUGINS = [
    "file-explorer",
    "global-search",
    "switcher",
    "graph",
    "backlink",
    "outline",
    "command-palette",
    "page-preview",
    "templates",
    "daily-notes",
]

DEFAULT_DAILY_NOTES = {
    "folder": "daily",
    "format": "YYYY-MM-DD",
    "template": "",
    "autorun": False,
}

DEFAULT_WORKSPACE = {
    "main": {
        "id": "main",
        "type": "split",
        "children": [
            {
                "id": "tabs",
                "type": "tabs",
                "children": [
                    {
                        "id": "atlas-index",
                        "type": "leaf",
                        "state": {
                            "type": "markdown",
                            "state": {
                                "file": "index.md",
                                "mode": "source",
                                "source": False,
                            },
                        },
                    }
                ],
            }
        ],
    },
    "left": {"collapsed": False, "visible": True},
    "right": {"collapsed": False, "visible": False},
}


def detect_vault(config: Mapping[str, object] | None = None) -> Path | None:
    candidates: list[Path] = []
    configured = None
    if config:
        obsidian = config.get("obsidian", {})
        if isinstance(obsidian, Mapping):
            configured = obsidian.get("vault")
    if configured:
        candidates.append(Path(str(configured)).expanduser())
    candidates.extend(DEFAULT_VAULT_PATHS)

    seen: set[Path] = set()
    for candidate in candidates:
        candidate = candidate.expanduser()
        if candidate in seen:
            continue
        seen.add(candidate)
        if not candidate.exists():
            continue
        if (candidate / ".obsidian").exists():
            return candidate
        for child in candidate.iterdir():
            if child.is_dir() and (child / ".obsidian").exists():
                return child
    return None


def detect_external_vault(
    config: Mapping[str, object] | None = None,
    *,
    atlas_root: Path | None = None,
) -> Path | None:
    vault = detect_vault(config)
    if vault is None:
        return None
    if atlas_root is not None and vault.resolve() == atlas_root.expanduser().resolve():
        return None
    return vault


def _write_json_if_missing(path: Path, payload: object, written: list[Path]) -> None:
    if path.exists():
        return
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    written.append(path)


def bootstrap(atlas_root: Path) -> dict[str, object]:
    obsidian_dir = atlas_root / ".obsidian"
    obsidian_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    _write_json_if_missing(obsidian_dir / "app.json", DEFAULT_APP_CONFIG, written)
    _write_json_if_missing(obsidian_dir / "core-plugins.json", DEFAULT_CORE_PLUGINS, written)
    _write_json_if_missing(obsidian_dir / "daily-notes.json", DEFAULT_DAILY_NOTES, written)
    _write_json_if_missing(obsidian_dir / "workspace.json", DEFAULT_WORKSPACE, written)

    gitignore_path = obsidian_dir / ".gitignore"
    if not gitignore_path.exists():
        gitignore_path.write_text(
            "workspace-mobile.json\nhotkeys.json\nworkspace.json.bak\n",
            encoding="utf-8",
        )
        written.append(gitignore_path)

    return {
        "vault": atlas_root,
        "settings_dir": obsidian_dir,
        "written": written,
    }


def sync(atlas_root: Path, vault_path: Path) -> Path:
    bootstrap(vault_path)
    lines = [
        "---",
        "type: obsidian-index",
        f"atlas_root: {atlas_root}",
        "---",
        "",
        "# cartographer index",
        "",
    ]
    for note_path in sorted(atlas_root.rglob("*.md")):
        if ".cartographer" in note_path.parts:
            continue
        relative = note_path.relative_to(vault_path if note_path.is_relative_to(vault_path) else atlas_root)
        lines.append(f"- [[{relative.as_posix()}]]")
    destination = vault_path / "_cartographer_index.md"
    destination.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return destination
