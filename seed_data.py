"""Terminal-owned root launcher for explicit demo commands; no sys.path mutation."""
import os
import subprocess
import sys

from run_app import ROOT, backend_python, bind_windows_process_tree, stop_process


def main():
    process_job = bind_windows_process_tree()
    process = None
    try:
        options = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
                   else {"start_new_session": True})
        process = subprocess.Popen([backend_python(), "-u", "-m", "seeding", *sys.argv[1:]],
                                   cwd=ROOT / "backend", **options)
        return process.wait()
    except KeyboardInterrupt:
        return 130
    finally:
        if process is not None and process.poll() is None:
            stop_process(process)


if __name__ == "__main__":
    raise SystemExit(main())
