"""Run the local API and frontend together: python run_app.py."""

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def bind_windows_process_tree():
    """Let Windows kill every descendant when the launcher dies, even forcibly.

    Enroll the launcher before spawning anything so children inherit membership
    atomically. The job handle is non-inheritable and stays open until process
    exit; no child can keep it alive after the terminal kills the launcher.
    """
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    limits = ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        error = ctypes.WinError(ctypes.get_last_error())
        kernel.CloseHandle(job)
        raise error
    if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        error = ctypes.WinError(ctypes.get_last_error())
        kernel.CloseHandle(job)
        raise error
    return job


def backend_python() -> str:
    for folder in (ROOT / "backend" / ".venv", ROOT / ".venv"):
        executable = folder / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if executable.is_file():
            return str(executable)
    return sys.executable


def commands(*, check_app: bool = False, backend_port: int = 8000,
             frontend_port: int = 5173) -> list[tuple[str, list[str], Path]]:
    if not all(1 <= port <= 65535 for port in (backend_port, frontend_port)):
        raise RuntimeError("Ports must be between 1 and 65535.")
    if backend_port == frontend_port:
        raise RuntimeError("Frontend and backend must use different ports.")
    python = backend_python()
    node = shutil.which("node")
    vite = ROOT / "frontend/node_modules/vite/bin/vite.js"
    if node is None:
        raise RuntimeError("Node.js is missing. Install Node.js and run npm install in frontend.")
    if not vite.is_file():
        raise RuntimeError("Frontend dependencies are missing. Run npm install in frontend.")
    if not (ROOT / ".env").is_file():
        raise RuntimeError("Copy .env.example to .env and configure your local DATABASE_URL.")
    check = subprocess.run(
        # Let the reloader start even while an application edit has an import or
        # syntax error. The explicit --check command still validates the app.
        [python, "-c", "import uvicorn, fastapi, sqlalchemy"
         + ("; import api.main" if check_app else "")],
        cwd=ROOT / "backend", capture_output=True, text=True,
        timeout=30, check=False,
    )
    if check.returncode:
        raise RuntimeError(
            f'Backend setup failed using {python}. Install dependencies with '
            'python -m pip install -e . in backend and check your .env settings.'
        )
    for port in (backend_port, frontend_port):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError as error:
                raise RuntimeError(
                    f"Port {port} is unavailable. Stop the service using it before launching."
                ) from error
    return [
        ("Backend", [python, str(ROOT / "backend" / "dev_server.py"),
                     "--host", "127.0.0.1", "--port", str(backend_port)], ROOT / "backend"),
        ("Frontend", [node, str(vite), "--host", "127.0.0.1", "--port", str(frontend_port),
                      "--strictPort"], ROOT / "frontend"),
    ]


def start_service(name: str, command: list[str], directory: Path, env: dict[str, str]):
    if os.name == "nt":
        # Share the terminal; isolate Ctrl+C so the launcher coordinates shutdown.
        options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        options = {"start_new_session": True}
    process = subprocess.Popen(
        command, cwd=directory, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1, **options,
    )

    def forward_output():
        with process.stdout:
            for line in process.stdout:
                try:
                    print(f"[{name}] {line}", end="", flush=True)
                except (OSError, ValueError):
                    return

    threading.Thread(target=forward_output, name=f"{name}-output", daemon=True).start()
    print(f"Starting {name.lower()}...", flush=True)
    return process


def stop_process(process: subprocess.Popen) -> None:
    """Stop only our service's process group, including reload workers."""
    if os.name == "nt":
        if process.poll() is None:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        process.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check setup without starting servers")
    parser.add_argument("--backend-port", type=int, default=8000)
    parser.add_argument("--frontend-port", type=int, default=5173)
    args = parser.parse_args()
    processes: list[tuple[str, subprocess.Popen]] = []
    try:
        # Keep the raw handle alive until OS process teardown, including crashes.
        process_job = bind_windows_process_tree()
        services = commands(check_app=args.check, backend_port=args.backend_port,
                            frontend_port=args.frontend_port)
        if args.check:
            print("Setup OK. Frontend and backend ports are available.")
            return 0
        env = {**os.environ, "VITE_API_BASE_URL": f"http://localhost:{args.backend_port}",
               "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
        if args.frontend_port != 5173:
            env.setdefault("CORS_ORIGINS", f"http://localhost:{args.frontend_port},"
                           f"http://127.0.0.1:{args.frontend_port}")
        for name, command, directory in services:
            process = start_service(name, command, directory, env)
            processes.append((name, process))
        print(f"Frontend: http://localhost:{args.frontend_port}\nAPI: http://localhost:{args.backend_port}"
              "\nBackend auto-reload is watching backend packages."
              "\nPress Ctrl+C to stop both services.", flush=True)
        restart_at = None
        while True:
            for index, (name, process) in enumerate(processes):
                code = process.poll()
                if code is not None:
                    if name == "Backend":
                        if restart_at is None:
                            print(f"Backend supervisor exited (code {code}); "
                                  "restarting in 2 seconds."
                                  " Frontend stays running.", flush=True)
                            restart_at = time.monotonic() + 2
                        elif time.monotonic() >= restart_at:
                            stop_process(process)
                            _, command, directory = services[index]
                            processes[index] = (name, start_service(name, command, directory, env))
                            restart_at = None
                        continue
                    print(f"{name} exited (code {code}); stopping both services.", flush=True)
                    return code if code > 0 else 1
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("\nStopping both services...", flush=True)
        return 0
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"Cannot start app: {error}", file=sys.stderr)
        return 1
    finally:
        for _, process in reversed(processes):
            stop_process(process)


if __name__ == "__main__":
    raise SystemExit(main())
