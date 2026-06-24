#!/usr/bin/env python3
"""
Development server with auto-reload for Persona Mirror (mbti/).
Watches .py and .html files in the mbti directory and restarts on change.

Usage:
    python mbti/dev.py [--port 8899]
"""
import os
import sys
import time
import signal
import subprocess
from pathlib import Path
from threading import Thread, Event

HERE = Path(__file__).parent
PORT = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == '--port' else 8899

server_proc = None
stop_event = Event()

def start_server():
    global server_proc
    if server_proc:
        server_proc.kill()
        server_proc.wait()
    env = os.environ.copy()
    server_proc = subprocess.Popen(
        [sys.executable, str(HERE / "server.py"), "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=HERE, env=env
    )
    print(f"[dev] Server started (PID {server_proc.pid}) on port {PORT}", flush=True)

def watcher():
    """Poll mtime of relevant files every 1.5s."""
    exts = (".py", ".html", ".json")
    last_mtimes = {}
    while not stop_event.is_set():
        changed = False
        for fpath in HERE.rglob("*"):
            if fpath.suffix not in exts or fpath.name.startswith("_"):
                continue
            mtime = fpath.stat().st_mtime
            old = last_mtimes.get(fpath)
            if old is not None and mtime != old:
                print(f"[dev] Change detected: {fpath.relative_to(HERE)}", flush=True)
                changed = True
            last_mtimes[fpath] = mtime
        if changed:
            start_server()
        stop_event.wait(1.5)

if __name__ == "__main__":
    print(f"[dev] Watching {HERE} for changes (*.py, *.html, *.json)…", flush=True)
    start_server()
    try:
        watcher()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        if server_proc:
            server_proc.kill()
        print("[dev] Stopped", flush=True)
