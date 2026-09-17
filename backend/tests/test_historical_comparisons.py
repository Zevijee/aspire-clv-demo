from datetime import timedelta

import pytest
from app.admissions_reporting import daily, state
from app.adt_admissions import get_historical_comparisons
from app.database import get_engine
from sqlalchemy import func, select


def test_historical_averages_reconcile_to_daily_reporting():
    with get_engine().connect() as connection:
        first, latest = connection.execute(
            select(state.c.first_date, state.c.latest_date).where(state.c.id == 1)
        ).one()
        start = latest - timedelta(days=29)
        result = get_historical_comparisons(start_date=start, end_date=latest)
        assert len(result["periods"]) == 4
        for period in result["periods"]:
            begin, end = period["start"], period["end"]
            # Cached dates are JSON strings; uncached dates are date objects.
            from datetime import date

            begin = date.fromisoformat(begin) if isinstance(begin, str) else begin
            end = date.fromisoformat(end) if isinstance(end, str) else end
            expected = (
                connection.scalar(
                    select(func.sum(daily.c.total_admissions)).where(
                        daily.c.admission_date.between(begin, end)
                    )
                )
                or 0
            )
            assert sum(item[period["key"]] for item in result["items"]) == pytest.approx(
                expected / ((end - begin).days + 1)
            )
        unavailable = get_historical_comparisons(start_date=first, end_date=first)
        assert all(item["year"] is None and item["prior"] is None for item in unavailable["items"])
