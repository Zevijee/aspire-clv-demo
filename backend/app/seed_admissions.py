"""Compatibility entry point; implementation lives in seeding.generators."""

from datetime import date

from seeding.generators.admissions import admissions
from seeding.runner import run_seeders

__all__ = ["admissions", "seed_admissions"]


def seed_admissions(*, rebuild: bool = False, as_of: date | None = None) -> int:
    results = run_seeders(as_of=as_of, rebuild=rebuild, targets=("admissions",))
    return next(result.row_count for result in results if result.name == "admissions")


def main() -> None:
    from seeding.cli import main as run_cli

    raise SystemExit(run_cli(targets=("admissions",)))


if __name__ == "__main__":
    main()
