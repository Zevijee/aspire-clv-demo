"""Seed payer changes through the shared transactional runner."""

from seeding.cli import main as run_cli


def main() -> int:
    return run_cli(targets=("payer_changes",))


if __name__ == "__main__":
    raise SystemExit(main())
