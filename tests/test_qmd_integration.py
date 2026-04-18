from __future__ import annotations

from types import SimpleNamespace

import click
from click.testing import CliRunner

from cartographer import cli
from cartographer.integrations import qmd


def test_query_returns_empty_when_qmd_missing(monkeypatch):
    monkeypatch.setattr(qmd.shutil, "which", lambda _name: None)

    assert qmd.query("session drift") == []


def test_query_returns_empty_on_unsupported_mode(monkeypatch):
    monkeypatch.setattr(qmd.shutil, "which", lambda _name: "/usr/local/bin/qmd")

    assert qmd.query("session drift", mode="unsupported") == []


def test_query_parses_list_payload(monkeypatch):
    monkeypatch.setattr(qmd.shutil, "which", lambda _name: "/usr/local/bin/qmd")
    monkeypatch.setattr(
        qmd.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=(
                '[{"path":"docs/spec.md","docid":"abc123","score":0.81,'
                '"snippet":"matched text","collection":"cart"}]'
            ),
        ),
    )

    hits = qmd.query("auth middleware", collection="cart", mode="query")

    assert hits == [
        qmd.QmdHit(
            path="docs/spec.md",
            docid="abc123",
            score=0.81,
            snippet="matched text",
            collection="cart",
        )
    ]


def test_query_parses_enveloped_payload(monkeypatch):
    monkeypatch.setattr(qmd.shutil, "which", lambda _name: "/usr/local/bin/qmd")
    monkeypatch.setattr(
        qmd.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=(
                '{"results":[{"file":"notes/today.md","id":"doc-9","score":"0.5",'
                '"content":"x"*500}]}'
            ).replace('"x"*500', '"' + ("x" * 500) + '"'),
        ),
    )

    hits = qmd.query("today", mode="search")

    assert len(hits) == 1
    assert hits[0].path == "notes/today.md"
    assert hits[0].docid == "doc-9"
    assert hits[0].score == 0.5
    assert hits[0].snippet == "x" * 400


def test_query_returns_empty_on_nonzero_exit(monkeypatch):
    monkeypatch.setattr(qmd.shutil, "which", lambda _name: "/usr/local/bin/qmd")
    monkeypatch.setattr(
        qmd.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="[]"),
    )

    assert qmd.query("failure path") == []


def test_embed_incremental_is_noop_when_missing(monkeypatch):
    monkeypatch.setattr(qmd.shutil, "which", lambda _name: None)

    qmd.embed_incremental()


def test_embed_incremental_spawns_when_available(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(qmd.shutil, "which", lambda _name: "/usr/local/bin/qmd")
    monkeypatch.setattr(
        qmd.subprocess,
        "Popen",
        lambda command, **kwargs: calls.append(command),
    )

    qmd.embed_incremental()

    assert calls == [["qmd", "embed", "--incremental"]]


def test_resolve_query_paths_prefers_qmd_for_plain_text(monkeypatch, tmp_path):
    resolved_path = tmp_path / "notes" / "spec.md"
    resolved_path.parent.mkdir(parents=True)
    resolved_path.write_text("# spec\n", encoding="utf-8")
    atlas = SimpleNamespace(root=tmp_path, config={"qmd": {"enabled": "auto", "min_score": 0.42}})
    monkeypatch.setattr(cli.qmd, "is_available", lambda: True)
    monkeypatch.setattr(cli.qmd, "collection_name_for_path", lambda path: "atlas")
    monkeypatch.setattr(cli.qmd, "resolve_path", lambda raw_path, **kwargs: resolved_path)
    monkeypatch.setattr(
        cli.qmd,
        "query",
        lambda text, **kwargs: [
            qmd.QmdHit(
                path="qmd://atlas/notes/spec.md",
                docid="doc-1",
                score=0.9,
                snippet="matched text",
            )
        ],
    )
    monkeypatch.setattr(
        cli,
        "ensure_index_current",
        lambda atlas_obj: (_ for _ in ()).throw(AssertionError("legacy query should not run")),
    )

    assert cli.resolve_query_paths(atlas, "session drift") == [str(resolved_path)]


def test_resolve_query_paths_falls_back_when_no_matching_collection(monkeypatch, tmp_path):
    atlas = SimpleNamespace(root=tmp_path, config={"qmd": {"enabled": "auto"}})
    monkeypatch.setattr(cli.qmd, "is_available", lambda: True)
    monkeypatch.setattr(cli.qmd, "collection_name_for_path", lambda path: None)
    monkeypatch.setattr(
        cli.qmd,
        "query",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("qmd should be bypassed")),
    )
    monkeypatch.setattr(
        cli,
        "ensure_index_current",
        lambda atlas_obj: SimpleNamespace(query=lambda expression: ["legacy-result.md"]),
    )

    assert cli.resolve_query_paths(atlas, "session drift") == ["legacy-result.md"]


def test_resolve_query_paths_keeps_structured_queries_on_legacy_index(monkeypatch, tmp_path):
    atlas = SimpleNamespace(root=tmp_path, config={"qmd": {"enabled": "auto"}})
    monkeypatch.setattr(
        cli.qmd,
        "query",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("qmd should be bypassed")),
    )
    monkeypatch.setattr(
        cli,
        "ensure_index_current",
        lambda atlas_obj: SimpleNamespace(query=lambda expression: ["legacy-result.md"]),
    )

    assert cli.resolve_query_paths(atlas, 'type:note "session drift"') == ["legacy-result.md"]


def test_resolve_query_paths_raises_when_qmd_required_but_missing(monkeypatch, tmp_path):
    atlas = SimpleNamespace(root=tmp_path, config={"qmd": {"enabled": "on"}})
    monkeypatch.setattr(cli.qmd, "is_available", lambda: False)

    try:
        cli.resolve_query_paths(atlas, "session drift")
    except click.ClickException as exc:
        assert "qmd.enabled=on" in str(exc)
    else:
        raise AssertionError("expected ClickException when qmd is required but missing")


def test_resolve_query_paths_raises_when_qmd_required_but_collection_missing(monkeypatch, tmp_path):
    atlas = SimpleNamespace(root=tmp_path, config={"qmd": {"enabled": "on"}})
    monkeypatch.setattr(cli.qmd, "is_available", lambda: True)
    monkeypatch.setattr(cli.qmd, "collection_name_for_path", lambda path: None)

    try:
        cli.resolve_query_paths(atlas, "session drift")
    except click.ClickException as exc:
        assert "cart qmd bootstrap" in str(exc)
    else:
        raise AssertionError("expected ClickException when qmd collection is required but missing")


def test_qmd_bootstrap_prints_help_when_missing(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(cli, "get_atlas", lambda root=None: SimpleNamespace(root="unused", config={}))
    monkeypatch.setattr(cli.qmd, "is_available", lambda: False)

    result = runner.invoke(cli.main, ["qmd", "bootstrap"])

    assert result.exit_code == 0
    assert "qmd not installed" in result.output


def test_qmd_bootstrap_writes_collection_to_config(monkeypatch, tmp_path):
    runner = CliRunner()
    atlas_root = tmp_path / "atlas"
    atlas_root.mkdir(parents=True)
    atlas = SimpleNamespace(root=atlas_root, config={"qmd": {"enabled": "auto"}})
    monkeypatch.setattr(cli, "get_atlas", lambda root=None: atlas)
    monkeypatch.setattr(cli.qmd, "is_available", lambda: True)
    monkeypatch.setattr(cli.qmd, "ensure_collection", lambda root, preferred_name="atlas": ("atlas", True))
    monkeypatch.setattr(cli.qmd, "add_context", lambda target, description: True)
    monkeypatch.setattr(cli.qmd, "embed_full", lambda: True)

    result = runner.invoke(cli.main, ["qmd", "bootstrap"])

    assert result.exit_code == 0
    config_text = (atlas_root / ".cartographer" / "config.toml").read_text(encoding="utf-8")
    assert 'default_collection = "atlas"' in config_text
    assert "embed: complete" in result.output
