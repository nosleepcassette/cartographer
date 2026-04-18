from __future__ import annotations

from click.testing import CliRunner

from cartographer.cli import main


def test_completion_command_prints_zsh_script() -> None:
    runner = CliRunner()

    result = runner.invoke(main, ["completion", "zsh"])

    assert result.exit_code == 0
    assert "#compdef cart" in result.output
    assert "_CART_COMPLETE=zsh_complete" in result.output


def test_completion_command_respects_prog_name() -> None:
    runner = CliRunner()

    result = runner.invoke(main, ["completion", "bash", "--prog-name", "cartographer"])

    assert result.exit_code == 0
    assert "_CARTOGRAPHER_COMPLETE=bash_complete" in result.output
