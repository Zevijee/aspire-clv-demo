"""Exercise the complete seeding lifecycle only inside a disposable private schema."""

from datetime import date, timedelta
from uuid import uuid4

import pytest
from app.admissions_reporting import cache, daily, sources, state
from app.database import get_engine
from app.seeding import admissions as admission_module
from app.seeding.admissions import admissions
from app.seeding.base import BaseSeeder, SeedResult, SeedWindow, coverage, datasets
from app.seeding.facilities import facilities
from app.seeding.runner import default_registry, run_seeders
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.schema import CreateSchema, DropSchema


@pytest.fixture
def isolated_seed_engine():
    owner = get_engine()
    schema = f"seed_test_{uuid4().hex}"
    with owner.begin() as connection:
        connection.execute(CreateSchema(schema))

    engine = None
    try:
        engine = create_engine(owner.url, connect_args={"options": f"-csearch_path={schema}"})
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT current_schema()")) == schema
            assert connection.scalar(text("SHOW search_path")) == schema
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        # This identifier was created above from a fixed prefix and UUID. Never clean
        # the user's default schema, and never use a schema supplied by configuration.
        assert schema.startswith("seed_test_") and len(schema) == 42
        with owner.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))


def day_rows(connection, day):
    return [
        dict(row)
        for row in connection.execute(
            select(admissions)
            .where(admissions.c.admission_date == day)
            .order_by(admissions.c.admission_id)
        ).mappings()
    ]


def database_snapshot(engine):
    """Capture source contents and publication metadata for rollback comparisons."""
    with engine.connect() as connection:
        source_snapshot = tuple(
            connection.execute(
                text("""
                    SELECT count(*), min(admission_date), max(admission_date),
                        md5(string_agg(md5(row_to_json(a)::text), '' ORDER BY admission_id))
                    FROM adt_admissions a
                """)
            ).one()
        )
        snapshot = {"admissions": source_snapshot}
        for name, table, ordering in (
            ("facilities", facilities, facilities.c.facility_code),
            ("datasets", datasets, datasets.c.name),
            ("coverage", coverage, coverage.c.seed_date),
            ("state", state, state.c.id),
            ("cache", cache, cache.c.cache_key),
        ):
            snapshot[name] = [
                dict(row)
                for row in connection.execute(select(table).order_by(ordering)).mappings()
            ]
        snapshot["daily"] = tuple(
            connection.execute(
                select(
                    func.count(),
                    func.sum(daily.c.total_admissions),
                    func.sum(daily.c.readmission_count),
                    func.sum(daily.c.readmission_within_30_days_count),
                )
            ).one()
        )
        snapshot["sources"] = tuple(
            connection.execute(select(func.count(), func.sum(sources.c.admission_count))).one()
        )
        return snapshot


def assert_current_reporting(engine, window):
    with engine.connect() as connection:
        total = connection.scalar(select(func.count()).select_from(admissions))
        publication = connection.execute(select(state).where(state.c.id == 1)).mappings().one()
        assert publication["ready"] is True
        assert publication["first_date"] == window.start_date
        assert publication["latest_date"] == window.end_date
        assert publication["admission_count"] == total
        assert connection.scalar(select(func.sum(daily.c.total_admissions))) == total
        assert connection.scalar(select(func.sum(sources.c.admission_count))) == total
        assert connection.scalar(select(func.count()).select_from(facilities)) == 253
        assert connection.scalar(
            select(func.count()).select_from(coverage).where(coverage.c.dataset == "admissions")
        ) == window.days
        return publication


def test_seed_bootstrap_noop_rollover_repair_and_rollback(isolated_seed_engine, monkeypatch):
    engine = isolated_seed_engine
    as_of = date(2026, 9, 11)
    window = SeedWindow.ending_on(as_of)

    initial_results = run_seeders(as_of=as_of, engine=engine)
    assert [result.name for result in initial_results] == [
        "facilities", "admissions", "discharges", "payer_changes",
    ]
    assert initial_results[0].row_count == 253
    assert initial_results[1].row_count > 0
    publication = assert_current_reporting(engine, window)

    # A valid repeat retains both its report revision and existing cached responses.
    with engine.begin() as connection:
        connection.execute(
            cache.insert().values(
                cache_key="seeding-integration-sentinel",
                revision=publication["revision"],
                payload={"sentinel": "retain on unchanged runs"},
            )
        )

    def unexpected_generation(*_args, **_kwargs):
        raise AssertionError("An unchanged run must not generate admissions")

    with monkeypatch.context() as patch:
        patch.setattr(admission_module, "build_daily_admissions", unexpected_generation)
        repeated_results = run_seeders(as_of=as_of, engine=engine)
    assert all(result.changed_rows == 0 for result in repeated_results)
    assert assert_current_reporting(engine, window) == publication
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(cache)) == 1
        overlap_day = as_of - timedelta(days=30)
        overlap = day_rows(connection, overlap_day)
        assert overlap
        assert day_rows(connection, window.start_date)
        facility_rows = [dict(row) for row in connection.execute(select(facilities)).mappings()]

    # Advancing the clock extends one edge, trims the other, and preserves overlap.
    next_day = as_of + timedelta(days=1)
    next_window = SeedWindow.ending_on(next_day)
    rolled_results = run_seeders(as_of=next_day, engine=engine)
    assert rolled_results[1].changed_rows > 0
    rolled_publication = assert_current_reporting(engine, next_window)
    assert rolled_publication["revision"] > publication["revision"]
    with engine.connect() as connection:
        assert day_rows(connection, overlap_day) == overlap
        assert not day_rows(connection, window.start_date)
        expected_new_day = admission_module.build_daily_admissions(next_day, facility_rows)
        assert day_rows(connection, next_day) == sorted(
            expected_new_day, key=lambda row: row["admission_id"]
        )
        assert connection.scalar(select(func.count()).select_from(cache)) == 0

    # A damaged partition is restored with its original IDs and all original fields.
    removed = overlap[0]
    with engine.begin() as connection:
        connection.execute(
            admissions.delete().where(admissions.c.admission_id == removed["admission_id"])
        )
        assert connection.scalar(select(state.c.ready).where(state.c.id == 1)) is False
    repaired_results = run_seeders(as_of=next_day, engine=engine)
    assert repaired_results[1].changed_rows > 0
    assert_current_reporting(engine, next_window)
    with engine.connect() as connection:
        assert day_rows(connection, overlap_day) == overlap

    # The last dataset fails only after admissions has modified the rolling window.
    # All facts, coverage, facility data, summaries, and publication metadata must revert.
    class FailSeeder(BaseSeeder):
        name = "intentional_failure"
        dependencies = ("admissions",)

        def seed(self, context):
            return SeedResult(self.name, 0, 0)

        def validate(self, context, result):
            bounds = context.connection.execute(
                select(func.min(admissions.c.admission_date), func.max(admissions.c.admission_date))
            ).one()
            assert tuple(bounds) == (context.window.start_date, context.window.end_date)
            raise ValueError("Intentional validation failure after admissions changed")

    before_failure = database_snapshot(engine)
    with pytest.raises(ValueError, match="Intentional validation failure"):
        run_seeders(
            as_of=next_day + timedelta(days=1),
            engine=engine,
            registry=(*default_registry(), FailSeeder()),
        )
    assert database_snapshot(engine) == before_failure

    # Existing facts without a version manifest are legacy data, not an empty seed.
    # Refuse the incremental run before deleting old dates or inserting new dates.
    with engine.begin() as connection:
        connection.execute(datasets.delete().where(datasets.c.name == "admissions"))
    before_legacy_attempt = database_snapshot(engine)
    with pytest.raises(ValueError, match="full rebuild"):
        run_seeders(as_of=next_day + timedelta(days=1), engine=engine)
    assert database_snapshot(engine) == before_legacy_attempt
