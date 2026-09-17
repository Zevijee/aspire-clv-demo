from contextlib import contextmanager
from datetime import date, timedelta

import pytest
from app import report_cache
from app.admissions_reporting import refresh_reporting, state
from app.adt_admissions import get_admissions_kpis
from app.database import get_engine
from fastapi import HTTPException
from sqlalchemy import event, select, text


@pytest.mark.parametrize(
    "start,end,payers,scope",
    [
        ("2026-08-12", "2026-09-10", None, None),
        ("2026-08-12", "2026-09-10", ["Medicare", "Medicaid"], "portfolio"),
        ("2026-08-12", "2026-09-10", ["Medicare"], "region"),
        ("2026-09-10", "2026-09-10", None, "facility"),
        ("2023-09-10", "2023-09-10", None, None),
        ("2022-01-01", "2022-01-30", None, None),
        ("2026-08-12", "2026-09-10", ["NO_MATCH"], None),
    ],
)
def test_kpis_match_raw_records_for_both_periods(start, end, payers, scope):
    engine = get_engine()
    with engine.connect() as connection:
        facility = (
            connection.execute(
                text(
                    "SELECT name, portfolio, region FROM facilities ORDER BY facility_code LIMIT 1"
                )
            )
            .mappings()
            .one()
        )
    scopes = {"facility": None, "portfolio": None, "region": None}
    if scope:
        scopes[scope] = [facility["name" if scope == "facility" else scope]]
    start, end = date.fromisoformat(start), date.fromisoformat(end)
    result = get_admissions_kpis(start_date=start, end_date=end, payer_type=payers, **scopes)
    days = (end - start).days + 1
    for first, last, metrics in [
        (start, end, result),
        (start - timedelta(days=days), start - timedelta(days=1), result["prior_period"]),
    ]:
        clauses = ["a.admission_date BETWEEN :start AND :end"]
        params = {"start": first, "end": last}
        if payers:
            clauses.append("a.payer_type = ANY(:payers)")
            params["payers"] = payers
        if scope:
            column = "name" if scope == "facility" else scope
            clauses.append(f"f.{column} = :scope")
            params["scope"] = scopes[scope][0]
        with engine.connect() as connection:
            raw = (
                connection.execute(
                    text(
                        """
                SELECT count(*) AS total_admissions,
                  count(*) FILTER (WHERE is_readmission) AS readmission_count,
                  count(*) FILTER (WHERE readmission_days_since_prior <= 30)
                    AS readmission_within_30_days_count,
                  count(DISTINCT admission_source_name) AS unique_admission_source_count
                FROM adt_admissions a JOIN facilities f USING (facility_code)
                WHERE """
                        + " AND ".join(clauses)
                    ),
                    params,
                )
                .mappings()
                .one()
            )
        for key, value in raw.items():
            assert metrics[key] == value
        assert metrics["average_admissions_per_day"] == raw["total_admissions"] / days


def test_repeated_filter_order_uses_cache_without_summary_queries():
    parameters = dict(start_date=date(2026, 7, 3), end_date=date(2026, 7, 19))
    expected = get_admissions_kpis(**parameters, payer_type=["Medicare", "Medicaid"])
    statements = []

    def record(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(get_engine(), "before_cursor_execute", record)
    try:
        actual = get_admissions_kpis(**parameters, payer_type=["Medicaid", "Medicare", "Medicare"])
    finally:
        event.remove(get_engine(), "before_cursor_execute", record)
    assert expected == actual
    assert len(statements) == 1
    assert "adt_reporting_state" in statements[0] and "adt_report_cache" in statements[0]


def test_source_changes_invalidate_and_refresh_atomically(monkeypatch):
    # Exercise a real source change and refresh, then roll back ALL test changes.
    with get_engine().connect() as connection:
        transaction = connection.begin()

        class TransactionEngine:
            @contextmanager
            def connect(self):
                yield connection

            begin = connect

        monkeypatch.setattr(report_cache, "get_engine", lambda: TransactionEngine())

        @report_cache.cached_report
        def reporting_total_for_test():
            return int(connection.scalar(text("SELECT count(*) FROM adt_admissions")))

        try:
            before = reporting_total_for_test()
            connection.execute(
                text("""
                DELETE FROM adt_admissions WHERE admission_id =
                  (SELECT admission_id FROM adt_admissions ORDER BY admission_id LIMIT 1)
            """)
            )
            with pytest.raises(HTTPException) as error:
                reporting_total_for_test()
            assert error.value.status_code == 503
            refresh_reporting(connection)
            assert reporting_total_for_test() == before - 1
            assert (
                connection.scalar(text("SELECT sum(total_admissions) FROM adt_admissions_daily"))
                == before - 1
            )
            connection.execute(
                text("UPDATE facilities SET name = name WHERE facility_code='ASP-001'")
            )
            assert connection.scalar(select(state.c.ready).where(state.c.id == 1)) is False
        finally:
            transaction.rollback()
