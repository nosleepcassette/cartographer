from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


VIM_TRANSIENT_DIR_NAMES = {
    ".cache",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "target",
}


@dataclass(slots=True)
class BackupSummary:
    backups: list[Path]
    warnings: list[str]


def _cleanup_partial_backup(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
        return
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def _format_backup_error(error: OSError | shutil.Error) -> str:
    if isinstance(error, shutil.Error):
        details = error.args[0] if error.args else []
        if isinstance(details, list) and details:
            first = details[0]
            first_message = first[2] if isinstance(first, tuple) and len(first) >= 3 else str(first)
            return f"{len(details)} copy errors (first: {first_message})"
    return str(error)


def _vim_backup_ignore(_directory: str, names: list[str]) -> set[str]:
    # Init-time safety backups should keep user config, not transient plugin build trees.
    return {name for name in names if name in VIM_TRANSIENT_DIR_NAMES}


def backup_vimwiki_assets(stamp: str | None = None) -> BackupSummary:
    timestamp = stamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    targets = [
        Path.home() / ".vimrc",
        Path.home() / ".vim",
        Path.home() / "vimwiki",
        Path.home() / "writing",
        Path.home() / "therapy",
    ]
    backups: list[Path] = []
    warnings: list[str] = []
    for source in targets:
        if not source.exists():
            continue
        destination = Path(f"{source}.bak.cart.{timestamp}")
        try:
            if source.is_dir():
                # Preserve symlinks so dangling plugin links do not abort init-time backups.
                shutil.copytree(
                    source,
                    destination,
                    dirs_exist_ok=False,
                    ignore=_vim_backup_ignore if source == Path.home() / ".vim" else None,
                    symlinks=True,
                    ignore_dangling_symlinks=True,
                )
            else:
                shutil.copy2(source, destination)
        except (OSError, shutil.Error) as error:
            _cleanup_partial_backup(destination)
            if source == Path.home() / ".vimrc":
                raise
            warnings.append(f"skipped backup for {source}: {_format_backup_error(error)}")
            continue
        backups.append(destination)
    return BackupSummary(backups=backups, warnings=warnings)


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
