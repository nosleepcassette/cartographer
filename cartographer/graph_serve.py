from __future__ import annotations

import http.client
import http.server
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import click

from .config import load_config
from .graph_export import load_graph_payload, render_graph_html
from .index import Index


EXTRA_IGNORED_TOP_LEVEL_DIRS = {"readings", "shared"}


@dataclass
class GraphState:
    """Mutable in-memory graph snapshot shared across threads."""

    html: str = ""
    node_count: int = 0
    edge_count: int = 0
    last_regen: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def update(self, html: str, *, node_count: int, edge_count: int) -> None:
        with self._lock:
            self.html = html
            self.node_count = node_count
            self.edge_count = edge_count
            self.last_regen = datetime.now().astimezone().replace(microsecond=0).isoformat()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "html": self.html,
                "node_count": self.node_count,
                "edge_count": self.edge_count,
                "last_regen": self.last_regen,
            }


def daemon_artifact_paths(atlas_root: Path | str, *, port: int) -> tuple[Path, Path]:
    atlas_root = Path(atlas_root).expanduser()
    meta_dir = atlas_root / ".cartographer"
    meta_dir.mkdir(parents=True, exist_ok=True)
    return (
        meta_dir / f"graph-serve-{port}.pid",
        meta_dir / f"graph-serve-{port}.log",
    )


def _read_pid_file(pid_path: Path) -> int | None:
    if not pid_path.exists():
        return None
    try:
        return int(pid_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _existing_daemon_pid(pid_path: Path) -> int | None:
    pid = _read_pid_file(pid_path)
    if pid is None:
        return None
    return pid if _pid_is_running(pid) else None


def _server_status(port: int, *, timeout: float = 0.5) -> dict[str, Any] | None:
    connection = http.client.HTTPConnection("localhost", port, timeout=timeout)
    try:
        connection.request("GET", "/status")
        response = connection.getresponse()
        if response.status != 200:
            return None
        payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    finally:
        connection.close()
    return payload if isinstance(payload, dict) else None


def _ignored_watch_settings(atlas_root: Path) -> tuple[set[str], set[str]]:
    config = load_config(root=atlas_root)
    ignore_config = config.get("ignore", {}) if isinstance(config, dict) else {}
    ignored_dirs = {
        str(value).strip()
        for value in ignore_config.get("dirs", [])
        if str(value).strip()
    }
    ignored_extensions = {
        str(value).strip()
        for value in ignore_config.get("extensions", [])
        if str(value).strip()
    }
    ignored_dirs.update(EXTRA_IGNORED_TOP_LEVEL_DIRS)
    return ignored_dirs, ignored_extensions


def _snapshot_watched_files(atlas_root: Path) -> dict[str, int]:
    ignored_dirs, ignored_extensions = _ignored_watch_settings(atlas_root)
    snapshot: dict[str, int] = {}
    if not atlas_root.exists():
        return snapshot

    for path in atlas_root.rglob("*.md"):
        try:
            relative = path.relative_to(atlas_root)
        except ValueError:
            continue
        if any(part in ignored_dirs for part in relative.parts):
            continue
        if path.suffix in ignored_extensions:
            continue
        try:
            snapshot[relative.as_posix()] = path.stat().st_mtime_ns
        except OSError:
            continue
    return snapshot


def regenerate_graph(
    state: GraphState,
    atlas_root: Path | str,
    *,
    force_rebuild: bool = False,
    announce_rebuild: bool = False,
) -> dict[str, Any]:
    """Refresh the graph payload and replace the in-memory HTML snapshot."""

    atlas_root = Path(atlas_root).expanduser()
    index = Index(atlas_root)
    needs_rebuild = force_rebuild or not index.db_path.exists() or index.needs_rebuild()
    if needs_rebuild:
        if announce_rebuild:
            click.echo("rebuilding index...", err=True)
        index.rebuild()

    payload = load_graph_payload(atlas_root)
    state.update(
        render_graph_html(payload),
        node_count=int(payload["node_count"]),
        edge_count=int(payload["edge_count"]),
    )
    return payload


def watch_atlas(
    atlas_root: Path | str,
    state: GraphState,
    *,
    stop_event: threading.Event | None = None,
    poll_interval: float = 2.0,
    debounce: float = 2.0,
) -> None:
    """Poll atlas markdown files and regenerate after a quiet debounce window."""

    atlas_root = Path(atlas_root).expanduser()
    stop_event = stop_event or threading.Event()
    previous_snapshot = _snapshot_watched_files(atlas_root)
    pending_since: float | None = None

    while not stop_event.is_set():
        current_snapshot = _snapshot_watched_files(atlas_root)
        now = time.monotonic()

        if current_snapshot != previous_snapshot:
            previous_snapshot = current_snapshot
            pending_since = now

        if pending_since is not None and now - pending_since >= debounce:
            try:
                regenerate_graph(state, atlas_root, force_rebuild=True)
            except Exception as exc:
                click.echo(f"graph regeneration failed: {exc}", err=True)
            pending_since = None

        stop_event.wait(poll_interval)


def _graph_handler_factory(
    atlas_root: Path,
    state: GraphState,
) -> type[http.server.BaseHTTPRequestHandler]:
    class GraphHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlsplit(self.path)
            path = parsed.path or "/"

            if path == "/":
                self._send_html()
                return
            if path == "/status":
                snapshot = state.snapshot()
                self._send_json(
                    {
                        "node_count": snapshot["node_count"],
                        "edge_count": snapshot["edge_count"],
                        "last_regen": snapshot["last_regen"],
                    }
                )
                return
            if path == "/reload":
                try:
                    regenerate_graph(state, atlas_root, force_rebuild=True)
                except Exception as exc:
                    self._send_json({"error": str(exc)}, status=500)
                    return
                self.send_response(302)
                self.send_header("Location", "/")
                self.end_headers()
                return
            if path.startswith("/themes/"):
                self._send_theme_script(path)
                return

            self.send_error(404)

        def _send_html(self) -> None:
            html = str(state.snapshot()["html"])
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))

        def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

        def _send_theme_script(self, request_path: str) -> None:
            requested = request_path.removeprefix("/themes/")
            script_name = Path(requested).name
            if not script_name or script_name != requested:
                self.send_error(404)
                return

            theme_path = atlas_root / "themes" / script_name
            if not theme_path.exists() or not theme_path.is_file():
                self.send_error(404)
                return

            try:
                content = theme_path.read_text(encoding="utf-8")
            except OSError:
                self.send_error(404)
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/javascript; charset=utf-8")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))

        def log_message(self, format: str, *args: object) -> None:
            return

    return GraphHandler


def build_graph_http_server(
    atlas_root: Path | str,
    state: GraphState,
    *,
    host: str = "localhost",
    port: int = 6969,
) -> http.server.ThreadingHTTPServer:
    atlas_root = Path(atlas_root).expanduser()
    return http.server.ThreadingHTTPServer(
        (host, port),
        _graph_handler_factory(atlas_root, state),
    )


def spawn_graph_daemon(
    atlas_root: Path | str,
    *,
    port: int = 6969,
    open_in_browser: bool = False,
) -> dict[str, Any]:
    atlas_root = Path(atlas_root).expanduser()
    pid_path, log_path = daemon_artifact_paths(atlas_root, port=port)
    existing_pid = _existing_daemon_pid(pid_path)
    if existing_pid is not None:
        raise click.ClickException(
            f"graph daemon already running on port {port} (pid {existing_pid})"
        )

    command = [
        sys.executable,
        "-m",
        "cartographer.cli",
        "graph",
        "--serve",
        "--port",
        str(port),
    ]
    if open_in_browser:
        command.append("--open")

    env = os.environ.copy()
    env["CARTOGRAPHER_ROOT"] = str(atlas_root)

    popen_kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": None,
        "stderr": None,
        "env": env,
        "cwd": str(atlas_root),
        "close_fds": True,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        )
    else:
        popen_kwargs["start_new_session"] = True

    with log_path.open("ab") as log_file:
        popen_kwargs["stdout"] = log_file
        popen_kwargs["stderr"] = log_file
        process = subprocess.Popen(command, **popen_kwargs)

    pid_path.write_text(f"{process.pid}\n", encoding="utf-8")
    return {
        "pid": process.pid,
        "pid_path": pid_path,
        "log_path": log_path,
        "url": f"http://localhost:{port}",
    }


def daemon_status(atlas_root: Path | str, *, port: int = 6969) -> dict[str, Any]:
    atlas_root = Path(atlas_root).expanduser()
    pid_path, log_path = daemon_artifact_paths(atlas_root, port=port)
    recorded_pid = _read_pid_file(pid_path)
    pid = _existing_daemon_pid(pid_path)
    stale = recorded_pid is not None and pid is None
    if stale:
        pid_path.unlink(missing_ok=True)
    return {
        "running": pid is not None,
        "pid": pid,
        "port": port,
        "url": f"http://localhost:{port}",
        "pid_path": pid_path,
        "log_path": log_path,
        "server_status": _server_status(port) if pid is not None else None,
        "stale_pid": recorded_pid if stale else None,
    }


def stop_graph_daemon(
    atlas_root: Path | str,
    *,
    port: int = 6969,
    timeout: float = 5.0,
) -> dict[str, Any]:
    atlas_root = Path(atlas_root).expanduser()
    status_payload = daemon_status(atlas_root, port=port)
    pid_path = Path(status_payload["pid_path"])
    pid = status_payload["pid"]
    if pid is None:
        return {
            **status_payload,
            "stopped": False,
            "forced": False,
        }

    forced = False
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pid_path.unlink(missing_ok=True)
        return {
            **status_payload,
            "running": False,
            "stopped": True,
            "forced": False,
        }

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_is_running(pid):
            break
        time.sleep(0.1)

    if _pid_is_running(pid) and os.name != "nt":
        forced = True
        os.kill(pid, signal.SIGKILL)
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if not _pid_is_running(pid):
                break
            time.sleep(0.05)

    if _pid_is_running(pid):
        raise click.ClickException(
            f"graph daemon on port {port} did not stop cleanly"
        )

    pid_path.unlink(missing_ok=True)
    return {
        **status_payload,
        "running": False,
        "stopped": True,
        "forced": forced,
    }


def serve_graph(
    atlas_root: Path | str,
    *,
    port: int = 6969,
    open_in_browser: bool = False,
) -> None:
    atlas_root = Path(atlas_root).expanduser()
    state = GraphState()
    regenerate_graph(
        state,
        atlas_root,
        force_rebuild=False,
        announce_rebuild=True,
    )

    stop_event = threading.Event()
    watcher = threading.Thread(
        target=watch_atlas,
        kwargs={
            "atlas_root": atlas_root,
            "state": state,
            "stop_event": stop_event,
        },
        daemon=True,
    )
    server = build_graph_http_server(atlas_root, state, port=port)
    url = f"http://localhost:{server.server_port}"

    click.echo(f"serving atlas graph at {url}")
    watcher.start()

    if open_in_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        click.echo("\nstopping graph server")
    finally:
        stop_event.set()
        server.server_close()
        watcher.join(timeout=2.0)
