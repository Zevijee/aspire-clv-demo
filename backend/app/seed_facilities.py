"""Compatibility entry point; implementation lives in seeding.generators."""

from datetime import date

from seeding.generators.facilities import build_facility_rows, facilities
from seeding.runner import run_seeders

__all__ = ["build_facility_rows", "facilities", "seed_facilities"]


def seed_facilities(*, as_of: date | None = None) -> int:
    return run_seeders(as_of=as_of, targets=("facilities",))[0].row_count


def main() -> None:
    from seeding.cli import main as run_cli

    raise SystemExit(run_cli(targets=("facilities",)))


if __name__ == "__main__":
    main()
