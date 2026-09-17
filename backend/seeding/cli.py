"""Explicit demo commands. Preview is offline; inspect is read-only."""
import argparse
import json
from datetime import date, timedelta
from common.time import business_date


def parse_day(value):
    if value == 'today':
        return business_date()
    if value == 'yesterday':
        return business_date() - timedelta(days=1)
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError('Use today, yesterday, or YYYY-MM-DD.') from error


def _inspect(plan, run_id=None):
    from sqlalchemy import select, func
    from data.db import get_engine
    from data.migrations.__main__ import require_schema
    from data.models.seed_tracking import coverage, runs
    from data.models.seed_operations import batches, target_identity
    with get_engine().connect() as connection:
        require_schema(connection)
        if run_id:
            row = connection.execute(select(runs).where(runs.c.run_id == run_id)).mappings().one_or_none()
            if row is None:
                raise ValueError('Unknown seed run ID.')
            print(json.dumps(dict(row), default=str, indent=2))
            rows = connection.execute(select(batches).where(batches.c.run_id == run_id)).mappings()
            print(json.dumps([dict(row) for row in rows], default=str, indent=2))
        else:
            target = connection.execute(select(target_identity)).mappings().one_or_none()
            print(json.dumps({'demo_identity': dict(target) if target else None}, default=str, indent=2))
            rows = connection.execute(select(coverage.c.dataset,func.min(coverage.c.seed_date).label('first'),
                func.max(coverage.c.seed_date).label('last'),func.count().label('completed_days')).group_by(coverage.c.dataset)).mappings()
            scopes = set(plan.facility_codes)
            names = set(plan.sources or plan.targets)
            selected = [dict(row) for row in rows if (not names or row['dataset'].split(':')[0] in names)
                and (not scopes or row['dataset'].split(':')[-1] in scopes)]
            print(json.dumps({'coverage': selected}, default=str, indent=2))


def main(targets=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', nargs='?', default='update', choices=(
        'preview','inspect','update','populate','rebuild','backfill','refresh','resume','full-reset'))
    parser.add_argument('--dataset', action='append')
    dates = parser.add_mutually_exclusive_group()
    dates.add_argument('--through', type=parse_day)
    dates.add_argument('--as-of', type=parse_day)
    history = parser.add_mutually_exclusive_group()
    history.add_argument('--history-months', type=int)
    history.add_argument('--history-years', type=int)
    parser.add_argument('--from', dest='replace_from', type=parse_day)
    parser.add_argument('--facility', dest='facility_codes', action='append', default=[])
    parser.add_argument('--entity', dest='entity_ids', action='append', default=[])
    parser.add_argument('--organization', default='aspire-demo')
    parser.add_argument('--scenario-key', default='aspire-demo')
    parser.add_argument('--generator-version', action='append', default=[], metavar='DATASET=VERSION')
    parser.add_argument('--changed-field', action='append', default=[])
    parser.add_argument('--backfill-name', choices=('canonical_sources','hospital_assignments','initial_payer'))
    parser.add_argument('--batch-size', type=int, default=1000)
    parser.add_argument('--concurrency', type=int, default=1)
    parser.add_argument('--run-id')
    parser.add_argument('--demo-instance', help='Must match the explicitly configured database identity')
    parser.add_argument('--preview', action='store_true')
    parser.add_argument('--sources-only', action='store_true', help='Load source records without building reporting summaries.')
    parser.add_argument('--inspect', action='store_true', help='Read-only schema/coverage inspection with preview')
    parser.add_argument('--rebuild', action='store_true', help='Compatibility alias for rebuild')
    parser.add_argument('--check', action='store_true', help='Compatibility alias for offline preview')
    args = parser.parse_args()
    try:
        if args.operation == 'resume':
            if args.sources_only:
                raise ValueError('Resume uses the recorded sources-only setting.')
            if not args.run_id:
                raise ValueError('Resume requires --run-id.')
            if args.dataset or args.facility_codes or args.entity_ids or args.through or args.as_of or args.replace_from or args.changed_field or args.backfill_name or args.generator_version:
                raise ValueError('Resume uses the recorded immutable scope/version plan; do not supply new targets or dates.')
            if args.preview or args.check or args.inspect:
                if args.inspect:
                    _inspect(None,args.run_id)
                else:
                    print(json.dumps({'operation':'resume','run_id':args.run_id,
                        'offline':True,'scope':'Stored plan requires explicit inspect; no database connection made.'},indent=2))
                return 0
            from seeding.runner import run_seeders
            run_seeders(resume_run_id=args.run_id,demo_instance=args.demo_instance)
            return 0
        if args.run_id and args.operation != 'inspect':
            raise ValueError('--run-id applies to resume or inspect only.')
        if args.operation == 'inspect' and args.run_id:
            _inspect(None,args.run_id)
            return 0
        operation = 'rebuild' if args.rebuild else 'update' if args.operation in ('preview','inspect') else args.operation
        if args.rebuild and args.operation not in ('update','rebuild','preview'):
            raise ValueError('Do not combine --rebuild with a different operation.')
        requested = tuple(args.dataset) if args.dataset else targets
        # Legacy reporting launchers still route to the independent reporting service.
        if operation == 'update' and requested:
            from reporting.registry import REPORTS
            if set(requested) <= set(REPORTS):
                operation = 'refresh'
        months = args.history_months if args.history_months is not None else args.history_years * 12 if args.history_years is not None else 36
        versions = {}
        for item in args.generator_version:
            if '=' not in item:
                raise ValueError('Generator version must be DATASET=VERSION.')
            name,value = item.split('=',1)
            versions[name] = value
        kwargs = dict(operation=operation,targets=requested,history_months=months,replace_from=args.replace_from,
            facility_codes=args.facility_codes,entity_ids=args.entity_ids,organization_id=args.organization,
            scenario_key=args.scenario_key,versions=versions,changed_fields=args.changed_field,
            backfill=args.backfill_name,batch_size=args.batch_size,concurrency=args.concurrency)
        from seeding.planner import build_plan
        plan = build_plan(through=args.through or args.as_of or business_date(),**kwargs)
        if args.sources_only and operation == 'refresh':
            raise ValueError('--sources-only cannot be used for reporting refresh.')
        if args.preview or args.check or args.operation in ('preview','inspect') or args.inspect:
            print(json.dumps(dict(plan.describe(), sources_only=args.sources_only),indent=2))
            if args.inspect or args.operation == 'inspect':
                _inspect(plan)
            else:
                print('Offline preview: no database connection. Existing coverage/boundaries are resolved only by explicit execution.')
            return 0
        from seeding.runner import run_seeders
        run_seeders(as_of=plan.window.end_date,demo_instance=args.demo_instance,sources_only=args.sources_only,**kwargs)
        return 0
    except KeyboardInterrupt:
        print('Interrupted. The current stage batch rolls back; committed stages can be resumed using the logged run ID.')
        return 130
    except (ValueError,RuntimeError) as error:
        print(f'Cannot complete operation: {error}')
        return 1
    except Exception as error:
        from sqlalchemy.exc import SQLAlchemyError
        if not isinstance(error,SQLAlchemyError):
            raise
        original = getattr(error, 'orig', None)
        diagnostic = getattr(original, 'diag', None)
        message = getattr(diagnostic, 'message_primary', None)
        sqlstate = getattr(original, 'sqlstate', None)
        if message:
            # Do not print SQL parameters or entire resident/source payloads.
            print(f'Database error{f" [{sqlstate}]" if sqlstate else ""}: {message}')
        print('Database operation failed. Current batch rolled back; inspect the recorded run and schema before resuming.')
        return 1
