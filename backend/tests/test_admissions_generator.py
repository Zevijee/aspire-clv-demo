from datetime import date, timedelta

from app.seeding.admissions import build_daily_admissions
from app.seeding.facilities import build_facility_rows


def test_overlapping_days_are_independent_of_generation_order():
    facilities = build_facility_rows()
    day = date(2026, 9, 11)
    first = build_daily_admissions(day, facilities)
    build_daily_admissions(day + timedelta(days=1), facilities)
    repeated = build_daily_admissions(day, list(reversed(facilities)))
    assert first == repeated
    assert len({row["admission_id"] for row in first}) == len(first)
    assert all(row["admission_date"] == day for row in first)
    assert {row["admission_id"] for row in first}.isdisjoint(
        row["admission_id"] for row in build_daily_admissions(day + timedelta(days=1), facilities)
    )


def test_daily_generation_maintains_readmission_integrity_and_source_mix():
    facilities = build_facility_rows()
    rows = [
        row
        for offset in range(30)
        for row in build_daily_admissions(date(2026, 8, 13) + timedelta(days=offset), facilities)
    ]
    assert rows
    assert 0.45 < sum(row["admission_source_type"] == "Hospital" for row in rows) / len(rows) < 0.55
    assert 0.09 < sum(row["is_readmission"] for row in rows) / len(rows) < 0.15
    assert all(
        (row["readmission_days_since_prior"] is None and not row["is_readmission"])
        or (row["is_readmission"] and 1 <= row["readmission_days_since_prior"] <= 60)
        for row in rows
    )
