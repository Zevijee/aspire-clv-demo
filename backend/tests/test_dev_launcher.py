"""Exercise the real launcher and Uvicorn against disposable apps, without the DB."""

import importlib.util
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

LAUNCHER = Path(__file__).resolve().parents[2] / "run_app.py"
spec = importlib.util.spec_from_file_location("dev_launcher", LAUNCHER)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def app_code(version):
    return (
        "import os\nfrom fastapi import FastAPI\napp = FastAPI()\n"
        "@app.get('/')\ndef health():\n"
        f"    return {{'version': {version!r}, 'pid': os.getpid()}}\n"
    )


def wait_for(check, log, process, timeout=25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        assert process.poll() is None, log.read_text(encoding="utf-8", errors="replace")
        try:
            result = check()
            if result:
                return result
        except (OSError, urllib.error.URLError, ValueError):
            pass
        time.sleep(0.1)
    pytest.fail(log.read_text(encoding="utf-8", errors="replace"))


def get_json(port):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=0.5) as response:
        return json.load(response)


@pytest.fixture
def dev_workspace(tmp_path):
    app_dir = tmp_path / "backend" / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "__init__.py").write_text("", encoding="utf-8")
    (app_dir / "main.py").write_text(app_code("initial"), encoding="utf-8")
    shutil.copyfile(LAUNCHER.parent / "backend" / "dev_server.py",
                    tmp_path / "backend" / "dev_server.py")
    vite = tmp_path / "frontend" / "node_modules" / "vite" / "bin" / "vite.js"
    vite.parent.mkdir(parents=True)
    # A tiny frontend server lets the test detect shutdowns independently of Vite.
    vite.write_text(
        "const http = require('http');\n"
        "const port = Number(process.argv[process.argv.indexOf('--port') + 1]);\n"
        "http.createServer((req,res) => {res.setHeader('Content-Type','application/json');"
        "res.end(JSON.stringify({pid:process.pid}));}).listen(port,'127.0.0.1');\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("", encoding="utf-8")
    return tmp_path


def start_launcher(workspace, api_port, ui_port):
    bootstrap = (
        f"import sys; sys.path.insert(0, {str(LAUNCHER.parent)!r}); "
        f"import run_app; from pathlib import Path; run_app.ROOT = Path({str(workspace)!r}); "
        "sys.exit(run_app.main())"
    )
    options = {"start_new_session": True}
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        # Isolate the test console too: the old bug must not interrupt pytest.
        options = {"creationflags": subprocess.CREATE_NEW_CONSOLE, "startupinfo": startupinfo}
    log = workspace / "launcher.log"
    with log.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(
            [sys.executable, "-u", "-c", bootstrap, "--backend-port", str(api_port),
             "--frontend-port", str(ui_port)],
            stdout=output, stderr=subprocess.STDOUT, **options,
        )
    return process, log


@pytest.mark.parametrize("broken_at_start", [False, True])
def test_reloads_and_recovers_without_stopping_frontend(dev_workspace, broken_at_start):
    assert shutil.which("node"), "Node.js is needed for launcher integration tests"
    api_port, ui_port = free_port(), free_port()
    source = dev_workspace / "backend" / "app" / "main.py"
    if broken_at_start:
        source.write_text("def unfinished(\n", encoding="utf-8")
    process, log = start_launcher(dev_workspace, api_port, ui_port)
    try:
        frontend = wait_for(lambda: get_json(ui_port), log, process)
        if broken_at_start:
            wait_for(lambda: "SyntaxError" in log.read_text(), log, process)
            source.write_text(app_code("initial"), encoding="utf-8")
        initial = wait_for(lambda: get_json(api_port), log, process)
        assert initial["version"] == "initial"
        # Test the atomic replacement save used by many editors.
        replacement = source.with_suffix(".tmp")
        replacement.write_text(app_code("updated"), encoding="utf-8")
        replacement.replace(source)
        updated = wait_for(lambda: (value if (value := get_json(api_port))["version"]
                                   == "updated" else None), log, process)
        assert updated["pid"] != initial["pid"]
        assert get_json(ui_port) == frontend
        previous_errors = log.read_text().count("SyntaxError")
        source.write_text("def unfinished(\n", encoding="utf-8")
        wait_for(lambda: log.read_text().count("SyntaxError") > previous_errors, log, process)
        assert get_json(ui_port) == frontend
        source.write_text(app_code("recovered"), encoding="utf-8")
        wait_for(lambda: get_json(api_port)["version"] == "recovered", log, process)
        assert get_json(ui_port) == frontend
        # A second valid edit proves the watcher continues after recovery.
        source.write_text(app_code("final-save"), encoding="utf-8")
        wait_for(lambda: get_json(api_port)["version"] == "final-save", log, process)
        assert get_json(ui_port) == frontend
    finally:
        launcher.stop_process(process)


def test_backend_supervisor_restarts_without_stopping_frontend(dev_workspace):
    api_port, ui_port = free_port(), free_port()
    process, log = start_launcher(dev_workspace, api_port, ui_port)
    try:
        frontend = wait_for(lambda: get_json(ui_port), log, process)
        worker = wait_for(lambda: get_json(api_port), log, process)
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(worker["pid"]), "/F"],
                           capture_output=True, check=True)
        else:
            os.kill(worker["pid"], signal.SIGTERM)
        wait_for(lambda: get_json(api_port)["pid"] != worker["pid"], log, process)
        assert get_json(ui_port) == frontend
        # Read only the PID emitted by our disposable reloader.
        import re
        match = re.search(r"Started development supervisor \[(\d+)\]", log.read_text())
        assert match
        reloader_pid = int(match[1])
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(reloader_pid), "/T", "/F"],
                           capture_output=True, check=True)
        else:
            os.kill(reloader_pid, signal.SIGTERM)
        wait_for(lambda: "restarting in 2 seconds" in log.read_text(), log, process)
        assert get_json(ui_port) == frontend
        wait_for(lambda: log.read_text().count("Started development supervisor") >= 2, log, process)
        wait_for(lambda: get_json(api_port), log, process)
        assert get_json(ui_port) == frontend
    finally:
        launcher.stop_process(process)


def test_ctrl_c_stops_both_services_and_releases_ports(dev_workspace):
    api_port, ui_port = free_port(), free_port()
    process, log = start_launcher(dev_workspace, api_port, ui_port)
    try:
        wait_for(lambda: get_json(api_port), log, process)
        wait_for(lambda: get_json(ui_port), log, process)
        if os.name == "nt":
            # Send Ctrl+C only into the disposable launcher's console, never pytest's.
            helper = (
                "import ctypes; k = ctypes.windll.kernel32; k.FreeConsole(); "
                f"assert k.AttachConsole({process.pid}); "
                "assert k.SetConsoleCtrlHandler(None, True); "
                "assert k.GenerateConsoleCtrlEvent(0, 0)"
            )
            subprocess.run([sys.executable, "-c", helper], check=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            process.send_signal(signal.SIGINT)
        assert process.wait(timeout=15) == 0, log.read_text()
        assert "Stopping both services" in log.read_text()
        for port in (api_port, ui_port):
            with socket.socket() as probe:
                assert probe.connect_ex(("127.0.0.1", port)) != 0
    finally:
        launcher.stop_process(process)
