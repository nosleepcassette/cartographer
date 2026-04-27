from __future__ import annotations

import http.client
import json
import os
import signal
import threading
import time
from pathlib import Path

from click.testing import CliRunner

from cartographer.atlas import Atlas
from cartographer.cli import main
from cartographer.graph_serve import (
    GraphState,
    build_graph_http_server,
    daemon_status,
    daemon_artifact_paths,
    regenerate_graph,
    spawn_graph_daemon,
    stop_graph_daemon,
    watch_atlas,
)


def _init_atlas(atlas_root: Path) -> None:
    previous_skip = os.environ.get("CARTOGRAPHER_SKIP_VIMWIKI_PATCH")
    os.environ["CARTOGRAPHER_SKIP_VIMWIKI_PATCH"] = "1"
    try:
        Atlas(root=atlas_root).init()
    finally:
        if previous_skip is None:
            os.environ.pop("CARTOGRAPHER_SKIP_VIMWIKI_PATCH", None)
        else:
            os.environ["CARTOGRAPHER_SKIP_VIMWIKI_PATCH"] = previous_skip


def _write_note(path: Path, *, note_id: str, title: str, note_type: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "---\n"
            f"id: {note_id}\n"
            f"title: {title}\n"
            f"type: {note_type}\n"
            "created: '2026-04-21'\n"
            "modified: '2026-04-21'\n"
            "---\n\n"
            f"{body}\n"
        ),
        encoding="utf-8",
    )


def test_graph_serve_command_defaults_to_html(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    _write_note(
        atlas_root / "projects" / "alpha.md",
        note_id="alpha",
        title="Alpha",
        note_type="project",
        body="# Alpha\n",
    )
    Atlas(root=atlas_root).refresh_index()

    captured: dict[str, object] = {}

    def fake_serve_graph(atlas_root_arg: Path, *, port: int, open_in_browser: bool, plugin_names: tuple[str, ...] = ()) -> None:
        captured["atlas_root"] = atlas_root_arg
        captured["port"] = port
        captured["open_in_browser"] = open_in_browser
        captured["plugin_names"] = plugin_names

    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))
    monkeypatch.setattr("cartographer.graph_serve.serve_graph", fake_serve_graph)

    runner = CliRunner()
    result = runner.invoke(main, ["graph", "--serve"])

    assert result.exit_code == 0
    assert captured == {
        "atlas_root": atlas_root,
        "port": 6969,
        "open_in_browser": False,
        "plugin_names": (),
    }


def test_graph_api_predicates_returns_active_profile_palette(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    _write_note(
        atlas_root / "projects" / "alpha.md",
        note_id="alpha",
        title="Alpha",
        note_type="project",
        body="# Alpha\n",
    )
    Atlas(root=atlas_root).refresh_index()

    state = GraphState()
    regenerate_graph(state, atlas_root)
    server = build_graph_http_server(atlas_root, state, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("localhost", server.server_port, timeout=2.0)
        connection.request("GET", "/api/predicates")
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)

    assert response.status == 200
    assert any(item["name"] == "relates_to" for item in payload)


def test_graph_api_trace_returns_activation_results(tmp_path) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    _write_note(
        atlas_root / "projects" / "alpha.md",
        note_id="alpha",
        title="Alpha",
        note_type="project",
        body='# Alpha\n\n<!-- cart:wire target="beta" predicate="supports" weight="0.9" -->\n',
    )
    _write_note(
        atlas_root / "projects" / "beta.md",
        note_id="beta",
        title="Beta",
        note_type="project",
        body="# Beta\n",
    )
    Atlas(root=atlas_root).refresh_index()

    state = GraphState()
    regenerate_graph(state, atlas_root)
    server = build_graph_http_server(atlas_root, state, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("localhost", server.server_port, timeout=2.0)
        connection.request("GET", "/api/trace?note=alpha&depth=2")
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)

    assert response.status == 200
    assert payload["note_id"] == "alpha"
    assert payload["results"][0]["note_id"] == "beta"


def test_graph_api_discover_returns_candidates(tmp_path) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    _write_note(
        atlas_root / "projects" / "alpha.md",
        note_id="alpha",
        title="Alpha",
        note_type="project",
        body="# Alpha\n\nbridge memory support\n",
    )
    _write_note(
        atlas_root / "projects" / "beta.md",
        note_id="beta",
        title="Beta",
        note_type="project",
        body="# Beta\n\nbridge memory support\n",
    )
    Atlas(root=atlas_root).refresh_index()

    state = GraphState()
    regenerate_graph(state, atlas_root)
    server = build_graph_http_server(atlas_root, state, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("localhost", server.server_port, timeout=2.0)
        connection.request("GET", "/api/discover?format=json&threshold=0.1")
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)

    assert response.status == 200
    assert payload["count"] >= 1
    assert any({item["left_id"], item["right_id"]} == {"alpha", "beta"} for item in payload["candidates"])


def test_graph_api_discover_accept_writes_wire(tmp_path) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    alpha_path = atlas_root / "projects" / "alpha.md"
    beta_path = atlas_root / "projects" / "beta.md"
    _write_note(
        alpha_path,
        note_id="alpha",
        title="Alpha",
        note_type="project",
        body="# Alpha\n\nbridge memory support\n",
    )
    _write_note(
        beta_path,
        note_id="beta",
        title="Beta",
        note_type="project",
        body="# Beta\n\nbridge memory support\n",
    )
    Atlas(root=atlas_root).refresh_index()

    state = GraphState()
    regenerate_graph(state, atlas_root)
    server = build_graph_http_server(atlas_root, state, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("localhost", server.server_port, timeout=2.0)
        connection.request(
            "POST",
            "/api/discover/accept",
            body=json.dumps(
                {
                    "left_id": "alpha",
                    "right_id": "beta",
                    "score": 0.8,
                    "reasons": {"keywords": ["bridge", "memory", "support"]},
                    "predicate": "supports",
                    "weight": 0.8,
                    "confidence": "medium",
                }
            ),
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)

    assert response.status == 200
    assert payload["accepted"] == 1
    content = alpha_path.read_text(encoding="utf-8")
    assert 'predicate="supports"' in content
    assert 'target="beta"' in content


def test_graph_api_wire_update_review_and_delete(tmp_path) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    alpha_path = atlas_root / "projects" / "alpha.md"
    _write_note(
        alpha_path,
        note_id="alpha",
        title="Alpha",
        note_type="project",
        body=(
            '# Alpha\n\n'
            '<!-- cart:wire target="beta" predicate="supports" weight="0.9" '
            'author="cart-discover" method="agent" reviewed="false" -->\n'
        ),
    )
    _write_note(
        atlas_root / "projects" / "beta.md",
        note_id="beta",
        title="Beta",
        note_type="project",
        body="# Beta\n",
    )
    Atlas(root=atlas_root).refresh_index()

    state = GraphState()
    regenerate_graph(state, atlas_root)
    server = build_graph_http_server(atlas_root, state, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("localhost", server.server_port, timeout=2.0)
        connection.request(
            "POST",
            "/api/wire/update",
            body=json.dumps(
                {
                    "path": str(alpha_path),
                    "source_note": "alpha",
                    "target_note": "beta",
                    "predicate": "supports",
                    "new_predicate": "contradicts",
                    "weight": 0.4,
                    "confidence": "high",
                    "note": "reviewed in graph",
                }
            ),
            headers={"Content-Type": "application/json"},
        )
        update_response = connection.getresponse()
        update_payload = json.loads(update_response.read().decode("utf-8"))
        updated_content = alpha_path.read_text(encoding="utf-8")

        connection.request(
            "POST",
            "/api/wire/review",
            body=json.dumps(
                {
                    "path": str(alpha_path),
                    "source_note": "alpha",
                    "target_note": "beta",
                    "predicate": "contradicts",
                    "confidence": "high",
                    "note": "reviewed in graph",
                }
            ),
            headers={"Content-Type": "application/json"},
        )
        review_response = connection.getresponse()
        review_payload = json.loads(review_response.read().decode("utf-8"))
        reviewed_content = alpha_path.read_text(encoding="utf-8")

        connection.request(
            "POST",
            "/api/wire/delete",
            body=json.dumps(
                {
                    "path": str(alpha_path),
                    "source_note": "alpha",
                    "target_note": "beta",
                    "predicate": "contradicts",
                }
            ),
            headers={"Content-Type": "application/json"},
        )
        delete_response = connection.getresponse()
        delete_payload = json.loads(delete_response.read().decode("utf-8"))
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)

    assert update_response.status == 200
    assert update_payload["updated"] is True
    assert 'predicate="contradicts"' in updated_content
    assert 'weight="0.4"' in updated_content
    assert 'confidence="high"' in updated_content

    assert review_response.status == 200
    assert review_payload["updated"] is True
    assert 'reviewed="true"' in reviewed_content
    assert 'method="confirmed"' in reviewed_content

    assert delete_response.status == 200
    assert delete_payload["deleted"] is True
    final_content = alpha_path.read_text(encoding="utf-8")
    assert "cart:wire" not in final_content


def test_graph_serve_rejects_json_format(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    _write_note(
        atlas_root / "projects" / "alpha.md",
        note_id="alpha",
        title="Alpha",
        note_type="project",
        body="# Alpha\n",
    )
    Atlas(root=atlas_root).refresh_index()

    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))
    runner = CliRunner()
    result = runner.invoke(main, ["graph", "--serve", "--format", "json"])

    assert result.exit_code != 0
    assert "--serve only works with --format html" in result.output


def test_graph_daemon_requires_serve(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    _write_note(
        atlas_root / "projects" / "alpha.md",
        note_id="alpha",
        title="Alpha",
        note_type="project",
        body="# Alpha\n",
    )
    Atlas(root=atlas_root).refresh_index()

    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))
    runner = CliRunner()
    result = runner.invoke(main, ["graph", "--daemon"])

    assert result.exit_code != 0
    assert "--daemon only works with --serve" in result.output


def test_graph_serve_daemon_dispatches_to_background_spawn(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    _write_note(
        atlas_root / "projects" / "alpha.md",
        note_id="alpha",
        title="Alpha",
        note_type="project",
        body="# Alpha\n",
    )
    Atlas(root=atlas_root).refresh_index()

    captured: dict[str, object] = {}

    def fake_spawn_graph_daemon(
        atlas_root_arg: Path,
        *,
        port: int,
        open_in_browser: bool,
        plugin_names: list[str] | None = None,
    ) -> dict[str, object]:
        captured["atlas_root"] = atlas_root_arg
        captured["port"] = port
        captured["open_in_browser"] = open_in_browser
        return {
            "pid": 4242,
            "url": "http://localhost:6969",
            "log_path": atlas_root_arg / ".cartographer" / "graph-serve-6969.log",
            "pid_path": atlas_root_arg / ".cartographer" / "graph-serve-6969.pid",
        }

    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))
    monkeypatch.setattr("cartographer.graph_serve.spawn_graph_daemon", fake_spawn_graph_daemon)

    runner = CliRunner()
    result = runner.invoke(main, ["graph", "--serve", "--daemon"])

    assert result.exit_code == 0
    assert captured == {
        "atlas_root": atlas_root,
        "port": 6969,
        "open_in_browser": False,
    }
    assert "graph daemon started: pid 4242 serving http://localhost:6969" in result.output


def test_graph_status_daemon_dispatches_and_reports_runtime_status(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))

    def fake_daemon_status(atlas_root_arg: Path, *, port: int) -> dict[str, object]:
        return {
            "running": True,
            "pid": 4242,
            "port": port,
            "url": f"http://localhost:{port}",
            "pid_path": atlas_root_arg / ".cartographer" / f"graph-serve-{port}.pid",
            "log_path": atlas_root_arg / ".cartographer" / f"graph-serve-{port}.log",
            "server_status": {
                "node_count": 12,
                "edge_count": 34,
                "last_regen": "2026-04-21T20:45:00-07:00",
            },
            "stale_pid": None,
        }

    monkeypatch.setattr("cartographer.graph_serve.daemon_status", fake_daemon_status)

    runner = CliRunner()
    result = runner.invoke(main, ["graph", "--status-daemon", "--port", "8080"])

    assert result.exit_code == 0
    assert "graph daemon running: pid 4242 at http://localhost:8080" in result.output
    assert (
        "graph status: 12 nodes, 34 edges, last regen 2026-04-21T20:45:00-07:00"
        in result.output
    )


def test_graph_stop_daemon_dispatches_to_stop_handler(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))

    def fake_stop_graph_daemon(atlas_root_arg: Path, *, port: int) -> dict[str, object]:
        return {
            "running": False,
            "stopped": True,
            "forced": False,
            "pid": 4242,
            "port": port,
            "url": f"http://localhost:{port}",
            "pid_path": atlas_root_arg / ".cartographer" / f"graph-serve-{port}.pid",
            "log_path": atlas_root_arg / ".cartographer" / f"graph-serve-{port}.log",
            "server_status": None,
            "stale_pid": None,
        }

    monkeypatch.setattr("cartographer.graph_serve.stop_graph_daemon", fake_stop_graph_daemon)

    runner = CliRunner()
    result = runner.invoke(main, ["graph", "--stop-daemon", "--port", "8080"])

    assert result.exit_code == 0
    assert "graph daemon stopped: pid 4242 on port 8080" in result.output


def test_spawn_graph_daemon_writes_pid_and_uses_detached_process(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)

    popen_calls: dict[str, object] = {}

    class FakeProcess:
        pid = 31337

    def fake_popen(command, **kwargs):
        popen_calls["command"] = command
        popen_calls["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    monkeypatch.setenv("CARTOGRAPHER_ROOT", str(atlas_root))

    result = spawn_graph_daemon(atlas_root, port=7777, open_in_browser=True)
    pid_path, log_path = daemon_artifact_paths(atlas_root, port=7777)

    assert result["pid"] == 31337
    assert result["pid_path"] == pid_path
    assert result["log_path"] == log_path
    assert pid_path.read_text(encoding="utf-8").strip() == "31337"

    command = popen_calls["command"]
    kwargs = popen_calls["kwargs"]
    assert command == [
        os.sys.executable,
        "-m",
        "cartographer.cli",
        "graph",
        "--serve",
        "--port",
        "7777",
        "--open",
    ]
    assert kwargs["env"]["CARTOGRAPHER_ROOT"] == str(atlas_root)
    assert kwargs["cwd"] == str(atlas_root)
    assert kwargs["stdin"] is not None
    assert kwargs["close_fds"] is True
    if os.name == "nt":
        assert "creationflags" in kwargs
    else:
        assert kwargs["start_new_session"] is True


def test_daemon_status_cleans_stale_pid_files(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    pid_path, _ = daemon_artifact_paths(atlas_root, port=6969)
    pid_path.write_text("99999\n", encoding="utf-8")

    monkeypatch.setattr("cartographer.graph_serve._pid_is_running", lambda pid: False)

    status = daemon_status(atlas_root, port=6969)

    assert status["running"] is False
    assert status["stale_pid"] == 99999
    assert not pid_path.exists()


def test_stop_graph_daemon_terminates_process_and_cleans_pid_file(tmp_path, monkeypatch) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    pid_path, _ = daemon_artifact_paths(atlas_root, port=6969)
    pid_path.write_text("4242\n", encoding="utf-8")

    kill_calls: list[tuple[int, int]] = []
    checks = iter([True, False, False, False])

    monkeypatch.setattr(
        "cartographer.graph_serve._server_status",
        lambda port, timeout=0.5: None,
    )
    monkeypatch.setattr(
        "cartographer.graph_serve._pid_is_running",
        lambda pid: next(checks),
    )
    monkeypatch.setattr(
        "cartographer.graph_serve.os.kill",
        lambda pid, sig: kill_calls.append((pid, sig)),
    )

    stopped = stop_graph_daemon(atlas_root, port=6969, timeout=0.2)

    assert stopped["stopped"] is True
    assert stopped["forced"] is False
    assert kill_calls == [(4242, signal.SIGTERM)]
    assert not pid_path.exists()


def test_graph_http_server_serves_status_reload_and_theme_scripts(tmp_path) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    theme_dir = atlas_root / "themes"
    theme_dir.mkdir(parents=True, exist_ok=True)
    (theme_dir / "synaptic-wizard.js").write_text(
        "window.CART_THEMES.register({ id: 'synaptic-wizard' });\n",
        encoding="utf-8",
    )
    config_dir = atlas_root / ".cartographer"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.toml").write_text(
        (
            "[graph]\n"
            'theme_preset = "synaptic-wizard"\n'
        ),
        encoding="utf-8",
    )
    _write_note(
        atlas_root / "entities" / "maps.md",
        note_id="maps",
        title="maps",
        note_type="entity",
        body="# maps\n",
    )
    Atlas(root=atlas_root).refresh_index()

    state = GraphState()
    regenerate_graph(state, atlas_root)
    server = build_graph_http_server(atlas_root, state, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        conn = http.client.HTTPConnection("localhost", server.server_port, timeout=5)
        conn.request("GET", "/status")
        response = conn.getresponse()
        status_payload = json.loads(response.read().decode("utf-8"))
        conn.close()

        assert response.status == 200
        initial_node_count = status_payload["node_count"]
        assert initial_node_count >= 1
        assert status_payload["edge_count"] >= 0
        assert status_payload["last_regen"]

        conn = http.client.HTTPConnection("localhost", server.server_port, timeout=5)
        conn.request("GET", "/themes/synaptic-wizard.js")
        theme_response = conn.getresponse()
        theme_body = theme_response.read().decode("utf-8")
        conn.close()

        assert theme_response.status == 200
        assert "synaptic-wizard" in theme_body

        _write_note(
            atlas_root / "projects" / "alpha.md",
            note_id="alpha",
            title="Alpha",
            note_type="project",
            body="# Alpha\n",
        )

        conn = http.client.HTTPConnection("localhost", server.server_port, timeout=5)
        conn.request("GET", "/reload")
        reload_response = conn.getresponse()
        reload_response.read()
        conn.close()

        assert reload_response.status == 302
        assert reload_response.getheader("Location") == "/"

        conn = http.client.HTTPConnection("localhost", server.server_port, timeout=5)
        conn.request("GET", "/status")
        refreshed = json.loads(conn.getresponse().read().decode("utf-8"))
        conn.close()

        assert refreshed["node_count"] == initial_node_count + 1

        conn = http.client.HTTPConnection("localhost", server.server_port, timeout=5)
        conn.request("GET", "/")
        html = conn.getresponse().read().decode("utf-8")
        conn.close()

        assert '<script src="./themes/synaptic-wizard.js"></script>' in html
        assert '"id": "alpha"' in html
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


def test_watch_atlas_regenerates_after_note_change(tmp_path) -> None:
    atlas_root = tmp_path / "atlas"
    _init_atlas(atlas_root)
    _write_note(
        atlas_root / "projects" / "alpha.md",
        note_id="alpha",
        title="Alpha",
        note_type="project",
        body="# Alpha\n",
    )
    Atlas(root=atlas_root).refresh_index()

    state = GraphState()
    regenerate_graph(state, atlas_root)
    initial_node_count = int(state.snapshot()["node_count"])
    stop_event = threading.Event()
    watcher = threading.Thread(
        target=watch_atlas,
        kwargs={
            "atlas_root": atlas_root,
            "state": state,
            "stop_event": stop_event,
            "poll_interval": 0.05,
            "debounce": 0.1,
        },
        daemon=True,
    )
    watcher.start()

    try:
        time.sleep(0.1)
        _write_note(
            atlas_root / "tasks" / "beta.md",
            note_id="beta",
            title="Beta",
            note_type="task",
            body="# Beta\n",
        )

        deadline = time.time() + 3.0
        while time.time() < deadline:
            if state.snapshot()["node_count"] == initial_node_count + 1:
                break
            time.sleep(0.05)

        snapshot = state.snapshot()
        assert snapshot["node_count"] == initial_node_count + 1
        assert snapshot["last_regen"]
    finally:
        stop_event.set()
        watcher.join(timeout=2.0)
