"""Compatibility launcher for the explicit, scoped hospital-assignment backfill."""
def reconcile_hospital_regions(**kwargs):
    from seeding.runner import run_seeders
    return run_seeders(operation='backfill',backfill='hospital_assignments',**kwargs)

if __name__ == '__main__':
    from seeding.cli import main
    raise SystemExit(main())
