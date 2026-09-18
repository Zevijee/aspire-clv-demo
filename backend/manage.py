"""Start the API from any working directory: python backend/manage.py serve --reload."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('serve',))
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--reload', action='store_true', help='Reload active backend/shared code; ignore staged schema drafts.')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535.')
    excluded = [ROOT / 'shared' / 'database' / name for name in ('staged', 'stage-history')]
    if args.reload:
        # Uvicorn recognizes directory exclusions only when they already exist.
        for directory in excluded:
            directory.mkdir(parents=True, exist_ok=True)
    import uvicorn
    uvicorn.run('backend.app.main:create_app', factory=True, host=args.host, port=args.port,
        reload=args.reload, reload_dirs=[str(ROOT / 'backend'), str(ROOT / 'shared')] if args.reload else None,
        reload_excludes=[str(directory) for directory in excluded] if args.reload else None,
        log_level='info')


if __name__ == '__main__':
    main()
