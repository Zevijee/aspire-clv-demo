"""Calendar boundaries and seeder dependency resolution require no database."""

from datetime import date

import pytest
from app.seeding import base
from app.seeding.base import BaseSeeder, SeedWindow
from app.seeding.runner import resolve_seeders


@pytest.mark.parametrize(
    "as_of,expected_start,expected_days",
    [
        (date(2026, 9, 11), date(2023, 9, 11), 1097),
        (date(2027, 3, 1), date(2024, 3, 1), 1096),
        (date(2028, 2, 29), date(2025, 2, 28), 1097),
        (date(2027, 2, 28), date(2024, 2, 28), 1097),
        (date(2026, 1, 1), date(2023, 1, 1), 1097),
    ],
)
def test_window_uses_three_calendar_years_and_includes_both_boundaries(
    as_of, expected_start, expected_days
):
    window = SeedWindow.ending_on(as_of)

    assert window.start_date == expected_start
    assert window.end_date == as_of
    assert window.days == expected_days


def test_window_captures_local_today_once(monkeypatch):
    class LocalDate(date):
        calls = 0

        @classmethod
        def today(cls):
            cls.calls += 1
            # Crossing midnight between reads must not produce a mismatched window.
            return date(2026, 12, 31) if cls.calls == 1 else date(2027, 1, 1)

    monkeypatch.setattr(base, "date", LocalDate)

    window = SeedWindow.ending_on()

    assert LocalDate.calls == 1
    assert window.start_date == date(2023, 12, 31)
    assert window.end_date == date(2026, 12, 31)


def test_explicit_reference_date_does_not_read_the_clock(monkeypatch):
    class UnexpectedClockRead(date):
        @classmethod
        def today(cls):
            raise AssertionError("An explicit reference date must be reproducible")

    monkeypatch.setattr(base, "date", UnexpectedClockRead)

    assert SeedWindow.ending_on(date(2024, 2, 29)).start_date == date(2021, 2, 28)


class StubSeeder(BaseSeeder):
    """Resolving dependencies must never prepare, seed, or validate data."""

    def __init__(self, name, dependencies=()):
        self.name = name
        self.dependencies = dependencies

    def prepare(self, context):
        raise AssertionError("Dependency resolution must not prepare a database")

    def seed(self, context):
        raise AssertionError("Dependency resolution must not generate data")

    def validate(self, context, result):
        raise AssertionError("Dependency resolution must not validate a database")


def test_default_run_includes_all_seeders_after_their_dependencies():
    facilities = StubSeeder("facilities")
    admissions = StubSeeder("admissions", ("facilities",))
    reporting = StubSeeder("reporting", ("admissions",))

    assert resolve_seeders((reporting, admissions, facilities)) == [
        facilities,
        admissions,
        reporting,
    ]


def test_targeted_run_includes_dependencies_and_excludes_unrelated_seeders():
    facilities = StubSeeder("facilities")
    admissions = StubSeeder("admissions", ("facilities",))
    unrelated = StubSeeder("unrelated")

    assert resolve_seeders((unrelated, admissions, facilities), ("admissions",)) == [
        facilities,
        admissions,
    ]


def test_shared_dependency_runs_once_even_when_also_selected():
    facilities = StubSeeder("facilities")
    admissions = StubSeeder("admissions", ("facilities",))
    census = StubSeeder("census", ("facilities",))

    resolved = resolve_seeders(
        (facilities, admissions, census), ("admissions", "census", "facilities")
    )

    assert resolved == [facilities, admissions, census]


def test_empty_registry_has_no_work():
    assert resolve_seeders(()) == []


def test_duplicate_registry_names_are_rejected():
    with pytest.raises(ValueError):
        resolve_seeders((StubSeeder("facilities"), StubSeeder("facilities")))


def test_unknown_target_is_rejected():
    with pytest.raises(ValueError):
        resolve_seeders((StubSeeder("facilities"),), ("missing",))


def test_missing_dependency_is_rejected():
    with pytest.raises(ValueError):
        resolve_seeders((StubSeeder("admissions", ("facilities",)),))


@pytest.mark.parametrize(
    "registry",
    [
        (StubSeeder("facilities", ("facilities",)),),
        (
            StubSeeder("facilities", ("admissions",)),
            StubSeeder("admissions", ("facilities",)),
        ),
    ],
)
def test_dependency_cycles_are_rejected(registry):
    with pytest.raises(ValueError):
        resolve_seeders(registry)
