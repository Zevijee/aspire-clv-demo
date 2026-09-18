"""Compact, dependency-free progress output shared by database commands and seeds."""
import os
import shutil
import sys
import textwrap
from datetime import datetime
from threading import Event, RLock, Thread
from time import perf_counter
from unicodedata import combining, east_asian_width


_output_lock = RLock()
_active = None


def _columns():
    try:
        return max(1, os.get_terminal_size(sys.stdout.fileno()).columns - 1)
    except (OSError, ValueError, AttributeError):
        return max(1, shutil.get_terminal_size((100, 24)).columns - 1)


def _clean(value):
    return ' '.join(str(value).split())


def _clip(value, width):
    """Count display cells, including wide characters; never reach the wrap column."""
    cells, result = 0, []
    for character in value:
        size = 0 if combining(character) else 2 if east_asian_width(character) in ('W', 'F') else 1
        if cells + size > width:
            return ''.join(result), cells
        result.append(character)
        cells += size
    return ''.join(result), cells


def message(value=''):
    """Print a permanent message without colliding with the progress thread."""
    with _output_lock:
        if _active is not None:
            _active._clear()
        print(value, flush=True)
        if _active is not None:
            _active._render()


class RunProgress:
    """Timestamped stage history plus one live line with actual elapsed time."""
    def __init__(self, name):
        self.name = _clean(name)
        self.started = self.phase_started = perf_counter()
        self.phase = 'Connecting'
        self.total = None
        self.done = 0
        self.unit = 'rows'
        self.details = ''
        self.phase_name = self.name
        self.phase_open = False
        self.lock = _output_lock
        self.stopped = Event()
        self.interactive = sys.stdout.isatty()
        self.width = 0
        self.thread = Thread(target=self._heartbeat, daemon=True)

    @staticmethod
    def duration(seconds):
        minutes, seconds = divmod(max(0, int(seconds)), 60)
        hours, minutes = divmod(minutes, 60)
        return f'{hours:d}:{minutes:02}:{seconds:02}' if hours else f'{minutes:02}:{seconds:02}'

    def set_phase(self, phase, total=None, unit='rows', details=''):
        with self.lock:
            self._finish_phase({'Failed': 'failed', 'Paused': 'paused'}.get(phase, 'done'))
            self.phase, self.total, self.unit = _clean(phase), total, _clean(unit)
            self.details = _clean(details)
            self.done = 0
            self.phase_started = perf_counter()
            self.phase_name = self.name
            if self.phase not in ('Complete', 'Skipped', 'Failed', 'Paused', 'Deferred'):
                self._begin_phase()

    def _stage_line(self, status, seconds=None):
        self._clear()
        stamp = datetime.now().astimezone().isoformat(timespec='seconds')
        line = f'  {self.phase_name} | {stamp} | {self.phase} | {status}'
        if seconds is not None:
            line += f' | {seconds:.3f}s'
        if self.details:
            line += f' | {self.details}'
        print(textwrap.fill(line, width=max(12, _columns()), subsequent_indent='    ',
            replace_whitespace=False), flush=True)

    def _begin_phase(self):
        self.phase_open = True
        self._stage_line('started')

    def _finish_phase(self, status='done'):
        if self.phase_open:
            self._stage_line(status, perf_counter() - self.phase_started)
            self.phase_open = False

    def advance(self, amount, details=None):
        with self.lock:
            self.done += amount
            if details is not None:
                self.details = _clean(details)

    def describe(self, details):
        with self.lock:
            self.details = _clean(details)

    def _clear(self):
        if self.interactive and self.width:
            sys.stdout.write('\r' + ' ' * min(self.width, _columns()) + '\r')
            sys.stdout.flush()
            self.width = 0

    def _render(self, final=False):
        with self.lock:
            now = perf_counter()
            elapsed = self.duration(now - self.started)
            if final:
                self._clear()
                status = {'Complete': 'done', 'Skipped': 'skipped', 'Failed': 'failed',
                    'Paused': 'paused', 'Deferred': 'deferred'}.get(self.phase, self.phase.lower())
                stamp = datetime.now().astimezone().isoformat(timespec='seconds')
                line = f'  {self.name} | {stamp} | {status}'
                if self.details:
                    line += f' - {self.details}'
                if self.phase != 'Skipped':
                    line += f' ({elapsed})'
                # Permanent results may wrap, with a clear continuation indent.
                print(textwrap.fill(line, width=max(12, _columns()), subsequent_indent='    ',
                    replace_whitespace=False), flush=True)
                return
            parts = [f'  {self.name}', datetime.now().astimezone().strftime('%H:%M:%S'),
                self.phase, f'stage {self.duration(now - self.phase_started)}', f'total {elapsed}']
            if self.total is not None:
                percent = min(100, 100 * self.done / self.total) if self.total else 100
                remaining = max(0, self.total - self.done)
                rate = self.done / max(now - self.phase_started, 0.001)
                parts.append(f'{percent:.0f}%  {self.done:,}/{self.total:,}')
                if rate:
                    parts.append(f'ETA {self.duration(remaining / rate)}')
            else:
                if self.done:
                    parts.append(f'{self.done:,} {self.unit}')
            if self.details:
                parts.append(self.details)
            line = ' | '.join(parts)
            if self.interactive:
                line, width = _clip(line, _columns())
                padding = max(0, min(self.width, _columns()) - width)
                sys.stdout.write('\r' + line + ' ' * padding)
                sys.stdout.flush()
                self.width = width
            else:
                print(line, flush=True)

    def _heartbeat(self):
        while not self.stopped.wait(1 if self.interactive else 30):
            self._render()

    def __enter__(self):
        global _active
        with self.lock:
            if _active is not None:
                raise RuntimeError('Progress displays must be sequential, not nested.')
            _active = self
            self._begin_phase()
            if self.interactive:
                self._render()
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback):
        global _active
        self.stopped.set()
        self.thread.join()
        with self.lock:
            if exc_type is not None:
                self.set_phase('Paused' if issubclass(exc_type, KeyboardInterrupt) else 'Failed',
                    details='committed work is saved')
            self._finish_phase()
            self._render(final=True)
            _active = None
