"""Local API supervisor: poll for saves and replace only the Uvicorn worker."""

import argparse
import compileall
import os
import py_compile
import signal
import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
SOURCE_PACKAGES = ("api", "common", "data", "domain", "reporting", "seeding", "app")


def source_snapshot():
    files = [path for package in SOURCE_PACKAGES for path in BACKEND.joinpath(package).rglob("*.py")]
    files.extend((BACKEND / "pyproject.toml", BACKEND.parent / ".env"))
    snapshot = {}
    for path in files:
        try:
            stat = path.stat()
            snapshot[str(path)] = (stat.st_mtime_ns, stat.st_size)
        except FileNotFoundError:
            pass  # Editors can replace a file between enumeration and stat.
    return snapshot


def stop_worker(worker):
    if worker.poll() is None:
        # Do not broadcast CTRL_C_EVENT on Windows: it can interrupt the launcher
        # or hang the reloader. Terminate only this local, disposable API worker.
        worker.terminate()
    try:
        worker.wait(timeout=5)
    except subprocess.TimeoutExpired:
        worker.kill()
        worker.wait(timeout=5)


def start_worker(host, port):
    # Timestamp-only pycs can serve old code after same-size saves in one second.
    # Checked hashes keep rapid edits correct, without touching application data.
    for package in SOURCE_PACKAGES:
        compileall.compile_dir(BACKEND / package, quiet=2, force=True,
                               invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH)
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.main:app", "--host", host, "--port", str(port)],
        cwd=BACKEND,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    stopping = False

    def request_stop(_signal, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    snapshot = source_snapshot()
    changed_at = None
    retry_at = None
    worker = None
    print(f"Started development supervisor [{os.getpid()}]. Watching backend packages and .env.",
          flush=True)
    try:
        worker = start_worker(args.host, args.port)
        while not stopping:
            current = source_snapshot()
            now = time.monotonic()
            if current != snapshot:
                snapshot = current
                changed_at = now
            if changed_at is not None and now - changed_at >= 0.5:
                print("Source changed; reloading API worker...", flush=True)
                stop_worker(worker)
                worker = start_worker(args.host, args.port)
                changed_at = retry_at = None
            elif worker.poll() is not None:
                if retry_at is None:
                    print(f"API worker exited (code {worker.returncode}); "
                          "watching for edits and retrying in 2 seconds.", flush=True)
                    retry_at = now + 2
                elif now >= retry_at and changed_at is None:
                    worker = start_worker(args.host, args.port)
                    retry_at = None
            time.sleep(0.1)
    finally:
        if worker is not None:
            stop_worker(worker)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
