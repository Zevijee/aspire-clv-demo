"""Explicit command-line entry point for sandbox data generators."""
import argparse
from datetime import date
import os
from pathlib import Path
import sys
from time import perf_counter

# Support `python manage.py` from sandbox-data without copying the shared package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    from base import BaseGenerator
    from shared.database import lifecycle
    from shared.database.documentation import write_documentation
    from shared.database.console import message, RunProgress

    database_commands = ('upgrade', 'migrate', 'status', 'check', 'stage', 'revision', 'schema-docs')

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('generator', choices=('seed', 'update', 'all', *database_commands, *BaseGenerator.RUN_ORDER),
        help='Seed history or update missing days through today; reference generators remain available.')
    parser.add_argument('--plan', action='store_true',
        help='Show migration files and generator order without connecting to the database.')
    parser.add_argument('--regenerate', action='store_true',
        help='Refresh a reference generator or selected summary. Completed daily ADT is never rerolled.')
    parser.add_argument('--staged', action='store_true',
        help='With upgrade: publish the reviewed schema draft, then apply its migrations/backfills.')
    def parse_day(value):
        return BaseGenerator.today() if value == 'today' else date.fromisoformat(value)
    parser.add_argument('--from', dest='start', type=parse_day, help='First requested day, YYYY-MM-DD.')
    parser.add_argument('--through', type=parse_day, help='Last requested day, inclusive; defaults to today.')
    parser.add_argument('--date', type=parse_day, help='Process one date; earlier ADT dates must already be complete.')
    parser.add_argument('--only', help='Run a selected daily handler and its missing dependencies (e.g. admissions_summary).')
    parser.add_argument('--reset-history', action='store_true',
        help='With seed: drop every table and rebuild from empty. The same seed and facility list reproduce the same data.')
    parser.add_argument('--message', help='Description for a draft schema revision.')
    parser.add_argument('--batch-size', type=int, default=10000, help='Rows per upgrade backfill transaction.')
    parser.add_argument('--max-batches', type=int, help='Pause upgrade after this many committed backfill batches.')
    parser.add_argument('--check-docs', action='store_true', help='With schema-docs: fail if generated documentation is stale.')
    args = parser.parse_args()
    if args.staged and args.generator != 'upgrade':
        parser.error('--staged applies only to upgrade.')
    # Only these walk the day-by-day simulation. res_stays and the two log generators
    # rebuild from already-saved rows, so they run alone instead of being silently
    # widened into a full daily catch-up.
    daily = args.generator in ('seed', 'update', 'all', 'admissions_summary', 'discharges_summary',
        'payer_changes_summary', 'net_change_summary', 'monthly_adt_summary', 'referrals_summary',
        'monthly_adt_facts', 'census_logs')
    standalone = args.generator in ('res_stays', 'admission_logs', 'discharge_logs',
        'payer_change_logs')
    if args.date and (args.start or args.through):
        parser.error('--date cannot be combined with --from or --through.')
    if args.reset_history and args.generator != 'seed':
        parser.error('--reset-history is only available with seed.')
    if not daily and (args.start or args.through or args.date or args.only or args.reset_history):
        parser.error('Date options and --only apply to seed/update or daily ADT/summary commands.')
    if args.generator in database_commands and args.regenerate:
        parser.error('--regenerate applies to data generators, not migrations.')
    if args.message and args.generator != 'revision':
        parser.error('--message applies to revision.')
    if args.check_docs and args.generator != 'schema-docs':
        parser.error('--check-docs applies to schema-docs.')
    if (args.max_batches is not None or args.batch_size != 10000) and args.generator not in ('upgrade', 'update'):
        parser.error('Batch options apply to upgrade or update.')
    if args.batch_size < 1 or (args.max_batches is not None and args.max_batches < 1):
        parser.error('Batch limits must be positive.')
    try:
        summaries = ('admissions_summary', 'discharges_summary', 'payer_changes_summary',
            'net_change_summary',
            'monthly_adt_summary', 'referrals_summary', 'monthly_adt_facts', 'census_logs')
        daily_target = args.only or (args.generator if args.generator in summaries else 'all')
        daily_plan = BaseGenerator.daily_plan(daily_target) if daily else ()
        start = args.date or args.start
        through = args.date or args.through or BaseGenerator.today()
        if daily and (through > BaseGenerator.today() or through < BaseGenerator.SIMULATION_START or (start and
                (start < BaseGenerator.SIMULATION_START or start > through))):
            parser.error('Dates must run from 2023-01-01 through today, in chronological order.')
        if daily and args.regenerate and (daily_target == 'all' or any(
                item.name == daily_target and item.sequential for item in daily_plan)):
            parser.error('Use seed --reset-history to rebuild ADT; --regenerate is only for summaries/reference data.')
        if args.reset_history and (daily_target != 'all' or start not in (None, BaseGenerator.SIMULATION_START)
                or args.regenerate):
            parser.error('History reset starts on 2023-01-01 and runs all daily handlers without --regenerate.')
        # A reset drops every table, so the resident pool has to be rebuilt before ADT
        # runs; otherwise the simulation invents residents on demand under different IDs.
        reference = ('states', 'portfolios', 'regions', 'facilities', 'payers', 'payer_rates',
            'referring_hospitals')
        if args.reset_history:
            reference += ('residents',)
        if args.generator in database_commands:
            plan = ()
        elif daily:
            plan = tuple(item for item in BaseGenerator.execution_plan('all')
                if item.name in reference)
        elif standalone:
            # Run only the requested generator: its inputs are saved rows, and its own
            # prepare_sources reports clearly if they are missing or inconsistent.
            plan = tuple(item for item in BaseGenerator.execution_plan(args.generator)
                if item.name == args.generator)
        else:
            plan = BaseGenerator.execution_plan(args.generator)
    except ValueError as error:
        parser.error(str(error))
    message(f'\nSandbox data | {args.generator}{" (plan)" if args.plan else ""}')
    if daily:
        message(f'  {start or "Missing days"} through {through} ({BaseGenerator.SIMULATION_TIMEZONE})')
    message()
    if args.plan:
        if plan:
            message('  Generators: ' + ' -> '.join(generator.name for generator in plan))
        if daily:
            message('  Daily:      ' + ' -> '.join(item.name for item in daily_plan))
        message('  Migrations: ' + ', '.join(item.revision for item in lifecycle.upgrade_plan()))
        message('  Backfills:  ' + ' -> '.join(job.name for job in lifecycle.backfills.ordered_jobs()))
        from shared.database.staging import describe
        describe()
        message('\nCompleted work is skipped. Use status to see what is pending in your database.')
        if args.reset_history:
            message('RESET: every table is dropped and rebuilt from empty, including reference data and residents.')
        return 0

    if args.generator == 'stage':
        from shared.database.staging import begin
        try:
            begin()
        except (ValueError, OSError) as error:
            parser.error(str(error))
        return 0

    if args.generator == 'schema-docs':
        try:
            write_documentation(check=args.check_docs)
        except ValueError as error:
            parser.error(str(error))
        return 0

    from dotenv import load_dotenv
    from psycopg import Error as PsycopgError
    from sqlalchemy.exc import SQLAlchemyError
    from alembic.util.exc import CommandError

    # Resolve the shared root configuration independently of the working directory.
    load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=False)
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        parser.error('Set DATABASE_URL in the repository root .env or your environment.')
    # Say which database, every time. Two databases with the same schema and
    # different data is the failure this prevents.
    message(f'  Database    {lifecycle.describe_url(database_url)}')
    message()

    started = perf_counter()
    try:
        if args.reset_history:
            # Everything is regenerated deterministically from the same seed, so
            # start from an empty database instead of clearing rows in place.
            lifecycle.drop_everything(database_url)
            lifecycle.upgrade(database_url, batch_size=args.batch_size, max_batches=args.max_batches)
        if args.generator == 'update':
            from shared.database.staging import apply, needs_apply
            if not os.getenv('ASPIRE_DATABASE_STAGE_WORKER') and needs_apply():
                forwarded = []
                for flag, value in (('--date', args.date), ('--from', args.start),
                        ('--through', args.through), ('--only', args.only)):
                    if value is not None:
                        forwarded += [flag, str(value)]
                if args.regenerate:
                    forwarded.append('--regenerate')
                return apply(batch_size=args.batch_size, max_batches=args.max_batches,
                    command_name='update', arguments=forwarded)
            # Finish schema changes and required data work before any generator
            # reads or writes the next day. Failed upgrades abort this command.
            lifecycle.upgrade(database_url, batch_size=args.batch_size, max_batches=args.max_batches)
            if os.getenv('ASPIRE_DATABASE_STAGE_WORKER'):
                write_documentation()
        if args.generator == 'upgrade' and args.staged:
            from shared.database.staging import apply
            return apply(batch_size=args.batch_size, max_batches=args.max_batches)
        if args.generator in ('upgrade', 'migrate'):
            lifecycle.upgrade(database_url, data=args.generator == 'upgrade',
                batch_size=args.batch_size, max_batches=args.max_batches)
            if os.getenv('ASPIRE_DATABASE_STAGE_WORKER'):
                write_documentation()
            if args.generator == 'migrate':
                message('\nRun upgrade to complete any pending backfills.')
        elif args.generator == 'status':
            lifecycle.status(database_url)
            from shared.database.staging import describe
            describe()
        elif args.generator == 'check':
            lifecycle.check(database_url)
            write_documentation(check=True)
        elif args.generator == 'revision':
            lifecycle.revision(database_url, args.message)
        for generator_class in plan:
            generator = generator_class(database_url)
            generator.run(regenerate=not daily and args.regenerate and args.generator == generator.name)
        if daily:
            BaseGenerator.run_days(database_url, through=through, start=start, target=daily_target,
                reset_history=args.reset_history, refresh=args.regenerate)
    except (SQLAlchemyError, PsycopgError) as error:
        # Never print connection strings, passwords or bound row values.
        original = getattr(error, 'orig', error)
        diagnostic = getattr(original, 'diag', None)
        error_message = getattr(diagnostic, 'message_primary', None)
        code = getattr(original, 'sqlstate', None)
        message(f'\nDatabase error{f" [{code}]" if code else ""}: '
            f'{error_message or "Could not complete the database operation; check the database connection and configuration."}')
        return 1
    except (ValueError, OSError, CommandError, SyntaxError, ImportError) as error:
        message(f'\n{args.generator} failed: {error}')
        return 1
    except KeyboardInterrupt:
        message('\nStopped. Committed work is saved; rerun the command to resume pending work.')
        return 130
    message(f'\nDone in {RunProgress.duration(perf_counter() - started)}.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
