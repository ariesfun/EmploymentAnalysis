#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dashboard one-click start/stop manager (Windows-friendly, no bat syntax quirks).

Usage (from scripts/ or anywhere via absolute path):
    python scripts/dashboard_manager.py start      # start (warn if already running)
    python scripts/dashboard_manager.py stop       # stop
    python scripts/dashboard_manager.py restart    # restart
    python scripts/dashboard_manager.py status     # show state + access URL

Defaults (overridable via env vars):
    JOBMVP_DSN        default postgresql://mvp:mvp@127.0.0.1:5432/jobmvp
    JOBMVP_API_KEY    default devkey
    DASHBOARD_HOST    default 127.0.0.1
    DASHBOARD_PORT    default 8010

Notes:
    - Uses DETACHED process so the dashboard survives parent/terminal closing.
    - PID written to .dashboard.pid, logs to logs/dashboard.log.
    - stop prefers pid file, falls back to port 8010.
    - Pre-flight PG check warns but does not block startup.
"""

import argparse
import os
import subprocess
import sys
import time

DEFAULT_DSN = "postgresql://mvp:mvp@127.0.0.1:5432/jobmvp"
DEFAULT_KEY = "devkey"
HOST = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
PORT = int(os.environ.get("DASHBOARD_PORT", "8010"))
DSN = os.environ.get("JOBMVP_DSN", DEFAULT_DSN)
KEY = os.environ.get("JOBMVP_API_KEY", DEFAULT_KEY)

# project root: this file is in scripts/, go up one level
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PID_FILE = os.path.join(ROOT, ".dashboard.pid")
LOG_FILE = os.path.join(ROOT, "logs", "dashboard.log")


def _log(msg):
    print(msg, flush=True)


def _read_pid():
    if not os.path.exists(PID_FILE):
        return None
    try:
        with open(PID_FILE, "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except Exception:
        return None


def _pid_alive(pid):
    if not pid:
        return False
    try:
        if os.name == "nt":
            raw = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
            ).stdout
            out = raw.decode("gbk", errors="ignore")
            return str(pid) in out
        else:
            os.kill(pid, 0)
            return True
    except Exception:
        return False


def _pids_on_port():
    pids = []
    if os.name != "nt":
        return pids
    try:
        raw = subprocess.run(
            ["netstat", "-ano"], capture_output=True,
        ).stdout
        out = raw.decode("gbk", errors="ignore")
        for line in out.splitlines():
            if f":{PORT}" in line and "LISTENING" in line:
                parts = line.split()
                pids.append(int(parts[-1]))
    except Exception:
        pass
    return sorted(set(pids))


def _check_pg():
    try:
        import psycopg
        with psycopg.connect(DSN, connect_timeout=3):
            return True
    except Exception as e:  # noqa: BLE001
        _log(f"  [WARN] DB connection failed, dashboard APIs will error: {e}")
        return False


def start():
    pid = _read_pid()
    if _pid_alive(pid):
        _log(f"Dashboard already running (PID {pid}). http://{HOST}:{PORT}/ui?key={KEY}")
        return 0
    port_pids = _pids_on_port()
    if port_pids:
        _log(f"Port {PORT} occupied by PID {port_pids}. Run stop first.")
        return 1

    _check_pg()

    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    env = os.environ.copy()
    env["JOBMVP_DSN"] = DSN
    env["JOBMVP_API_KEY"] = KEY

    python_exe = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
    if not os.path.exists(python_exe):
        python_exe = sys.executable

    # --no-use-colors: avoid ANSI escape codes when the log is a real console
    cmd = [
        python_exe, "-m", "uvicorn", "console.app:app",
        "--host", HOST, "--port", str(PORT), "--no-use-colors",
    ]

    log_f = open(LOG_FILE, "a", encoding="utf-8")
    creationflags = 0
    if os.name == "nt":
        creationflags = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )

    _log(f"Starting: {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd,
        cwd=ROOT,
        env=env,
        stdout=log_f,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
        close_fds=True,
    )

    with open(PID_FILE, "w", encoding="utf-8") as f:
        f.write(str(proc.pid))
    _log(f"Launched (PID {proc.pid}), logs: logs/dashboard.log")

    for _ in range(10):
        time.sleep(1)
        if _pids_on_port():
            _log(f"Started. http://{HOST}:{PORT}/ui?key={KEY}")
            return 0
    _log("Launched but port not listening after 10s. Check logs/dashboard.log.")
    return 0


def _kill(pid):
    """Kill pid with its process tree. Falls back to TerminateProcess when
    taskkill reports failure (blocked by policy, or the PID is gone), so a
    stale dashboard can never survive a stop."""
    if os.name != "nt":
        try:
            os.kill(pid, 15)
        except Exception:
            pass
        return
    ok = False
    try:
        ok = subprocess.run(
            ["taskkill", "/PID", str(pid), "/F", "/T"],
            capture_output=True,
        ).returncode == 0
    except Exception:
        ok = False
    if not ok:
        try:
            os.kill(pid, 9)
        except Exception:
            pass
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue"],
                capture_output=True,
            )
        except Exception:
            pass


def stop():
    pid = _read_pid()
    targets = []
    if _pid_alive(pid):
        targets.append(pid)
    for p in _pids_on_port():
        if p not in targets:
            targets.append(p)
    for p in targets:
        _kill(p)
    if os.path.exists(PID_FILE):
        try:
            os.remove(PID_FILE)
        except Exception:
            pass
    left = _pids_on_port()
    if left:
        _log(f"[WARN] Port {PORT} still LISTENING "
             f"(PID {', '.join(map(str, left))}). Stop it manually.")
        return 1
    if targets:
        _log(f"Stopped (PID {', '.join(map(str, targets))}).")
    else:
        _log("No running dashboard process found.")
    return 0


def status():
    pid = _read_pid()
    alive = _pid_alive(pid)
    port_pids = _pids_on_port()
    if alive or port_pids:
        where = f"PID {pid}" if alive else "port PID " + ", ".join(map(str, port_pids))
        _log(f"Dashboard running ({where}). http://{HOST}:{PORT}/ui?key={KEY}")
        return 0
    _log(f"Dashboard not running. http://{HOST}:{PORT}/ui?key={KEY}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Dashboard start/stop manager")
    parser.add_argument("action", nargs="?", default="start",
                        choices=["start", "stop", "restart", "status"],
                        help="start / stop / restart / status (default start)")
    args = parser.parse_args()

    if args.action == "start":
        return start()
    if args.action == "stop":
        return stop()
    if args.action == "restart":
        stop()
        time.sleep(2)
        return start()
    if args.action == "status":
        return status()
    return 1


if __name__ == "__main__":
    sys.exit(main())
