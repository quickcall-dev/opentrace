# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""QuickCall OpenTrace CLI for managing the local daemon."""


import argparse
import json
import os
import platform
import signal
import subprocess
import sys
import time
import shutil
import urllib.error
import logging
import urllib.request
from pathlib import Path

from opentrace.daemon.config import DaemonConfig
from opentrace.daemon.main import Daemon

QUICKCALL_OPENTRACE_DIR = Path(os.environ.get("QUICKCALL_OPENTRACE_CONFIG_DIR", str(Path.home() / ".quickcall-opentrace")))
PID_FILE = QUICKCALL_OPENTRACE_DIR / "quickcall.pid"
LOG_FILE = QUICKCALL_OPENTRACE_DIR / "quickcall.log"


def _resolve_ingest_url() -> str:
    env_url = os.environ.get("QUICKCALL_OPENTRACE_INGEST_URL")
    if env_url:
        return env_url.rstrip("/ingest")
    config_path = QUICKCALL_OPENTRACE_DIR / "config.json"
    if config_path.exists():
        try:
            url = json.loads(config_path.read_text()).get("ingest_url")
            if url:
                return url.rstrip("/ingest")
        except (json.JSONDecodeError, OSError):
            pass
    return "http://localhost:19777"


INGEST_URL = _resolve_ingest_url()


def _read_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
    except (ValueError, OSError):
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        PID_FILE.unlink(missing_ok=True)
        return None
    except PermissionError:
        return pid
    return pid


def _write_pid(pid: int) -> None:
    QUICKCALL_OPENTRACE_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(pid))


def _is_service_active() -> str | None:
    system = platform.system()
    if system == "Darwin":
        domain = f"gui/{os.getuid()}"
        try:
            result = subprocess.run(["launchctl", "print", f"{domain}/com.quickcall.daemon"], capture_output=True, text=True)
            if result.returncode == 0:
                return "launchd (com.quickcall.daemon)"
        except FileNotFoundError:
            pass
    elif system == "Linux":
        try:
            result = subprocess.run(["systemctl", "--user", "is-active", "--quiet", "quickcall"], capture_output=True)
            if result.returncode == 0:
                return "systemd (opentrace.service)"
        except FileNotFoundError:
            pass
    return None


def _kill_all_opentrace_processes() -> int:
    killed = 0
    try:
        result = subprocess.run(["pgrep", "-f", "quickcall-daemon run"], capture_output=True, text=True)
    except FileNotFoundError:
        return killed
    if result.returncode != 0:
        return killed
    for line in result.stdout.strip().splitlines():
        try:
            pid = int(line.strip())
            if pid == os.getpid():
                continue
            os.kill(pid, signal.SIGTERM)
            killed += 1
        except (ValueError, ProcessLookupError, PermissionError):
            pass
    return killed


def _stop_service() -> bool:
    system = platform.system()
    if system == "Darwin":
        domain = f"gui/{os.getuid()}"
        cmd = ["launchctl", "bootout", f"{domain}/com.quickcall.daemon"]
    elif system == "Linux":
        cmd = ["systemctl", "--user", "stop", "quickcall"]
    else:
        return False
    try:
        return subprocess.run(cmd, capture_output=True).returncode == 0
    except FileNotFoundError:
        return False


def _rebootstrap_service() -> bool:
    return False


def _load_api_key() -> str | None:
    config_path = QUICKCALL_OPENTRACE_DIR / "config.json"
    if config_path.exists():
        try:
            return json.loads(config_path.read_text()).get("api_key")
        except (json.JSONDecodeError, OSError):
            pass
    return os.environ.get("QUICKCALL_OPENTRACE_API_KEY")


def _http_get(path: str, timeout: float = 3.0) -> dict | None:
    try:
        req = urllib.request.Request(f"{INGEST_URL}{path}")
        api_key = _load_api_key()
        if api_key:
            req.add_header("X-API-Key", api_key)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
        return None


def cmd_run(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO)
    Daemon(DaemonConfig()).run()
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    service = _is_service_active()
    if service:
        print(f"Daemon is managed by {service} - use 'quickcall stop' first to disable it")
        return 1
    existing_pid = _read_pid()
    if existing_pid is not None:
        print(f"Daemon already running (PID {existing_pid})")
        return 0
    if _rebootstrap_service():
        return 0
    QUICKCALL_OPENTRACE_DIR.mkdir(parents=True, exist_ok=True)
    log_file = open(LOG_FILE, "a")
    proc = subprocess.Popen([sys.executable, "-m", "opentrace.daemon"], stdout=log_file, stderr=subprocess.STDOUT, start_new_session=True)
    _write_pid(proc.pid)
    print(f"Daemon started (PID {proc.pid})")
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    service = _is_service_active()
    if service and _stop_service():
        _kill_all_opentrace_processes()
        print("Service stopped")
        return 0
    pid = _read_pid()
    if pid is None:
        _kill_all_opentrace_processes()
        print("Daemon not running")
        return 1
    try:
        os.kill(pid, signal.SIGTERM)
        deadline = time.time() + 2
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
                time.sleep(0.05)
            except ProcessLookupError:
                break
    finally:
        PID_FILE.unlink(missing_ok=True)
    _kill_all_opentrace_processes()
    print("Daemon stopped")
    return 0


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def cmd_status(args: argparse.Namespace) -> int:
    pid = _read_pid()
    if pid is None:
        print("Daemon not running")
        return 0
    print(f"Daemon running (PID {pid})")
    print("Server: \u2717 unreachable" if _http_get("/health") is None else "Server: ok")
    push_status = _load_json(QUICKCALL_OPENTRACE_DIR / "push_status.json")
    queue_size = push_status.get("queue_size", 0)
    backoff = push_status.get("current_backoff", 0)
    if queue_size:
        print(f"{queue_size} messages queued for retry")
    if backoff:
        print(f"backoff: {backoff}s")
    files = _load_json(QUICKCALL_OPENTRACE_DIR / "state.json").get("files", {})
    if files:
        labels = {"claude_code": "Claude Code", "codex_cli": "Codex CLI", "gemini_cli": "Gemini CLI", "cursor": "Cursor", "cursor_vscdb": "Cursor"}
        by_source: dict[str, dict[str, int]] = {}
        for item in files.values():
            source = item.get("source", "unknown")
            row = by_source.setdefault(source, {"files": 0, "lines": 0})
            row["files"] += 1
            row["lines"] += int(item.get("last_line_processed") or 0)
        total_files = total_lines = 0
        for source, row in sorted(by_source.items()):
            total_files += row["files"]
            total_lines += row["lines"]
            print(f"{labels.get(source, source)}: {row['files']} files, {row['lines']} lines processed")
        print(f"{total_files} files, {total_lines} lines processed")
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    if not LOG_FILE.exists():
        print(f"Log file not found: {LOG_FILE}")
        return 1
    for line in LOG_FILE.read_text(errors="replace").splitlines()[-args.lines:]:
        print(line)
    return 0


def _find_compose_file() -> Path | None:
    """Look for docker-compose.yml in cwd or parent dirs."""
    cwd = Path.cwd()
    for path in [cwd, *cwd.parents]:
        compose = path / "docker-compose.yml"
        if compose.exists():
            return compose
    return None


SESSION_DIR_CANDIDATES = [
    Path.home() / ".claude" / "projects",
    Path.home() / ".codex" / "sessions",
    Path.home() / ".gemini",
    Path.home() / ".cursor" / "projects",
    Path.home() / ".pi" / "agent" / "sessions",
]


def _find_session_dirs() -> list[Path]:
    """Return existing session directories on this machine."""
    return [p for p in SESSION_DIR_CANDIDATES if p.exists()]


def _test_dsn(dsn: str) -> bool:
    """Test if a Postgres DSN is reachable."""
    try:
        import psycopg
        with psycopg.connect(dsn, connect_timeout=3):
            return True
    except Exception:
        return False


def cmd_up(args: argparse.Namespace) -> int:
    """Run docker compose up -d for the full stack."""
    if not shutil.which("docker"):
        print("Docker not found. Install Docker: https://docs.docker.com/get-docker/")
        return 1

    compose = _find_compose_file()
    if compose is None:
        print("No docker-compose.yml found.")
        print("Clone the repo and run from the repo root:")
        print("  git clone https://github.com/quickcall-dev/opentrace.git")
        print("  cd opentrace")
        print("  quickcall up")
        return 1

    result = subprocess.run(
        ["docker", "compose", "up", "-d"],
        cwd=str(compose.parent),
    )
    if result.returncode == 0:
        print("QuickCall OpenTrace is up: http://localhost:3000")
    return result.returncode


def cmd_down(args: argparse.Namespace) -> int:
    """Run docker compose down."""
    compose = _find_compose_file()
    if compose is None:
        print("No docker-compose.yml found.")
        return 1
    result = subprocess.run(
        ["docker", "compose", "down"],
        cwd=str(compose.parent),
    )
    return result.returncode


def cmd_doctor(args: argparse.Namespace) -> int:
    """Check system readiness and print actionable report."""
    ok = "\u2713"
    fail = "\u2717"

    # Config dir
    config_exists = QUICKCALL_OPENTRACE_DIR.exists()
    print(f"{ok if config_exists else fail} Config dir: {QUICKCALL_OPENTRACE_DIR}")

    # Docker
    docker_path = shutil.which("docker")
    print(f"{ok if docker_path else fail} Docker: {docker_path or 'not found'}")

    # Compose file
    compose = _find_compose_file()
    print(f"{ok if compose else fail} docker-compose.yml: {compose or 'not found (needed for quickcall up)'}")

    # Postgres / Server
    health = _http_get("/health")
    print(f"{ok if health else fail} Server: {'ok' if health else 'unreachable on ' + INGEST_URL}")

    # Daemon
    pid = _read_pid()
    print(f"{ok if pid else fail} Daemon: {'running (PID ' + str(pid) + ')' if pid else 'not running'}")

    # Session dirs
    session_dirs = _find_session_dirs()
    if session_dirs:
        print(f"{ok} Session dirs found: {len(session_dirs)}")
        for d in session_dirs:
            print(f"    {d}")
    else:
        print(f"{fail} Session dirs: none found (install a CLI first)")

    print()
    if not compose:
        print("Next steps:")
        print("  git clone https://github.com/quickcall-dev/opentrace.git")
        print("  cd opentrace")
        print("  quickcall up")
    elif not health:
        print("Next steps:")
        print("  quickcall up          # start the full stack")
        print("  quickcall-server      # or start just the server")
    elif not pid:
        print("Next steps:")
        print("  quickcall start       # start the daemon")
    else:
        print("All checks passed. Open http://localhost:3000")

    return 0


def cmd_init(args: argparse.Namespace) -> int:
    """Create config dir and write config.json with user input."""
    config_path = QUICKCALL_OPENTRACE_DIR / "config.json"

    if config_path.exists():
        print(f"Config already exists: {config_path}")
        print("Edit it directly or delete it and run 'quickcall init' again.")
        return 0

    QUICKCALL_OPENTRACE_DIR.mkdir(parents=True, exist_ok=True)

    # Prompt user (read from stdin if piped, or use env defaults)
    def _ask(prompt: str, default: str) -> str:
        if sys.stdin.isatty():
            val = input(f"{prompt} [{default}]: ").strip()
        else:
            # Non-tty: try reading one line from stdin, fallback to default
            try:
                val = sys.stdin.readline().strip()
            except Exception:
                val = ""
        return val if val else default

    dsn = _ask("PostgreSQL DSN", "postgresql://quickcall:quickcall@localhost:5432/quickcall")
    api_key = _ask("API key for daemon pushes", "push_dev")
    admin_keys = _ask("Admin API keys", "admin_dev")

    config = {
        "dsn": dsn,
        "api_key": api_key,
        "admin_keys": admin_keys,
        "ingest_url": "http://localhost:19777/ingest",
    }

    config_path.write_text(json.dumps(config, indent=2))
    print(f"Config written: {config_path}")

    # Test DSN
    print("Testing Postgres connection...")
    if _test_dsn(dsn):
        print("  \u2713 Connected")
    else:
        print(f"  \u2717 Could not connect to {dsn}")
        print("  Make sure Postgres is running, then edit the DSN in config.json.")

    print()
    print("Next steps:")
    print("  quickcall doctor    # verify setup")
    print("  quickcall up        # start full stack (needs repo clone + docker)")
    print("  quickcall-server    # start server only")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quickcall")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run")
    sub.add_parser("start")
    sub.add_parser("stop")
    sub.add_parser("status")
    sub.add_parser("up")
    sub.add_parser("down")
    sub.add_parser("doctor")
    sub.add_parser("init")
    logs = sub.add_parser("logs")
    logs.add_argument("-f", "--follow", action="store_true")
    logs.add_argument("-n", "--lines", type=int, default=50)
    return parser


COMMAND_MAP = {
    "run": cmd_run, "start": cmd_start, "stop": cmd_stop,
    "status": cmd_status, "logs": cmd_logs, "up": cmd_up,
    "down": cmd_down, "doctor": cmd_doctor, "init": cmd_init,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 1
    return COMMAND_MAP[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
