"""Source data, run order and PostgreSQL persistence using the shared schema.

Generators declare a table and produce rows. This class owns connections,
transactions, source validation, ordering and repeatable upserts.
Importing this module never opens a database connection.
"""
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping, Sized
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from hashlib import sha1, sha256
from importlib import import_module
import json
from math import isfinite
from pathlib import Path
from random import Random
from operator import itemgetter
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

from psycopg import sql
from psycopg.types.json import Json, Jsonb

from sqlalchemy import (
    JSON, Table, create_engine, func, inspect, select,
)
from sqlalchemy.engine import Connection
from sqlalchemy.dialects.postgresql import JSONB
from shared.database import schema
from shared.database.console import RunProgress
from shared.database.lifecycle import ensure_compatible, postgres_url, seed_guard

COPY_BATCH_SIZE = 20000


@dataclass(frozen=True)
class GenerationResult:
    generated: int
    changed: int


class BaseGenerator(ABC):
    name: str
    table: Table
    related_tables = ()
    depends_on = ()
    transaction_isolation = None
    SIMULATION_START = date(2023, 1, 1)
    SIMULATION_TIMEZONE = 'America/New_York'
    SKILLED_PAYER_TYPES = frozenset(('medicare', 'medicare_hmo', 'medicare_comm', 'va'))
    facilities_path = Path(__file__).resolve().parent / 'hard_coded_data' / 'facilities.json'
    payers_path = Path(__file__).resolve().parent / 'hard_coded_data' / 'payers.json'
    hospitals_path = Path(__file__).resolve().parent / 'hard_coded_data' / 'hospitals.json'
    # Each module exports a GENERATORS tuple containing one or more classes.
    GENERATOR_MODULES = (
        'source_data_generators.aspire-facilities',
        'source_data_generators.aspire-residents',
        'source_data_generators.aspire-payers',
        'source_data_generators.aspire-res-stays',
        'source_data_generators.aspire-admission-logs',
        'source_data_generators.aspire-discharge-logs',
        'source_data_generators.aspire-payer-change-logs',
        'summary_generators.aspire-admissions',
        'summary_generators.aspire-discharges',
        'summary_generators.aspire-payer-changes',
        'summary_generators.aspire-net-change',
        'summary_generators.aspire-monthly-adt',
    )
    RUN_ORDER = ('states', 'portfolios', 'regions', 'facilities', 'payers', 'residents',
        'res_stays', 'admission_logs', 'discharge_logs', 'payer_change_logs',
        'admissions_summary',
        'discharges_summary', 'payer_changes_summary', 'net_change_summary',
        'monthly_adt_summary')
    metadata = schema.metadata
    migration_history = schema.migration_history
    run_history = schema.run_history
    states = schema.states
    portfolios = schema.portfolios
    regions = schema.regions
    facilities = schema.facilities
    residents = schema.residents
    payers = schema.payers
    res_stays = schema.res_stays
    res_payer_stays = schema.res_payer_stays
    admission_logs = schema.admission_logs
    medicaid_applications = schema.medicaid_applications
    discharge_logs = schema.discharge_logs
    daily_runs = schema.daily_runs
    adt_resident_state = schema.adt_resident_state
    adt_active_stays = schema.adt_active_stays
    adt_daily_census = schema.adt_daily_census

    @classmethod
    def today(cls):
        return datetime.now(ZoneInfo(cls.SIMULATION_TIMEZONE)).date()

    @classmethod
    def daily_plan(cls, target='all'):
        """Discover daily handlers alongside existing generators; order by dependencies."""
        registered = {}
        for module_name in cls.GENERATOR_MODULES:
            for generator in getattr(import_module(module_name), 'DAILY_GENERATORS', ()):
                if generator.name in registered:
                    raise ValueError(f'Duplicate daily generator: {generator.name}.')
                registered[generator.name] = generator
        ordered, visiting, done = [], set(), set()

        def include(name):
            if name in done:
                return
            if name in visiting:
                raise ValueError(f'Circular daily dependency: {name}.')
            if name not in registered:
                raise ValueError(f'Unknown daily generator: {name}.')
            visiting.add(name)
            for parent in registered[name].depends_on:
                include(parent)
            visiting.remove(name)
            done.add(name)
            ordered.append(registered[name])

        for name in registered if target == 'all' else (target,):
            include(name)
        return tuple(ordered)

    @classmethod
    def run_days(cls, database_url, *, through=None, start=None, target='all', reset_history=False,
            refresh=False):
        """Resume missing work in dependency order; data and its markers commit together.

        Handlers use run_day(connection, day), depend only on saved data, and must
        write only their owned tables. A newly registered handler can backfill
        historical days without re-running completed dependencies. Stateful handlers
        declare sequential=True and cannot be inserted into the middle of their history.
        """
        through = through or cls.today()
        start = start or cls.SIMULATION_START
        if through > cls.today() or start < cls.SIMULATION_START or start > through:
            raise ValueError('Choose consecutive dates from 2023-01-01 through today; future simulation is disabled.')
        plan = cls.daily_plan(target)
        if refresh and (target == 'all' or any(handler.name == target and handler.sequential for handler in plan)):
            raise ValueError('Completed ADT days cannot be regenerated. Use seed --reset-history for a full rebuild.')
        if reset_history and (target != 'all' or start != cls.SIMULATION_START):
            raise ValueError('--reset-history requires seed from 2023-01-01 with all daily handlers.')
        engine = create_engine(cls.postgres_url(database_url))
        try:
            with engine.connect() as connection, seed_guard(connection), RunProgress(plan[-1].table.fullname) as progress:
                # One session lock covers all day transactions and is released on errors too.
                connection.exec_driver_sql('SELECT pg_advisory_lock(1935766388, 1)')
                connection.commit()
                try:
                    handlers = [generator(database_url) for generator in plan]
                    for handler in handlers:
                        handler.progress = progress
                    with connection.begin():
                        for handler in handlers:
                            for table in handler.owned_tables:
                                handler.show_table_progress(table)
                                handler.prepare_table(connection, table)
                        if reset_history:
                            # One TRUNCATE, no CASCADE. Without CASCADE PostgreSQL refuses
                            # when a table outside this list references one inside it, which
                            # is the same guard the previous per-table DELETE relied on, so
                            # unknown future references still prevent a partial reset.
                            # DELETE rewrote every row and index entry, fired per-row foreign
                            # key checks, and left the dead rows for autovacuum; TRUNCATE
                            # swaps in an empty file per table and reclaims the space now.
                            cleared, targets = set(), []
                            for handler in reversed(handlers):
                                for table in getattr(handler, 'reset_tables', tuple(reversed(handler.owned_tables))):
                                    if table.name not in cleared and inspect(connection).has_table(table.name):
                                        cleared.add(table.name)
                                        targets.append(table)
                            if targets:
                                progress.set_phase('Reset generated ADT history',
                                    details=', '.join(table.name for table in targets))
                                connection.exec_driver_sql(sql.SQL('TRUNCATE {}').format(
                                    sql.SQL(', ').join(sql.Identifier(table.name) for table in targets)
                                ).as_string(connection.connection.driver_connection))
                            connection.execute(cls.daily_runs.delete())
                            connection.execute(cls.run_history.delete().where(cls.run_history.c.name.in_(
                                ('res_stays', 'admission_logs', 'discharge_logs', 'admissions_summary'))))
                        records = connection.execute(select(cls.daily_runs.c.generator,
                            cls.daily_runs.c.simulation_date)).all()
                        completed = {}
                        for name, day in records:
                            completed.setdefault(name, set()).add(day)
                        if any(handler.name == 'adt' for handler in handlers) and not completed.get('adt') and connection.scalar(
                                select(cls.res_stays.c.stay_id).limit(1)) is not None:
                            raise ValueError('Existing ADT history uses the old generator. Run '
                                'python manage.py seed --reset-history to replace generated stays, logs, '
                                'and summaries. Facilities, payers, and residents are retained.')
                        for handler in handlers:
                            if handler.sequential:
                                history = completed.get(handler.name, set())
                                latest = max(history) if history else cls.SIMULATION_START - timedelta(days=1)
                                if history and len(history) != (latest - cls.SIMULATION_START).days + 1:
                                    raise ValueError(f'{handler.name} has a gap in its committed history; cannot replay past events.')
                                if start > latest + timedelta(days=1):
                                    raise ValueError(f'{handler.name} must resume on {latest + timedelta(days=1)}; '
                                        'omit --from to catch up automatically.')
                    updated_days = set()
                    updated_tables = []
                    requested_days = [start + timedelta(days=offset)
                        for offset in range((through - start).days + 1)]
                    # Finish each dependency before its consumers. Stateful handlers
                    # still commit one day at a time; derived reports can batch all
                    # missing dates without thousands of queries and transactions.
                    for handler in handlers:
                        days = [day for day in requested_days
                            if (refresh and handler.name == target)
                            or day not in completed.get(handler.name, set())]
                        if not days:
                            continue
                        updated_tables.extend(table.fullname for table in handler.owned_tables)
                        for parent in handler.depends_on:
                            missing = set(days) - completed.get(parent, set())
                            if missing:
                                raise ValueError(f'{handler.name} requires {parent} completed on {min(missing)}.')
                        handler.show_table_progress(handler.table)
                        progress.set_phase('Building', total=len(days), unit='days')
                        if handler.bulk_dates:
                            with connection.begin():
                                connection.exec_driver_sql('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                                handler.prepare_daily(connection)
                                counts_by_day = handler.run_dates(connection, days)
                                if set(counts_by_day) != set(days):
                                    raise ValueError(f'{handler.name} returned incomplete date coverage.')
                                handler.show_table_progress(cls.daily_runs)
                                progress.set_phase('Record checkpoints', details=f'{len(days):,} dates')
                                connection.execute(cls.daily_runs.delete().where(
                                    cls.daily_runs.c.generator == handler.name,
                                    cls.daily_runs.c.simulation_date.in_(days)))
                                connection.execute(cls.daily_runs.insert(), [dict(
                                    generator=handler.name, simulation_date=day,
                                    row_counts=counts_by_day[day]) for day in days])
                                handler.show_table_progress(handler.table)
                                progress.set_phase('Commit', details=f'{len(days):,} days and checkpoints')
                            completed.setdefault(handler.name, set()).update(days)
                            updated_days.update(days)
                        else:
                            # Stateful handlers still simulate strictly in order, but a
                            # handler may buffer several days and write them together.
                            # Per-day writes are dominated by fixed statement cost, not
                            # row volume, so batching is most of the win. A failed batch
                            # commits nothing and resumes from its own first day.
                            size = max(1, handler.batch_days)
                            for offset in range(0, len(days), size):
                                batch = days[offset:offset + size]
                                with connection.begin():
                                    handler.show_table_progress(handler.table)
                                    if offset == 0:
                                        handler.prepare_daily(connection)
                                    counts_by_day = {}
                                    for day in batch:
                                        progress.describe(str(day))
                                        counts_by_day[day] = handler.run_day(connection, day)
                                        # Advance per simulated day so the ETA stays smooth
                                        # instead of stepping once per committed batch.
                                        progress.advance(1)
                                    handler.flush_writes(connection)
                                    if refresh and handler.name == target:
                                        connection.execute(cls.daily_runs.delete().where(
                                            cls.daily_runs.c.generator == handler.name,
                                            cls.daily_runs.c.simulation_date.in_(batch)))
                                    connection.execute(cls.daily_runs.insert(), [dict(
                                        generator=handler.name, simulation_date=day,
                                        row_counts=counts_by_day[day]) for day in batch])
                                completed.setdefault(handler.name, set()).update(batch)
                                updated_days.update(batch)
                                progress.describe(f'{batch[-1]} committed')
                    with progress.lock:
                        progress.name = ', '.join(dict.fromkeys(updated_tables)) or plan[-1].table.fullname
                    progress.set_phase('Complete', details=f'{len(updated_days):,} days updated through {through}')
                finally:
                    if connection.in_transaction():
                        connection.rollback()
                    connection.exec_driver_sql('SELECT pg_advisory_unlock(1935766388, 1)')
                    connection.commit()
        finally:
            engine.dispose()

    def __init__(self, database_url: str):
        self.database_url = self.postgres_url(database_url)
        self.progress = None
        self._resident_plans = {}
        self._stage_number = 0

    def prepare_sources(self, connection: Connection):
        """Load saved parent records once before generate(), using this run's transaction.

        Override in child generators. Never reconstruct another generator's keys.
        """

    @staticmethod
    def read_rows(connection: Connection, statement):
        """Read selected parent columns in bulk, outside the COPY/generation loop."""
        return connection.execute(statement).mappings().all()

    @staticmethod
    def parent_key(index, key, table_name):
        """Resolve a source label to an existing parent key with a useful error."""
        if key not in index:
            raise ValueError(f'Missing parent in {table_name}: {key!r}. '
                'Add the parent record before running this generator.')
        return index[key]

    postgres_url = staticmethod(postgres_url)

    @classmethod
    def execution_plan(cls, target):
        """Load all classes exported by each file, then apply the parent-first order."""
        generators = {}
        for module_name in cls.GENERATOR_MODULES:
            # import_module also supports filenames containing a hyphen.
            module = import_module(module_name)
            for generator in module.GENERATORS:
                if generator.name in generators:
                    raise ValueError(f'Duplicate generator name: {generator.name}.')
                generators[generator.name] = generator
        if set(cls.RUN_ORDER) != set(generators):
            raise ValueError('RUN_ORDER must include every registered generator.')
        if target != 'all' and target not in generators:
            raise ValueError(f'Unknown generator: {target}.')
        by_table = {table.fullname: name for name, generator in generators.items()
            for table in (generator.table, *generator.related_tables)}
        required = set()

        def include(name):
            if name in required:
                return
            required.add(name)
            generator = generators[name]
            # Summaries depend on source generators even without a per-record FK.
            for parent in generator.depends_on:
                if parent not in generators:
                    raise ValueError(f'Unknown dependency {parent} for {name}.')
                if cls.RUN_ORDER.index(parent) >= cls.RUN_ORDER.index(name):
                    raise ValueError(f'RUN_ORDER must place {parent} before {name}.')
                include(parent)
            for table in (generator.table, *generator.related_tables):
                for foreign_key in table.foreign_keys:
                    parent = by_table.get(foreign_key.column.table.fullname)
                    if parent is None:
                        raise ValueError(f'No generator registered for parent table {foreign_key.column.table.fullname}.')
                    if parent == name:
                        continue
                    if cls.RUN_ORDER.index(parent) >= cls.RUN_ORDER.index(name):
                        raise ValueError(f'RUN_ORDER must place {parent} before {name}.')
                    include(parent)

        for name in cls.RUN_ORDER if target == 'all' else (target,):
            include(name)
        return tuple(generators[name] for name in cls.RUN_ORDER if name in required)

    @staticmethod
    def source_id(kind, *parts):
        """Keys stay the same when source rows are reordered or added."""
        return uuid5(NAMESPACE_URL, json.dumps(['sandbox-data', kind, *parts], ensure_ascii=False))

    @staticmethod
    @lru_cache(maxsize=8192)
    def _mix_factors(seed, kind, scope, period, labels, spread):
        rng = Random(BaseGenerator.source_id('demo-mix-v1', seed, kind, scope, period).int)
        # Bounded multipliers keep small categories possible without letting an
        # extreme draw dominate. These are synthetic preferences, not quotas.
        return tuple(min(3.0, max(0.3, rng.lognormvariate(0, spread))) for _ in labels)

    @staticmethod
    @lru_cache(maxsize=4096)
    def varied_mix(seed, kind, facility_id, day, baseline):
        """Repeatable facility preferences plus shared monthly/daily variation.

        Shared time effects prevent variation from disappearing when hundreds of
        facilities are combined. Bounded caches avoid per-resident profile work
        and keep memory independent of the length of the seeded history.
        """
        labels = tuple(label for label, _ in baseline)
        month = day.strftime('%Y-%m')
        layers = (
            ('all', month, .25),
            (str(facility_id), 'baseline', .55),
            (str(facility_id), month, .25),
            ('all', day.isoformat(), .12),
        )
        weights = [weight for _, weight in baseline]
        for scope, period, spread in layers:
            factors = BaseGenerator._mix_factors(seed, kind, scope, period, labels, spread)
            weights = [weight * factor for weight, factor in zip(weights, factors)]
        return tuple(zip(labels, weights))

    @staticmethod
    def numbered_ids(kind, *parts):
        """Reuse a UUID5 hash prefix, preserving source_id(kind, *parts, integer)."""
        prefix = json.dumps(['sandbox-data', kind, *parts], ensure_ascii=False)[:-1] + ', '
        prepared = sha1(NAMESPACE_URL.bytes + prefix.encode('utf-8'))

        def identity(number):
            digest = prepared.copy()
            digest.update((str(number) + ']').encode('ascii'))
            return UUID(bytes=digest.digest()[:16], version=5)

        return identity

    def load_payers(self):
        """Flatten category-to-name lists, validating the full source before writes."""
        source = json.loads(self.payers_path.read_text(encoding='utf-8-sig'))
        if not isinstance(source, dict) or not source:
            raise ValueError('payers.json must contain a nonempty object of payer categories.')
        rows, categories = [], set()
        for category, names in source.items():
            payer_type = category.strip()
            if not payer_type:
                raise ValueError('Each payer category must have a nonempty name.')
            if payer_type.casefold() in categories:
                raise ValueError(f'Duplicate payer category: {payer_type}.')
            categories.add(payer_type.casefold())
            if not isinstance(names, list) or not names:
                raise ValueError(f'Payer category {payer_type} must contain a nonempty list of names.')
            seen = set()
            for position, name in enumerate(names, start=1):
                if not isinstance(name, str) or not name.strip():
                    raise ValueError(f'Payer {position} in {payer_type} needs a nonempty name.')
                payer_name = name.strip()
                if payer_name.casefold() in seen:
                    raise ValueError(f'Duplicate payer in {payer_type}: {payer_name}.')
                seen.add(payer_name.casefold())
                rows.append(dict(payer_type=payer_type, payer_name=payer_name))
        return sorted(rows, key=lambda row: (row['payer_type'], row['payer_name']))

    def load_hospitals(self):
        """Validate the regional hospital names and relative referral weights."""
        source = json.loads(self.hospitals_path.read_text(encoding='utf-8-sig'))
        if not isinstance(source, dict) or not source:
            raise ValueError('hospitals.json must contain a nonempty object of regional hospital lists.')
        regions = {}
        for region, hospitals in source.items():
            if not region.strip() or not isinstance(hospitals, list) or not hospitals:
                raise ValueError('Each hospital region needs a name and a nonempty hospital list.')
            region = region.strip()
            if region in regions:
                raise ValueError(f'Duplicate hospital region: {region}.')
            rows, seen = [], set()
            for row in hospitals:
                if not isinstance(row, dict):
                    raise ValueError(f'Hospital entries for {region} must be objects.')
                name, score = row.get('hospital'), row.get('score')
                if not isinstance(name, str) or not name.strip():
                    raise ValueError(f'A hospital in {region} is missing its name.')
                name = name.strip()
                if name.casefold() in seen:
                    raise ValueError(f'Duplicate hospital in {region}: {name}.')
                if type(score) not in (int, float) or not isfinite(score) or score < 0:
                    raise ValueError(f'Hospital {name} needs a finite nonnegative score.')
                seen.add(name.casefold())
                rows.append(dict(hospital=name, score=score))
            if not any(row['score'] > 0 for row in rows):
                raise ValueError(f'Hospital scores for {region} must have a positive total.')
            regions[region] = sorted(rows, key=lambda row: row['hospital'])
        return regions

    @staticmethod
    def load_name_list(path):
        """Read one name per line, preserving spelling and ignoring blank/duplicate lines."""
        names = {}
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            name = line.strip()
            if name:
                names.setdefault(name.casefold(), name)
        if not names:
            raise ValueError(f'{path.name} must contain at least one name.')
        return tuple(names.values())

    def random_names(self, count, *, seed=42):
        """Stream unique name pairs with a 50/50 gender draw for each resident.

        Lists are loaded once per call. A fixed seed and unchanged lists reproduce
        the same names. Sampling is uniform within each list; no model is used.
        """
        if type(count) is not int or count < 0:
            raise ValueError('Name count must be a nonnegative integer.')
        if count == 0:
            return
        data_path = self.facilities_path.parent
        male = self.load_name_list(data_path / 'male_first_names.txt')
        female = self.load_name_list(data_path / 'female_first_names.txt')
        surnames = self.load_name_list(data_path / 'last_names.txt')
        # Reserve enough combinations even if every gender draw selects one list.
        # This also prevents an exhausted list from causing an endless retry loop.
        if count > min(len(male), len(female)) * len(surnames):
            raise ValueError('Name lists are too small to guarantee unique names for this resident count.')
        # Normalize comparison keys once, rather than allocating strings per resident.
        male = tuple((name, name.casefold()) for name in male)
        female = tuple((name, name.casefold()) for name in female)
        surnames = tuple((name, name.casefold()) for name in surnames)
        rng = Random(seed)
        used = set()
        for _ in range(count):
            is_male = bool(rng.getrandbits(1))
            first_names = male if is_male else female
            while True:
                first_name, first_key = rng.choice(first_names)
                last_name, last_key = rng.choice(surnames)
                key = (first_key, last_key)
                if key not in used:
                    used.add(key)
                    break
            yield dict(gender='male' if is_male else 'female',
                first_name=first_name, last_name=last_name)

    def load_facilities(self):
        """Read and validate the shared source before producing any rows."""
        facilities = json.loads(self.facilities_path.read_text(encoding='utf-8-sig'))
        if not isinstance(facilities, list) or not facilities:
            raise ValueError('facilities.json must contain a nonempty list of facilities.')
        rows, seen = [], set()
        for position, facility in enumerate(facilities, start=1):
            if not isinstance(facility, dict):
                raise ValueError(f'Facility row {position} must be an object.')
            for field in ('state', 'portfolio', 'market', 'facility'):
                if not isinstance(facility.get(field), str) or not facility[field].strip():
                    raise ValueError(f'Facility row {position} needs a nonempty {field}.')
            row = {field: facility[field].strip()
                for field in ('state', 'portfolio', 'market', 'facility')}
            state = row['state']
            if len(state) != 2 or not state.isascii() or not state.isalpha() or state != state.upper():
                raise ValueError(f'Facility row {position} needs a two-letter uppercase state code.')
            beds = facility.get('beds')
            if type(beds) is not int or beds < 0:
                raise ValueError(f'Facility row {position} needs a nonnegative integer beds value.')
            key = tuple(row.values())
            if key in seen:
                raise ValueError(f'Duplicate facility row {position}; counts were not saved.')
            seen.add(key)
            row['beds'] = beds
            rows.append(row)
        return sorted(rows, key=lambda row: tuple(row[field]
            for field in ('state', 'portfolio', 'market', 'facility')))

    def resident_facilities(self, *, seed=42, minimum=8, maximum=14):
        """Plan new residents using facility IDs and bed counts loaded from the DB."""
        cache_key = (seed, minimum, maximum)
        if cache_key in self._resident_plans:
            return self._resident_plans[cache_key]
        rows = []
        for facility in self._facility_rows:
            facility_id = facility['facility_id']
            rng = Random(self.source_id('resident-count', seed, str(facility_id)).int)
            rows.append(dict(facility_id=facility_id, beds=facility['beds'],
                resident_count=facility['beds'] * rng.randint(minimum, maximum)))
        self._resident_plans[cache_key] = rows
        return rows

    @abstractmethod
    def generate(self) -> Iterable[Mapping]:
        """Produce rows from sources loaded by prepare_sources; no per-row DB calls."""

    def validate_table(self, connection: Connection, table=None) -> None:
        table = self.table if table is None else table
        inspector = inspect(connection)
        columns = {column['name'] for column in inspector.get_columns(
            table.name, schema=table.schema)}
        missing = set(table.c.keys()) - columns
        primary_key = inspector.get_pk_constraint(table.name, schema=table.schema)
        expected_key = {column.name for column in table.primary_key}
        if missing or set(primary_key['constrained_columns']) != expected_key:
            raise ValueError(f'Existing table {table.name} has an incompatible structure. '
                'Use the intended sandbox database or apply an explicit schema change; no table was replaced.')

    def prepare_table(self, connection: Connection, table=None) -> None:
        table = self.table if table is None else table
        self.validate_table(connection, table)

    def expected_rows(self):
        """An exact count when cheaply available; never generate a large stream twice."""
        return None

    def existing_counts(self, connection):
        inspector = inspect(connection)
        counts = {}
        for table in (self.table, *self.related_tables):
            if not inspector.has_table(table.name, schema=table.schema):
                return None
            self.validate_table(connection, table)
            counts[table.name] = connection.scalar(select(func.count()).select_from(table))
        return counts

    def can_reuse(self, connection, counts):
        """Recognize completed runs, including data created before run tracking existed."""
        if counts is None:
            return False
        recorded = connection.scalar(select(self.run_history.c.row_counts)
            .where(self.run_history.c.name == self.name))
        # Saved data is authoritative, including manually added/edited records.
        # Source-file sizes must not cause existing parents to be regenerated.
        return counts == recorded or all(count > 0 for count in counts.values())

    def record_completion(self, connection, counts):
        # This marker commits in the same transaction as the generated data.
        connection.execute(self.run_history.delete().where(self.run_history.c.name == self.name))
        connection.execute(self.run_history.insert().values(name=self.name, row_counts=counts))

    @staticmethod
    def _table_identifier(table):
        return sql.Identifier(table.schema, table.name) if table.schema else sql.Identifier(table.name)

    def show_table_progress(self, table):
        """Keep the actual destination table visible at the start of the CLI line."""
        if self.progress is not None:
            with self.progress.lock:
                self.progress.name = table.fullname

    def create_stage(self, connection, table):
        self.show_table_progress(table)
        self._stage_number += 1
        stage = f'_sandbox_{table.name}_{self._stage_number}'
        driver = connection.connection.driver_connection
        statement = sql.SQL('CREATE TEMP TABLE {} (LIKE {}) ON COMMIT DROP').format(
            sql.Identifier(stage), self._table_identifier(table))
        connection.exec_driver_sql(statement.as_string(driver))
        return stage

    def copy_rows(self, connection, table, stage, rows, progress=None):
        """Stream adapted values through COPY without building per-row SQL parameters."""
        self.show_table_progress(table)
        columns = tuple(table.c.keys())
        expected = frozenset(columns)
        values = itemgetter(*columns) if len(columns) > 1 else lambda row: (row[columns[0]],)
        json_columns = tuple((index, Jsonb if isinstance(column.type, JSONB) else Json)
            for index, column in enumerate(table.c) if isinstance(column.type, JSON))
        statement = sql.SQL('COPY {} ({}) FROM STDIN').format(sql.Identifier(stage),
            sql.SQL(', ').join(map(sql.Identifier, columns)))
        count, reported = 0, 0
        driver = connection.connection.driver_connection
        with driver.cursor() as cursor:
            with cursor.copy(statement) as copy:
                for row in rows:
                    if row.keys() != expected:
                        raise ValueError(f'{table.name} must supply exactly the declared table columns.')
                    adapted = values(row)
                    if json_columns:
                        adapted = list(adapted)
                        for index, wrapper in json_columns:
                            if adapted[index] is not None:
                                adapted[index] = wrapper(adapted[index])
                    copy.write_row(adapted)
                    count += 1
                    if progress is not None and count - reported >= 2048:
                        progress.advance(count - reported)
                        reported = count
        if progress is not None:
            progress.advance(count - reported)
        return count

    def merge_stage(self, connection, table, stage):
        """Merge once per table; filter unchanged rows before conflict checks and locks."""
        self.show_table_progress(table)
        columns = tuple(table.c.keys())
        keys = tuple(column.name for column in table.primary_key)
        if not keys:
            raise ValueError(f'{table.name} must declare a stable primary key.')
        fields = tuple(name for name in columns if name not in keys)
        driver = connection.connection.driver_connection
        column_list = sql.SQL(', ').join(map(sql.Identifier, columns))
        source_list = sql.SQL(', ').join(sql.Identifier('s', name) for name in columns)
        # A fresh build writes into an empty table: nothing can conflict and nothing
        # can be unchanged, so the anti-join, the row comparisons and ON CONFLICT are
        # all overhead. Probing for a single row is far cheaper than any of them.
        if connection.exec_driver_sql(sql.SQL('SELECT 1 FROM {} LIMIT 1').format(
                self._table_identifier(table)).as_string(driver)).first() is None:
            statement = sql.SQL('INSERT INTO {} ({}) SELECT {} FROM {}').format(
                self._table_identifier(table), column_list, column_list, sql.Identifier(stage))
            changed = connection.exec_driver_sql(statement.as_string(driver)).rowcount
            connection.exec_driver_sql(sql.SQL('DROP TABLE {}').format(sql.Identifier(stage)).as_string(driver))
            return changed
        connection.exec_driver_sql(sql.SQL('ANALYZE {}').format(sql.Identifier(stage)).as_string(driver))
        join = sql.SQL(' AND ').join(sql.SQL('{} = {}').format(
            sql.Identifier('s', key), sql.Identifier('t', key)) for key in keys)
        missing = sql.SQL('{} IS NULL').format(sql.Identifier('t', keys[0]))
        conflict = sql.SQL('ON CONFLICT ({}) DO NOTHING').format(sql.SQL(', ').join(map(sql.Identifier, keys)))
        if fields:
            def different(left, right):
                return sql.SQL('ROW({}) IS DISTINCT FROM ROW({})').format(
                    sql.SQL(', ').join(sql.Identifier(left, name) for name in fields),
                    sql.SQL(', ').join(sql.Identifier(right, name) for name in fields))
            missing = sql.SQL('({} OR {})').format(missing, different('t', 's'))
            assignments = sql.SQL(', ').join(sql.SQL('{} = {}').format(
                sql.Identifier(name), sql.Identifier('excluded', name)) for name in fields)
            conflict = sql.SQL('ON CONFLICT ({}) DO UPDATE SET {} WHERE {}').format(
                sql.SQL(', ').join(map(sql.Identifier, keys)), assignments, different('destination', 'excluded'))
        statement = sql.SQL(
            'INSERT INTO {} AS destination ({}) SELECT {} FROM {} AS s '
            'LEFT JOIN {} AS t ON {} WHERE {} {}').format(
                self._table_identifier(table), column_list, source_list, sql.Identifier(stage),
                self._table_identifier(table), join, missing, conflict)
        changed = connection.exec_driver_sql(statement.as_string(driver)).rowcount
        connection.exec_driver_sql(sql.SQL('DROP TABLE {}').format(sql.Identifier(stage)).as_string(driver))
        return changed

    def suspend_indexes(self, connection, table):
        """Drop a table's keys and indexes so a bulk replace rebuilds them once.

        Maintaining a multi-column primary key and foreign keys per inserted row
        costs far more than building them once over the finished table. Definitions
        are read from the catalog and replayed verbatim, so names and shapes are
        unchanged and schema-drift checks still pass. CHECK constraints stay: they
        are row-local and cheap. Everything runs in the caller's transaction, so a
        failure leaves the table exactly as it was.

        Only safe for a table nothing else references; dropping a primary key that
        another table's foreign key depends on will fail.
        """
        driver = connection.connection.driver_connection
        constraints = connection.exec_driver_sql(
            'SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint '
            "WHERE conrelid = %(name)s::regclass AND contype IN ('p', 'f', 'u')",
            dict(name=table.name)).all()
        indexes = connection.exec_driver_sql(
            'SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = current_schema() '
            'AND tablename = %(name)s AND indexname NOT IN (SELECT conname FROM pg_constraint '
            "WHERE conrelid = %(name)s::regclass AND contype IN ('p', 'u'))",
            dict(name=table.name)).all()
        for index_name, _ in indexes:
            connection.exec_driver_sql(sql.SQL('DROP INDEX {}').format(
                sql.Identifier(index_name)).as_string(driver))
        for constraint_name, _ in constraints:
            connection.exec_driver_sql(sql.SQL('ALTER TABLE {} DROP CONSTRAINT {}').format(
                sql.Identifier(table.name), sql.Identifier(constraint_name)).as_string(driver))
        return tuple(constraints), tuple(indexes)

    def restore_indexes(self, connection, table, suspended):
        """Recreate exactly what suspend_indexes removed, from its saved definitions."""
        constraints, indexes = suspended
        driver = connection.connection.driver_connection
        for constraint_name, definition in constraints:
            prefix = sql.SQL('ALTER TABLE {} ADD CONSTRAINT {} ').format(
                sql.Identifier(table.name), sql.Identifier(constraint_name)).as_string(driver)
            connection.exec_driver_sql(prefix + definition)
        for _, definition in indexes:
            connection.exec_driver_sql(definition)

    def replaces_most_rows(self, connection, table, incoming):
        """True when a write replaces enough of a table to justify rebuilding keys."""
        estimate = connection.exec_driver_sql(
            'SELECT COALESCE(reltuples, 0)::bigint FROM pg_class WHERE oid = %(name)s::regclass',
            dict(name=table.name)).scalar() or 0
        return incoming >= max(estimate, 1) * 0.5

    def write_rows(self, connection: Connection, rows: Iterable[Mapping], table=None) -> GenerationResult:
        """COPY into temporary staging, followed by one set-based upsert."""
        table = self.table if table is None else table
        total = len(rows) if isinstance(rows, Sized) else self.expected_rows()
        if self.progress:
            self.progress.set_phase('Generate + COPY', total=total, details=table.name)
        stage = self.create_stage(connection, table)
        generated = self.copy_rows(connection, table, stage, rows, self.progress)
        if self.progress:
            self.progress.set_phase('Merge', details=f'{table.name}: {generated:,} staged rows; database working')
        changed = self.merge_stage(connection, table, stage)
        return GenerationResult(generated=generated, changed=changed)

    def write_generated(self, connection: Connection) -> GenerationResult:
        return self.write_rows(connection, self.generate())

    def run(self, *, regenerate=False) -> GenerationResult:
        engine_options = ({'isolation_level': self.transaction_isolation}
            if self.transaction_isolation else {})
        engine = create_engine(self.database_url, **engine_options)
        try:
            with RunProgress(self.table.fullname) as progress:
                self.progress = progress
                with engine.begin() as connection:
                    connection.exec_driver_sql('SELECT pg_advisory_xact_lock_shared(1935766390, 1)')
                    ensure_compatible(connection)
                    if regenerate and self.name == 'residents' and inspect(connection).has_table(self.daily_runs.name):
                        if connection.scalar(select(self.daily_runs.c.generator)
                                .where(self.daily_runs.c.generator == 'adt').limit(1)):
                            raise ValueError('Daily ADT now maintains the resident population; existing residents cannot be regenerated.')
                    # Serialize the same generator; unrelated generators may still run.
                    lock_key = int.from_bytes(sha256(self.name.encode()).digest()[:4], 'big', signed=True)
                    connection.exec_driver_sql('SELECT pg_advisory_xact_lock(1935766387, %s)', (lock_key,))
                    progress.set_phase('Check existing data')
                    counts = self.existing_counts(connection)
                    reused = not regenerate and self.can_reuse(connection, counts)
                    if reused:
                        self.record_completion(connection, counts)
                        result = GenerationResult(sum(counts.values()), 0)
                    else:
                        progress.set_phase('Prepare tables')
                        for table in (self.table, *self.related_tables):
                            self.show_table_progress(table)
                            self.prepare_table(connection, table)
                        self.show_table_progress(self.table)
                        progress.set_phase('Load database records')
                        self._resident_plans.clear()
                        self.prepare_sources(connection)
                        result = self.write_generated(connection)
                        progress.set_phase('Record completed run', details='Checking final row counts')
                        counts = self.existing_counts(connection)
                        self.record_completion(connection, counts)
                    progress.set_phase('Commit', details='Existing data retained' if reused else 'Both data and run status')
                if reused:
                    progress.set_phase('Skipped', details=f'{sum(counts.values()):,} existing rows')
                else:
                    progress.set_phase('Complete', details=f'{result.generated:,} rows, {result.changed:,} changed')
                return result
        finally:
            self.progress = None
            engine.dispose()


class DailyGenerator(BaseGenerator):
    """Date-based work in the existing generator files.

    Register the class in its file's DAILY_GENERATORS tuple. Declare depends_on,
    owned_tables, and sequential=True only when the next day needs mutable state.
    Set bulk_dates=True for derived data that can build all requested dates in
    run_dates. The runner completes dependencies first, then commits the bulk
    result and all its checkpoints together. It does not erase old checkpoints
    before a refreshed result succeeds.
    run_day must use the passed connection and saved data for its date; never open
    another transaction, commit independently, or rewrite another handler's tables.
    Nonsequential additions may backfill without re-running existing handlers.
    A custom reset_tables sequence may exclude retained reference/population data.

    Set batch_days above 1 to buffer several simulated days and write them in one
    batch. run_day must then leave its rows in memory and implement flush_writes,
    which the runner calls once per batch inside the same transaction as that
    batch's checkpoints. Simulation order is unchanged; only the write boundary
    moves, so a failed batch resumes from its own first day rather than the last
    committed one.
    """
    owned_tables = ()
    sequential = False
    bulk_dates = False
    batch_days = 1

    def flush_writes(self, connection):
        """Write rows buffered across the batch. Only needed when batch_days > 1."""

    def generate(self):
        raise ValueError('Use manage.py seed or update for daily generators.')

    def prepare_daily(self, connection):
        """Load reusable state once per command; restart reloads committed DB state."""

    def run_dates(self, connection, days):
        """Bulk handlers return date -> table counts; the runner commits checkpoints."""
        raise NotImplementedError('A bulk_dates handler must implement run_dates.')

    @abstractmethod
    def run_day(self, connection, day):
        """Write this date's owned records and return counts for its checkpoint."""

    def save_rows(self, connection, table, rows):
        if not rows:
            return 0
        stage = self.create_stage(connection, table)
        self.copy_rows(connection, table, stage, rows)
        return self.merge_stage(connection, table, stage)
