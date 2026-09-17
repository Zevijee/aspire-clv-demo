"""Share the running demo through ngrok; Ctrl+C stops only sharing processes."""
import os
import shutil
import subprocess
import time
from urllib.request import urlopen

from run_app import ROOT, bind_windows_process_tree, stop_process


def main():
    node, ngrok = shutil.which('node'), shutil.which('ngrok')
    if not node or not ngrok:
        raise SystemExit('Node.js and ngrok must be installed.')
    job = bind_windows_process_tree()
    children = []
    options = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
    try:
        frontend = subprocess.Popen([node, str(ROOT / 'frontend/node_modules/vite/bin/vite.js'),
            '--config', 'vite.share.config.ts'], cwd=ROOT / 'frontend',
            env={**os.environ, 'VITE_API_BASE_URL': ''}, **options)
        children.append(frontend)
        for _ in range(60):
            if frontend.poll() is not None:
                raise RuntimeError('Sharing frontend could not start.')
            try:
                with urlopen('http://127.0.0.1:5174/adt/admissions', timeout=1):
                    break
            except OSError:
                time.sleep(0.25)
        else:
            raise RuntimeError('Sharing frontend did not become ready.')
        tunnel = subprocess.Popen([ngrok, 'http', 'http://127.0.0.1:5174',
            '--host-header=rewrite', '--log=stdout', '--log-format=json'], **options)
        children.append(tunnel)
        while frontend.poll() is None and tunnel.poll() is None:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print('Stopping sharing.')
    finally:
        for child in reversed(children):
            stop_process(child)


if __name__ == '__main__':
    main()
