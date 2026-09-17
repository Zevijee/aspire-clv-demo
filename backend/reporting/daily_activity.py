"""Stable imports for the daily admissions reporting interface."""
from reporting.daily.activity import (
    cache, daily, metadata, sources, state, ensure_reporting_schema, refresh_reporting,
)


def main():
    from reporting.cli import main as refresh_cli
    return refresh_cli(targets=("daily_activity",))


if __name__ == "__main__":
    raise SystemExit(main())
