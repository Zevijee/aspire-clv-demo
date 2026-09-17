"""Explicit reporting refresh entrypoint; safe to install without demo generators."""
import argparse
import json
from datetime import date

from reporting.planner import ReportScope, ordered_reports
from reporting.registry import REPORTS


def main(argv=None, *, targets=None):
    parser = argparse.ArgumentParser(description="Refresh reporting from existing source records only.")
    parser.add_argument("--dataset", action="append", choices=tuple(REPORTS), dest="datasets")
    parser.add_argument('--load-id', help='Build the reporting scope recorded by a completed source load.')
    parser.add_argument("--from", type=date.fromisoformat, dest="start_date")
    parser.add_argument("--through", type=date.fromisoformat, dest="end_date")
    parser.add_argument("--facility", action="append", default=[], dest="facility_codes")
    parser.add_argument("--organization", dest="organization_id")
    parser.add_argument("--include-dependencies", action="store_true")
    parser.add_argument("--from-canonical", action="store_true",
                        help="Publish canonical sources to compatibility event projections before refresh.")
    parser.add_argument("--preview", action="store_true", help="Print the offline plan without database access.")
    args = parser.parse_args(argv)
    if args.load_id:
        if args.start_date or args.end_date or args.datasets or targets or args.facility_codes or args.organization_id or args.from_canonical or args.include_dependencies:
            parser.error('--load-id uses its recorded scope; do not combine with new scope options.')
        if args.preview:
            print(json.dumps({'load_id': args.load_id, 'source_writes': False, 'scope': 'Recorded completed source load; no database connection.'}))
            return 0
        from data.db import get_engine
        from reporting.publication.loads import finish_load
        with get_engine().begin() as connection:
            result = finish_load(connection, args.load_id)
        print(json.dumps({'refreshed': result}))
        return 0
    if args.start_date is None or args.end_date is None:
        parser.error('Provide --from and --through, or --load-id.')
    if args.from_canonical and (not args.organization_id or not args.facility_codes):
        parser.error("--from-canonical requires --organization and one or more --facility values.")
    if args.from_canonical and (args.datasets or targets):
        parser.error("Canonical publication refreshes all affected report dependencies; do not combine it with --dataset.")
    scope = ReportScope(args.start_date, args.end_date, tuple(args.facility_codes), organization_id=args.organization_id)
    names = ordered_reports(args.datasets or targets or tuple(REPORTS), include_dependencies=args.include_dependencies)
    plan = {"datasets": names, "from": scope.start_date.isoformat(), "through": scope.end_date.isoformat(),
            "facilities": scope.facility_codes, "organization": scope.organization_id,
            "source_writes": False, "schema_changes": False, "project_canonical_sources": args.from_canonical,
            "monthly_scope": "Whole affected months read retained source/daily records.",
            "transaction": "Selected summaries, coverage, and reporting revision commit together."}
    if args.preview:
        print(json.dumps(plan, indent=2))
        return 0
    from data.db import get_engine
    from reporting.runner import refresh_from_canonical, refresh_reports
    with get_engine().begin() as connection:
        result = refresh_from_canonical(connection, scope) if args.from_canonical else refresh_reports(connection, names, scope)
    print(json.dumps({"refreshed": result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
