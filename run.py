import os
import socket
import subprocess
import threading
import time
import webbrowser

import requests
from werkzeug.serving import make_server

ENV = os.getenv("FLASK_ENV", "dev")
if ENV != "dev":
    raise SystemExit(
        "run.py is for local development only. Use gunicorn/systemd in production."
    )

from app import create_app

app = create_app(ENV)


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _open_browser_when_ready(url: str, delay_seconds: float) -> None:
    def _worker() -> None:
        time.sleep(max(delay_seconds, 0.0))
        try:
            webbrowser.open(url, new=1)
        except Exception:
            pass

    threading.Thread(target=_worker, daemon=True).start()


def _watch_local_browser_lifecycle(server, flask_app) -> None:
    lifecycle = flask_app.extensions.get("local_browser_lifecycle")
    if lifecycle is None:
        return

    startup_grace_seconds = float(
        os.getenv("LOCAL_BROWSER_STARTUP_GRACE_SECONDS", "180")
    )
    idle_poll_seconds = float(os.getenv("LOCAL_BROWSER_IDLE_POLL_SECONDS", "1.5"))
    launched_at = time.time()

    while True:
        time.sleep(max(idle_poll_seconds, 0.5))
        if lifecycle.has_active_clients():
            continue
        if lifecycle.ever_seen_client:
            server.shutdown()
            break
        if time.time() - launched_at >= startup_grace_seconds:
            break


def _wait_for_url(url: str, timeout_seconds: float, interval_seconds: float = 0.5) -> bool:
    deadline = time.time() + max(timeout_seconds, 0.5)
    while time.time() < deadline:
        try:
            response = requests.get(url, timeout=2.0)
            if response.ok:
                return True
        except requests.RequestException:
            pass
        time.sleep(max(interval_seconds, 0.1))
    return False


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def _start_local_mineru_if_needed():
    enable_local_mineru = _as_bool(os.getenv("AUTO_START_MINERU"), default=True)
    if not enable_local_mineru:
        return None, False

    mineru_host = os.getenv("MINERU_HOST", "127.0.0.1")
    mineru_port = int(os.getenv("MINERU_PORT", "8000"))
    mineru_cmd = os.getenv("MINERU_CMD", "mineru-api")
    mineru_health_url = f"http://{mineru_host}:{mineru_port}/health"

    if _wait_for_url(mineru_health_url, timeout_seconds=2.0, interval_seconds=0.4):
        print(f"MinerU already available at http://{mineru_host}:{mineru_port}/")
        return None, False

    if _port_in_use(mineru_host, mineru_port):
        raise RuntimeError(
            f"Port {mineru_port} is already in use, but MinerU health check failed."
        )

    env = os.environ.copy()
    env.setdefault("MINERU_PORT", str(mineru_port))

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    mineru_proc = subprocess.Popen(
        [mineru_cmd, "--host", mineru_host, "--port", str(mineru_port)],
        cwd=os.getcwd(),
        env=env,
        creationflags=creationflags,
    )

    if not _wait_for_url(mineru_health_url, timeout_seconds=45.0, interval_seconds=1.0):
        try:
            mineru_proc.terminate()
        except Exception:
            pass
        raise RuntimeError(
            f"MinerU failed to become healthy at http://{mineru_host}:{mineru_port}/health"
        )

    print(f"MinerU started at http://{mineru_host}:{mineru_port}/")
    return mineru_proc, True


def _stop_local_mineru(proc) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


if __name__ == "__main__":
    host = os.getenv("FLASK_RUN_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_RUN_PORT", "5000"))
    enable_browser_lifecycle = _as_bool(
        os.getenv("ENABLE_LOCAL_BROWSER_LIFECYCLE"),
        default=True,
    )
    auto_open_browser = _as_bool(
        os.getenv("AUTO_OPEN_BROWSER"),
        default=True,
    )

    app.config["ENABLE_LOCAL_BROWSER_LIFECYCLE"] = enable_browser_lifecycle
    app.config["LOCAL_BROWSER_SESSION_URL"] = (
        f"http://{host}:{port}/__local_dev__/browser-session"
        if enable_browser_lifecycle
        else ""
    )
    app.config["LOCAL_BROWSER_IDLE_TIMEOUT_SECONDS"] = float(
        os.getenv("LOCAL_BROWSER_IDLE_TIMEOUT_SECONDS", "8")
    )

    mineru_proc = None
    mineru_started_here = False
    try:
        mineru_proc, mineru_started_here = _start_local_mineru_if_needed()
    except Exception as exc:
        raise SystemExit(f"Failed to start local MinerU service: {exc}") from exc

    server = make_server(host, port, app, threaded=True)
    browser_url = f"http://{host}:{port}/"

    if auto_open_browser:
        _open_browser_when_ready(
            browser_url,
            float(os.getenv("AUTO_OPEN_BROWSER_DELAY_SECONDS", "1.2")),
        )

    if enable_browser_lifecycle:
        threading.Thread(
            target=_watch_local_browser_lifecycle,
            args=(server, app),
            daemon=True,
        ).start()

    print(f"Local server running at {browser_url}")
    if enable_browser_lifecycle:
        print("Browser-linked shutdown is enabled for this run.py session.")
    try:
        server.serve_forever()
    finally:
        if mineru_started_here:
            _stop_local_mineru(mineru_proc)
