from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path


def backup_vimwiki_assets(stamp: str | None = None) -> list[Path]:
    timestamp = stamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    targets = [
        Path.home() / ".vimrc",
        Path.home() / ".vim",
        Path.home() / "vimwiki",
        Path.home() / "writing",
        Path.home() / "therapy",
    ]
    backups: list[Path] = []
    for source in targets:
        if not source.exists():
            continue
        destination = Path(f"{source}.bak.cart.{timestamp}")
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=False)
        else:
            shutil.copy2(source, destination)
        backups.append(destination)
    return backups


def patch_vimrc(vimrc_path: Path, atlas_root: Path) -> str:
    if not vimrc_path.exists():
        return "missing"
    content = vimrc_path.read_text(encoding="utf-8")
    if "wiki_atlas" in content or "cartographer — atlas wiki" in content:
        return "already patched"

    atlas_block = (
        '""" cartographer — atlas wiki (primary, added by cart init)\n'
        "let wiki_atlas = {}\n"
        f"let wiki_atlas.path = '{atlas_root.expanduser()}/'\n"
        "let wiki_atlas.ext = '.md'\n"
        "let wiki_atlas.syntax = 'markdown'\n"
        "let wiki_atlas.auto_tags = 1\n"
    )

    pattern = re.compile(r"(let\s+g:vimwiki_list\s*=\s*\[)")
    if pattern.search(content):
        updated = pattern.sub(atlas_block + r"\n\1wiki_atlas, ", content, count=1)
    else:
        updated = (
            content.rstrip()
            + "\n\n"
            + atlas_block
            + "\nlet g:vimwiki_list = [wiki_atlas]\n"
        )
    vimrc_path.write_text(updated, encoding="utf-8")
    return "patched"
