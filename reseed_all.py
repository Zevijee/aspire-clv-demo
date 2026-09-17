"""Run the shared seeding framework from the project root."""

import argparse
import os
import subprocess
import sys
from datetime import date

from run_app import ROOT, backend_python, bind_windows_process_tree, stop_process


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify setup without changing data")
    parser.add_argument("--as-of", type=date.fromisoformat, help="Override local today (YYYY-MM-DD)")
    parser.add_argument("--incremental", action="store_true", help="Fill missing days and retain overlap")
    args = parser.parse_args()
    active_process = None
    process_job = bind_windows_process_tree()
    try:
        command = [backend_python(), "-u", "-m", "seeding"]
        if args.check:
            command.append("--check")
        elif not args.incremental:
            command.append("full-reset")
        if args.as_of is not None:
            command.extend(["--as-of", args.as_of.isoformat()])
        options = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
                   if os.name == "nt" else {"start_new_session": True})
        active_process = subprocess.Popen(command, cwd=ROOT / "backend", **options)
        code = active_process.wait()
        active_process = None
        if code == 0 and not args.check:
            print("Done. Refresh the app to use the updated demo data.")
        return code if code >= 0 else 1
    except KeyboardInterrupt:
        print("\nStopping the seed process; any uncommitted transaction will be rolled back.")
        return 130
    except OSError as error:
        print(f"Cannot start seeding: {error}", file=sys.stderr)
        return 1
    finally:
        if active_process is not None:
            stop_process(active_process)


if __name__ == "__main__":
    raise SystemExit(main())
