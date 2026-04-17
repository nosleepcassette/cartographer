from __future__ import annotations

from pathlib import Path
from typing import Mapping


DEFAULT_VAULT_PATHS = [
    Path.home() / "vaults",
    Path.home() / "Documents" / "vaults",
    Path.home() / "Obsidian",
]


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


def sync(atlas_root: Path, vault_path: Path) -> Path:
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
