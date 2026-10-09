"""Rebuild what changed generator code built, without being asked.

update generates missing days. A finished day looks the same whichever code
built it, so on its own update cannot tell that a generator's rules changed: a
deploy that adds a generated column or changes a rule left old rows in place
until someone ran --regenerate by hand. This module closes that gap.

Each generator's rules have a fingerprint: a hash of its module's code, plus
any shared helper its rules import. update compares the fingerprints saved in
sandbox_generator_rules with the code it is running and, before generating
days, rebuilds every generator whose fingerprint changed and everything built
from it. Then it saves the new fingerprints.

The fingerprint is taken from the parsed code with docstrings removed, so a
comment, docstring or formatting edit changes nothing and rebuilds nothing.

Not everything can be rebuilt in place. The day-by-day ADT simulation carries
state from one day to the next, and facilities, payers and residents are the
keys everything else hangs on; a change to any of those needs
seed --reset-history. update says so every run until it is done, and never
records their new fingerprint, so the warning cannot be lost.

The first time a database is seen -- no fingerprints saved -- the current ones
are recorded without rebuilding: the data is taken to match the code.
"""
import ast
import hashlib
import inspect
from pathlib import Path

from sqlalchemy import create_engine, delete, insert, select

from base import BaseGenerator
from shared.database import schema

HERE = Path(__file__).resolve().parent

# Files a generator's rules come from besides its own module.
SHARED_RULES = {
    'net_change_summary': ('summary_generators/payer_movements.py',),
    'monthly_adt_summary': ('summary_generators/payer_movements.py',),
    # PDPM pricing: the per diem from each code, shared with the API.
    'census_logs': ('../shared/pdpm.py',),
    # Stable SQL draws, shared by the clinical event generators.
    'incident_logs': ('source_data_generators/draws.py',),
    'infection_logs': ('source_data_generators/draws.py',),
    'weight_logs': ('source_data_generators/draws.py',),
    'progress_notes': ('source_data_generators/draws.py',),
}
# Reference data rebuilt from its rules alone, as `<name> --regenerate` does.
REFERENCE = ('payer_rates', 'facility_beds', 'referring_hospitals')
# Rebuilt from saved stays alone, as `<name> --regenerate` does. The ADT
# simulation reads their rules too, but they are pure outputs: nothing reads
# them back, so regenerating them reproduces what the simulation would write.
STANDALONE = ('admission_logs', 'discharge_logs')
# Change any of these and only seed --reset-history can apply it.
RESET_ONLY = ('states', 'portfolios', 'regions', 'facilities', 'payers', 'residents', 'res_stays')
# Not data rules: the admin user's password comes from the environment.
IGNORED = ('admin_user',)


def _file_fingerprint(path: Path) -> str:
    """Hash of the parsed code without docstrings: comments and formatting do
    not count, a changed rule or constant does."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        body = getattr(node, 'body', None)
        if (isinstance(body, list) and body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str)):
            node.body = body[1:] or [ast.Pass()]
    return hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()


def _generators():
    """Every generator by name, the classes RUN_ORDER covers."""
    return {generator.name: generator for generator in BaseGenerator.execution_plan('all')}


def fingerprints() -> dict[str, str]:
    """The current code's fingerprint for every generator."""
    result = {}
    for name, generator in _generators().items():
        if name in IGNORED:
            continue
        files = [Path(inspect.getsourcefile(generator)), *(HERE / extra for extra in SHARED_RULES.get(name, ()))]
        digest = hashlib.sha256()
        for path in files:
            digest.update(_file_fingerprint(path).encode())
        result[name] = digest.hexdigest()
    return result


def _downstream(names: set[str]) -> set[str]:
    """names and everything built from them, through declared dependencies."""
    children = {}
    for name, generator in _generators().items():
        for parent in generator.depends_on:
            children.setdefault(parent, set()).add(name)
    result, pending = set(), list(names)
    while pending:
        name = pending.pop()
        if name not in result:
            result.add(name)
            pending.extend(children.get(name, ()))
    return result


def changes(database_url: str) -> tuple[set[str], list[str], dict[str, str]]:
    """What the running code needs rebuilt: (generators to rebuild, generators
    whose change needs seed --reset-history, current fingerprints)."""
    current = fingerprints()
    engine = create_engine(BaseGenerator.postgres_url(database_url))
    try:
        with engine.connect() as connection:
            saved = dict(connection.execute(select(schema.rule_history.c.name,
                schema.rule_history.c.fingerprint)).all())
    finally:
        engine.dispose()
    if not saved:
        return set(), [], current
    # A generator with no saved fingerprint is new: daily handlers backfill
    # their missing days anyway, so there is nothing to rebuild.
    changed = {name for name, fingerprint in current.items() if name in saved and saved[name] != fingerprint}
    reset_needed = sorted(changed & set(RESET_ONLY))
    rebuild = _downstream(changed - set(RESET_ONLY)) - set(RESET_ONLY)
    return rebuild, reset_needed, current


def record(database_url: str, current: dict[str, str], skip=()):
    """Save the fingerprints the data now matches. skip keeps the old one --
    for a reset-only change not yet applied -- so it is reported again."""
    rows = [dict(name=name, fingerprint=fingerprint) for name, fingerprint in current.items() if name not in skip]
    engine = create_engine(BaseGenerator.postgres_url(database_url))
    try:
        with engine.begin() as connection:
            connection.execute(delete(schema.rule_history).where(
                schema.rule_history.c.name.in_([row['name'] for row in rows])))
            if rows:
                connection.execute(insert(schema.rule_history), rows)
    finally:
        engine.dispose()
