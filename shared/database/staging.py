"""Explicit schema drafts, isolated from API imports and migration discovery."""
from datetime import datetime, timezone
import ast
from functools import wraps
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

from .console import message

ROOT = Path(__file__).resolve().parent
DRAFT = ROOT / 'staged'
HISTORY = ROOT / 'stage-history'
MANIFEST = DRAFT / 'manifest.json'


def _locked(action):
    @wraps(action)
    def run(*args, **kwargs):
        with (ROOT / '.staging.lock').open('a+b') as handle:
            if handle.tell() == 0:
                handle.write(b'\0')
                handle.flush()
            handle.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise ValueError('Another schema staging command is running. Wait for it to finish.') from None
            try:
                return action(*args, **kwargs)
            finally:
                handle.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)
    return run


def _hash(path):
    return _digest(path.read_bytes(), path.suffix)


def _digest(content, suffix):
    if suffix in ('.py', '.sql', '.mako', '.json', '.csv', '.txt', '.md'):
        content = content.replace(b'\r\n', b'\n')
    return sha256(content).hexdigest()


def _atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_bytes(content)
    temporary.replace(path)


def _write_manifest(value):
    _atomic(MANIFEST, (json.dumps(value, indent=2, sort_keys=True) + '\n').encode())


def _active_files():
    return {path.relative_to(ROOT).as_posix(): _hash(path) for path in ROOT.rglob('*')
        if path.is_file() and not path.name.endswith('.tmp') and (path.suffix in ('.py', '.sql', '.mako')
            or path.relative_to(ROOT).parts[0] in ('migrations', 'backfills'))
        and not any(part in ('staged', 'stage-history', '__pycache__')
            for part in path.relative_to(ROOT).parts)}


def manifest():
    if not MANIFEST.exists():
        raise ValueError('No schema draft. Run python manage.py stage, then edit shared/database/staged/schema.py.')
    result = json.loads(MANIFEST.read_text(encoding='utf-8'))
    if result.get('version') != 1 or result.get('phase') not in ('draft', 'publishing', 'published', 'applied'):
        raise ValueError('Unsupported schema staging manifest.')
    return result


@_locked
def begin():
    if MANIFEST.exists():
        current = manifest()
        if current['phase'] != 'applied':
            message('  Schema draft  already exists; active schema remains unchanged')
            message('  Edit shared/database/staged/schema.py')
            return
        # Retain the completed draft for local recovery instead of deleting it.
        archive = HISTORY / current['id']
        if not DRAFT.resolve().is_relative_to(ROOT.resolve()) or not archive.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError('Schema draft/archive must remain inside shared/database.')
        archive.parent.mkdir(parents=True, exist_ok=True)
        DRAFT.rename(archive)
    elif DRAFT.exists() and any(DRAFT.iterdir()):
        raise ValueError('The staging directory contains files without a manifest; preserve/reconcile them before starting a draft.')
    identity = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    _atomic(DRAFT / 'schema.py', (ROOT / 'schema.py').read_bytes())
    _atomic(DRAFT / 'backfills' / 'runner.py', (ROOT / 'backfills' / 'runner.py').read_bytes())
    (DRAFT / 'migrations' / 'versions').mkdir(parents=True, exist_ok=True)
    _write_manifest(dict(version=1, id=identity, phase='draft', base=_active_files()))
    message('  Schema draft  created in shared/database/staged/schema.py')
    message('  Edit the draft, then run revision --message "describe the change"')
    message('  Run update when ready to apply it and catch up missing days.')
    message('  The API and ordinary upgrade ignore staged changes.')


def _draft_files():
    files = {}
    for path in DRAFT.rglob('*'):
        if not path.is_file() or path.name == 'manifest.json' or path.name.endswith('.tmp'):
            continue
        relative = path.relative_to(DRAFT)
        if '__pycache__' in relative.parts:
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(DRAFT.resolve()):
            raise ValueError('Draft files must remain inside the staging directory.')
        if relative.as_posix() != 'schema.py' and relative.parts[0] not in ('migrations', 'backfills'):
            raise ValueError(f'Unsupported staged file: {relative}')
        files[relative.as_posix()] = path
    return files


def validate_draft():
    state = manifest()
    if state['phase'] != 'draft':
        raise ValueError('This draft is already being applied. Resume update; do not edit it.')
    if _active_files() != state['base']:
        raise ValueError('Active database code changed after this draft began. Reconcile the draft/base before applying it.')
    files = _draft_files()
    if 'schema.py' not in files or 'backfills/runner.py' not in files:
        raise ValueError('The draft must retain schema.py and backfills/runner.py.')
    for relative in files:
        if relative in state['base'] and relative not in ('schema.py', 'backfills/runner.py'):
            raise ValueError(f'Do not overwrite existing migration/backfill files: {relative}. Add a new file.')
    return state


def metadata():
    validate_draft()
    spec = importlib.util.spec_from_file_location('shared.database._schema_draft', DRAFT / 'schema.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.metadata


def describe():
    if not MANIFEST.exists():
        message('  Staged changes  none')
        return
    state = manifest()
    message(f'  Staged changes  {state["phase"]}')
    for relative, path in sorted(_draft_files().items()):
        if state['base'].get(relative) != _hash(path):
            message(f'    {relative}')
    if state['phase'] != 'applied':
        message('  Apply with: python manage.py update')


def needs_apply():
    if not MANIFEST.exists():
        return False
    state = manifest()
    if state['phase'] in ('publishing', 'published'):
        return True
    return state['phase'] == 'draft' and any(state['base'].get(relative) != _hash(path)
        for relative, path in _draft_files().items())


def _validate_chain(files):
    from .lifecycle import scripts
    active = scripts()
    head = active.get_current_head()
    existing = {item.revision for item in active.walk_revisions()}
    remaining = {}
    for relative, path in files.items():
        if not relative.startswith('migrations/versions/') or path.suffix != '.py':
            continue
        values = {}
        for node in ast.parse(path.read_text(encoding='utf-8-sig')).body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in ('revision', 'down_revision'):
                        values[target.id] = ast.literal_eval(node.value)
        name, parent = values.get('revision'), values.get('down_revision')
        if not isinstance(name, str) or not isinstance(parent, str) or name in existing or name in remaining:
            raise ValueError(f'{relative} needs a unique revision and a single parent revision.')
        remaining[name] = parent
    while remaining:
        children = [name for name, parent in remaining.items() if parent == head]
        if len(children) != 1:
            raise ValueError('Staged migrations must form one chain extending the active head.')
        head = children[0]
        del remaining[head]


@_locked
def apply(*, batch_size=10000, max_batches=None, command_name='upgrade', arguments=()):
    """Publish only on explicit apply, then use the normal resumable upgrade.

    Migrations publish first so reloading API processes fail readiness rather
    than importing a newer schema while still expecting the old database head.
    The existing upgrade lock protects the actual database changes/backfills.
    """
    state = manifest()
    if state['phase'] == 'applied':
        message('  Staged changes  already applied; use stage to start another change')
        return 0
    files = _draft_files()
    contents = {relative: path.read_bytes() for relative, path in files.items()}
    planned = {relative: _digest(content, files[relative].suffix) for relative, content in contents.items()}
    if state['phase'] == 'draft':
        validate_draft()
        _validate_chain(files)
        if planned['schema.py'] != state['base']['schema.py'] and not any(
                relative.startswith('migrations/versions/') for relative in planned):
            raise ValueError('The schema draft changed but has no migration. Run revision first.')
        if all(state['base'].get(relative) == digest for relative, digest in planned.items()):
            raise ValueError('The draft has no changes to apply.')
        # Freeze content before publishing; failed upgrades resume these exact files.
        state.update(phase='publishing', planned=planned)
        _write_manifest(state)
    elif state.get('planned') != planned:
        raise ValueError('The applying draft was edited. Restore its frozen contents before resuming update.')
    active = _active_files()
    if set(active) - set(state['base']) - set(planned) or any(
            relative not in active or active[relative] not in (before, planned.get(relative))
            for relative, before in state['base'].items()) or any(
            relative not in state['base'] and relative in active and active[relative] != digest
            for relative, digest in planned.items()):
        raise ValueError('Active files no longer match the staged base or published change; reconcile before resuming.')
    for relative in sorted(files, key=lambda name: (not name.startswith('migrations/'), name)):
        target = ROOT / relative
        if not target.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError('Staged destinations must remain inside shared/database.')
        _atomic(target, contents[relative])
    state['phase'] = 'published'
    _write_manifest(state)
    message('  Staged files  published; applying migrations/backfills')
    # A fresh process imports the published schema and backfill registry together.
    # DATABASE_URL is inherited in the environment, never placed on the command line.
    command = [sys.executable, str(ROOT.parents[1] / 'sandbox-data' / 'manage.py'),
        command_name, '--batch-size', str(batch_size), *arguments]
    if max_batches is not None:
        command += ['--max-batches', str(max_batches)]
    environment = dict(os.environ, ASPIRE_DATABASE_STAGE_WORKER='1')
    result = subprocess.run(command, cwd=ROOT.parents[1], env=environment, check=False)
    if result.returncode:
        message('  Staged update incomplete. Resume: python manage.py update')
        return result.returncode
    state['phase'] = 'applied'
    _write_manifest(state)
    # Trigger one final development reload after upgrade has released its DB lock.
    os.utime(ROOT / 'schema.py', None)
    message('  Staged changes  applied; development API reload requested')
    return 0
