from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cartographer.vimwiki import backup_vimwiki_assets


class BackupVimwikiAssetsTests(unittest.TestCase):
    def test_backup_preserves_dangling_symlinks_in_vim_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            home = Path(tempdir)
            plugin_dir = home / ".vim" / "bundle" / "python-mode" / "pymode" / "libs"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "pytoolconfig").symlink_to("missing-target")

            with mock.patch("cartographer.vimwiki.Path.home", return_value=home):
                summary = backup_vimwiki_assets(stamp="20260416_212508")

            vim_backup = home / ".vim.bak.cart.20260416_212508"
            copied_link = vim_backup / "bundle" / "python-mode" / "pymode" / "libs" / "pytoolconfig"

            self.assertIn(vim_backup, summary.backups)
            self.assertTrue(copied_link.is_symlink())
            self.assertEqual(os.readlink(copied_link), "missing-target")
            self.assertEqual(summary.warnings, [])

    def test_backup_ignores_transient_vim_build_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            home = Path(tempdir)
            vim_dir = home / ".vim"
            keep_file = vim_dir / "after" / "ftplugin" / "markdown.vim"
            ignored_file = vim_dir / "plugged" / "vim-clap" / "target" / "release" / "app.bin"
            keep_file.parent.mkdir(parents=True)
            ignored_file.parent.mkdir(parents=True)
            keep_file.write_text("setlocal wrap\n", encoding="utf-8")
            ignored_file.write_text("compiled\n", encoding="utf-8")

            with mock.patch("cartographer.vimwiki.Path.home", return_value=home):
                summary = backup_vimwiki_assets(stamp="20260416_214500")

            vim_backup = home / ".vim.bak.cart.20260416_214500"

            self.assertIn(vim_backup, summary.backups)
            self.assertTrue((vim_backup / "after" / "ftplugin" / "markdown.vim").exists())
            self.assertFalse((vim_backup / "plugged" / "vim-clap" / "target").exists())
            self.assertEqual(summary.warnings, [])

    def test_backup_skips_large_directory_failures_without_aborting(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            home = Path(tempdir)
            vimrc = home / ".vimrc"
            vimrc.write_text("set nocompatible\n", encoding="utf-8")
            vim_dir = home / ".vim"
            vim_dir.mkdir()

            real_copytree = shutil.copytree

            def flaky_copytree(src: Path, dst: Path, **kwargs: object):
                if Path(src) == vim_dir:
                    Path(dst).mkdir(parents=True, exist_ok=True)
                    raise OSError(28, "No space left on device")
                return real_copytree(src, dst, **kwargs)

            with (
                mock.patch("cartographer.vimwiki.Path.home", return_value=home),
                mock.patch("cartographer.vimwiki.shutil.copytree", side_effect=flaky_copytree),
            ):
                summary = backup_vimwiki_assets(stamp="20260416_213617")

            vimrc_backup = home / ".vimrc.bak.cart.20260416_213617"
            partial_vim_backup = home / ".vim.bak.cart.20260416_213617"

            self.assertIn(vimrc_backup, summary.backups)
            self.assertFalse(partial_vim_backup.exists())
            self.assertEqual(len(summary.warnings), 1)
            self.assertIn("No space left on device", summary.warnings[0])


if __name__ == "__main__":
    unittest.main()
