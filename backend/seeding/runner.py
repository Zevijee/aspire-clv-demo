"""Explicit bounded source batches with transaction-matched checkpoints/publications."""
from dataclasses import replace
from datetime import date, timedelta
from uuid import uuid4
from time import perf_counter
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from data.db import get_engine
from data.locking import lock_source_scope
from data.migrations.__main__ import require_schema
from data.models.seed_tracking import coverage, runs
from data.models.seed_operations import batches, boundaries
from data.models.facilities import facilities
from data.models.admissions import admissions
from seeding.base import SeedContext, SeedResult, SeedWindow
from seeding.planner import Plan, build_plan
from seeding.state.target import require_demo_target


def resolve_seeders(registry, targets=None):
    """Legacy helper; resolve dependencies explicitly without executing them."""
    by_name = {item.name: item for item in registry}
    if len(by_name) != len(registry):
        raise ValueError('Duplicate generator names.')
    ordered, visiting = [], set()
    def visit(name):
        if name not in by_name:
            raise ValueError('Unknown source dataset: ' + name)
        if name in visiting:
            raise ValueError('Source dependency cycle: ' + name)
        if by_name[name] in ordered:
            return
        visiting.add(name)
        for dependency in by_name[name].dependencies:
            visit(dependency)
        visiting.remove(name)
        ordered.append(by_name[name])
    for name in targets or by_name:
        visit(name)
    return ordered


def _lock(connection, name):
    connection.execute(text('SELECT pg_advisory_xact_lock(hashtext(current_schema() || :name))'), {'name': ':seed:' + name})


def _retained_window(connection, window, codes):
    from data.models.stays import census
    from data.models.discharges import discharges
    first, last = connection.execute(select(func.min(admissions.c.admission_date), func.max(admissions.c.admission_date))
        .where(admissions.c.facility_code.in_(codes))).one()
    census_first,census_last = connection.execute(select(func.min(census.c.census_date),func.max(census.c.census_date))
        .where(census.c.facility_code.in_(codes))).one()
    discharge_first,discharge_last = connection.execute(select(func.min(discharges.c.discharge_date),func.max(discharges.c.discharge_date))
        .where(discharges.c.facility_code.in_(codes))).one()
    keys = [f'{dataset}:{code}' for code in codes for dataset in ('admissions','discharges','payer_changes','bed_holds')]
    if first or census_first or discharge_first:
        keys.extend(('admissions','discharges','payer_changes'))
    cov_first, cov_last = connection.execute(select(func.min(coverage.c.seed_date), func.max(coverage.c.seed_date))
        .where(coverage.c.dataset.in_(keys))).one()
    start = min([window.start_date] + [value for value in (first,cov_first,census_first,discharge_first) if value])
    end = max([window.end_date] + [value for value in (last,cov_last,census_last,discharge_last) if value])
    return SeedWindow(start.replace(day=1),end)


def _resume_plan(details):
    replacement = SeedWindow(date.fromisoformat(details['replace_from']), date.fromisoformat(details['replace_through'])) if details.get('replace_from') else None
    return Plan(details['operation'], SeedWindow(date.fromisoformat(details['from']), date.fromisoformat(details['through'])),
        tuple(details['requested']), tuple(details.get('generator_order', details['source_order'])), tuple(details['report_order']),
        tuple(details['rebuild_sources']), replacement, tuple(details['facility_codes']), tuple(details.get('entity_ids', ())),
        details['organization_id'], details['scenario_key'], tuple(sorted(details.get('versions', {}).items())),
        tuple(details.get('changed_fields', ())), details.get('backfill'), details.get('batch_size',1000))


def _protect_source_ownership(connection, plan):
    from data.models.canonical import census_stays,payer_stays
    owners = dict(connection.execute(select(facilities.c.facility_code,facilities.c.organization_id)
        .where(facilities.c.facility_code.in_(plan.facility_codes))).all())
    if any(owner and owner != plan.organization_id for owner in owners.values()):
        raise ValueError('Facility scope crosses organization ownership.')
    reference_only = bool(plan.sources) and set(plan.sources) <= {'states', 'portfolios', 'regions', 'payers'}
    if 'facilities' not in plan.sources and not reference_only and set(plan.facility_codes) - set(owners):
        raise ValueError('Unknown facilities: ' + ', '.join(sorted(set(plan.facility_codes)-set(owners))))
    if plan.operation != 'refresh' and (plan.backfill or set(plan.sources) - {'payers'}):
        imported = connection.scalar(select(census_stays.c.stay_id).where(
            census_stays.c.organization_id == plan.organization_id,
            census_stays.c.facility_code.in_(plan.facility_codes),census_stays.c.source_system != 'legacy-adt').limit(1))
        imported_coverage = connection.scalar(select(payer_stays.c.payer_stay_id).select_from(payer_stays.join(census_stays,
            (payer_stays.c.organization_id == census_stays.c.organization_id) & (payer_stays.c.stay_id == census_stays.c.stay_id)))
            .where(census_stays.c.organization_id == plan.organization_id,census_stays.c.facility_code.in_(plan.facility_codes),
                payer_stays.c.source_system != 'legacy-adt').limit(1))
        if imported or imported_coverage:
            raise ValueError('Selected facilities contain imported/manual source stays or coverage. Fake generation cannot overwrite those facilities.')


def _missing_reporting(connection, names, code, window):
    from data.models.reporting_publication import coverage as reported
    from reporting.publication.coverage import RULES_VERSION, COMPATIBLE_LEGACY_RULES
    expected = set(names) - {'report_results'}
    counts = dict(connection.execute(select(reported.c.dataset,func.count()).where(
        reported.c.facility_code == code,reported.c.dataset.in_(expected),
        reported.c.date.between(window.start_date,window.end_date),
        reported.c.rules_version.in_((RULES_VERSION,COMPATIBLE_LEGACY_RULES))).group_by(reported.c.dataset)).all())
    return tuple(name for name in names if name in expected and counts.get(name,0) != window.days)


def _clear_owned_population(connection, code):
    """Called exclusively by full-reset, never normal update/rebuild."""
    from data.models.discharges import discharges
    from data.models.stays import stays, census
    from data.models.payer_changes import payer_changes
    from data.models.payer_periods import periods
    from data.models.bed_holds import bed_holds
    from data.models.canonical import census_stays, payer_stays
    owned_stays = select(census_stays.c.stay_id).where(
        census_stays.c.organization_id == 'aspire-demo', census_stays.c.facility_code == code,
        census_stays.c.source_system == 'legacy-adt')
    connection.execute(payer_stays.delete().where(payer_stays.c.organization_id == 'aspire-demo',
        payer_stays.c.source_system == 'legacy-adt', payer_stays.c.stay_id.in_(owned_stays)))
    for table in (payer_changes, periods, discharges, stays, census, bed_holds, admissions):
        connection.execute(table.delete().where(table.c.facility_code == code))
    connection.execute(coverage.delete().where(coverage.c.dataset.in_(
        [f'{dataset}:{code}' for dataset in ('admissions','discharges','payer_changes','bed_holds')])))
    connection.execute(boundaries.delete().where(boundaries.c.scope_key == code))


def _verify_dependencies(connection, plan, code):
    from seeding.registry import SOURCES
    if code and not connection.scalar(select(facilities.c.facility_code).where(facilities.c.facility_code == code)):
        raise ValueError(f'Facility {code} is missing. Populate facilities explicitly first.')
    if 'admissions' in plan.sources:
        from data.models.hospital_reporting import hospitals
        from data.models.canonical import payer_plans
        from seeding.reference_data.hospital_directory import hospital_names_for_facility
        from seeding.reference_data.payers import PAYER_REFERENCES
        facility = dict(connection.execute(select(facilities).where(facilities.c.facility_code == code)).mappings().one())
        expected_hospitals = set(hospital_names_for_facility(facility))
        existing_hospitals = set(connection.scalars(select(hospitals.c.hospital).where(hospitals.c.hospital.in_(expected_hospitals))))
        if expected_hospitals != existing_hospitals:
            raise ValueError(f'Hospital references for {code} are incomplete; explicitly update hospitals first.')
        expected_plans = {row['code'] for row in PAYER_REFERENCES}
        existing_plans = set(connection.scalars(select(payer_plans.c.code).where(payer_plans.c.organization_id == plan.organization_id,
            payer_plans.c.code.in_(expected_plans))))
        if expected_plans != existing_plans:
            raise ValueError('Payer references are incomplete; explicitly update payers first.')
    if 'discharges' in plan.sources and 'admissions' not in plan.sources:
        scoped = connection.scalar(select(func.count()).select_from(coverage).where(
            coverage.c.dataset == f'admissions:{code}', coverage.c.seed_date.between(plan.window.start_date, plan.window.end_date)))
        legacy = connection.scalar(select(func.count()).select_from(coverage).where(coverage.c.dataset == 'admissions',
            coverage.c.seed_date.between(plan.window.start_date, plan.window.end_date)))
        if max(scoped, legacy) < plan.window.days:
            raise ValueError(f'Admissions coverage for {code} is incomplete. Run the explicit admissions update first.')
    if {'payer_changes','bed_holds'} & set(plan.sources) and 'discharges' not in plan.sources:
        from data.models.stays import census
        count = connection.scalar(select(func.count()).select_from(census).where(census.c.facility_code == code,
            census.c.census_date.between(plan.window.start_date, plan.window.end_date)))
        if count < plan.window.days:
            raise ValueError(f'Stay/census coverage for {code} is incomplete. Update discharges first.')


def _run_legacy_seeders(*, as_of=None, rebuild=False, targets=None, engine=None, registry=None, log=print,
                operation=None, history_months=36, replace_from=None, facility_codes=(), entity_ids=(),
                organization_id='aspire-demo', scenario_key='aspire-demo', versions=None, changed_fields=(),
                backfill=None, batch_size=1000, concurrency=1, resume_run_id=None, demo_instance=None):
    database = engine if engine is not None else get_engine()
    plan = None if resume_run_id else build_plan(operation or ('rebuild' if rebuild else 'update'), targets, as_of,
        history_months, replace_from, facility_codes=facility_codes, entity_ids=entity_ids,
        organization_id=organization_id, scenario_key=scenario_key, versions=versions, changed_fields=changed_fields,
        backfill=backfill, batch_size=batch_size, concurrency=concurrency)
    run_id = resume_run_id or str(uuid4())
    with database.begin() as connection:
        require_schema(connection)
        require_demo_target(connection, demo_instance)
        if resume_run_id:
            _lock(connection, 'run:' + run_id)
            recorded = connection.execute(select(runs).where(runs.c.run_id == run_id).with_for_update()).mappings().one_or_none()
            if recorded is None or recorded['status'] == 'complete':
                raise ValueError('Resume needs an existing incomplete seed run.')
            plan = _resume_plan(recorded['plan'])
            if plan.operation != 'refresh':
                from seeding.registry import SOURCES
                actual = {name: SOURCES[name].version for name in plan.sources}
                if plan.backfill:
                    actual = {plan.backfill: '1'}
                if actual != dict(plan.versions):
                    raise ValueError('Recorded generator versions differ; resume would mix incompatible versions.')
            connection.execute(runs.update().where(runs.c.run_id == run_id).values(status='running', finished_at=None, error_type=None))
        else:
            requested = plan.facility_codes
            if not requested:
                found = tuple(connection.scalars(select(facilities.c.facility_code).where(
                    facilities.c.organization_id == plan.organization_id).order_by(facilities.c.facility_code)))
                if plan.operation != 'refresh' and (not found or 'facilities' in plan.sources):
                    from seeding.reference_data.facilities import build_facility_rows
                    found = tuple(row['facility_code'] for row in build_facility_rows())
                requested = found
            if not requested and (plan.sources or plan.backfill):
                raise ValueError('No facilities are available in the requested demo scope.')
            plan = replace(plan, facility_codes=requested)
            _protect_source_ownership(connection, plan)
            if plan.entity_ids and plan.backfill == 'hospital_assignments':
                condition = plan.replacement or plan.window
                found = set(connection.scalars(select(admissions.c.admission_id).where(admissions.c.admission_id.in_(plan.entity_ids),
                    admissions.c.facility_code.in_(plan.facility_codes),admissions.c.admission_source_type == 'Hospital',
                    admissions.c.admission_date.between(condition.start_date,condition.end_date))))
                if found != set(plan.entity_ids):
                    raise ValueError('An admission entity ID is unknown or outside the selected hospital/facility/date scope.')
            connection.execute(runs.insert().values(run_id=run_id, status='running', operation=plan.operation, plan=plan.describe()))
    log(f'Run {run_id}: {plan.operation}; {len(plan.facility_codes)} facilities.')
    results = []
    current_batch = None
    try:
        from reporting.planner import ReportScope, affected_reports
        from reporting.runner import refresh_reports
        if plan.operation == 'refresh':
            work = [('reports', None)]
            source_registry = {}
        else:
            from seeding.registry import SOURCES, default_registry
            source_registry = {item.name: item for item in (registry if registry is not None else default_registry())}
            references = tuple(name for name in plan.sources if not SOURCES[name].date_based)
            history = tuple(name for name in plan.sources if SOURCES[name].date_based)
            work = ([('references', None)] if references else []) + ([(f'facility:{code}', code)
                for code in plan.facility_codes] if history or plan.backfill else [])
        for batch_key, code in work:
            current_batch = batch_key
            batch_started = perf_counter()
            timings = {}
            # The completion row commits with source writes, state, and reporting.
            with database.begin() as connection:
                require_schema(connection)
                require_demo_target(connection, demo_instance)
                _lock(connection, 'run:' + run_id)
                _lock(connection, code or batch_key)
                lock_source_scope(connection,plan.organization_id)
                connection.execute(text('SELECT id FROM adt_reporting_state WHERE id=1 FOR UPDATE'))
                _protect_source_ownership(connection, replace(plan,facility_codes=(code,)) if code else plan)
                prior_batch = connection.execute(select(batches).where(batches.c.run_id == run_id,batches.c.batch_key == batch_key)).mappings().one_or_none()
                if prior_batch and prior_batch['status'] == 'complete':
                    log(f'  {batch_key}: already committed; skipped on resume.')
                    current_batch = None
                    continue
                attempts = (prior_batch['details'].get('attempts',0) if prior_batch else 0) + 1
                statement = insert(batches).values(run_id=run_id,batch_key=batch_key,status='running',details={'attempts':attempts})
                connection.execute(statement.on_conflict_do_update(index_elements=[batches.c.run_id,batches.c.batch_key], set_={'status':'running','details':statement.excluded.details}))
                batch_results = []
                if batch_key == 'reports':
                    report_counts = refresh_reports(connection, plan.reports, ReportScope(plan.window.start_date,
                        plan.window.end_date, plan.facility_codes, organization_id=plan.organization_id))
                    batch_results = [SeedResult(name, count, count) for name,count in report_counts.items()]
                elif batch_key == 'references':
                    if plan.operation == 'full-reset':
                        connection.execute(coverage.delete().where(coverage.c.dataset.in_(('admissions','discharges','payer_changes','bed_holds'))))
                    context = SeedContext(connection, plan.window, batch_size=plan.batch_size, log=log,
                        facility_codes=plan.facility_codes, entity_ids=plan.entity_ids, scenario_key=plan.scenario_key,
                        operation=plan.operation, changed_fields=plan.changed_fields)
                    for name in references:
                        result = source_registry[name].seed(context)
                        source_registry[name].validate(context, result)
                        batch_results.append(result)
                    changed = [result.name for result in batch_results if result.changed_rows]
                    if 'payers' in changed:
                        from reporting.projections.payer_labels import refresh_payer_labels
                        refresh_payer_labels(connection,plan.organization_id)
                    if 'facilities' in changed:
                        from data.writers.legacy import sync_reference_data
                        sync_reference_data(connection, plan.facility_codes, plan.window.start_date, plan.window.end_date,
                            organization_id=plan.organization_id)
                    if changed and connection.scalar(select(func.count()).select_from(admissions)):
                        refresh_reports(connection, affected_reports(changed, plan.changed_fields or None),
                            ReportScope(plan.window.start_date,plan.window.end_date,plan.facility_codes,
                                organization_id=plan.organization_id))
                else:
                    retained = plan.window if plan.operation == 'full-reset' else _retained_window(connection, plan.window, (code,))
                    if plan.replacement and plan.replacement.start_date < retained.start_date:
                        raise ValueError('Requested repair begins before retained source history. Populate that explicitly before repairing it.')
                    scoped = replace(plan, window=retained)
                    _verify_dependencies(connection, scoped, code)
                    if plan.operation == 'full-reset':
                        from reporting.runner import clear_facility_history
                        clear_facility_history(connection,code)
                        _clear_owned_population(connection, code)
                    context = SeedContext(connection, retained, batch_size=plan.batch_size, log=log,
                        facility_codes=(code,), entity_ids=plan.entity_ids, scenario_key=plan.scenario_key,
                        operation=plan.operation, replace_window=plan.replacement)
                    if plan.backfill:
                        from seeding.backfills import run_backfill
                        result = run_backfill(plan.backfill, context, organization_id=plan.organization_id)
                        batch_results.append(result)
                    else:
                        for name in history:
                            step_started = perf_counter()
                            current = replace(context, rebuild=name in plan.rebuilds)
                            result = source_registry[name].seed(current)
                            source_registry[name].validate(current, result)
                            timings[name] = round(perf_counter() - step_started, 2)
                            batch_results.append(result)
                            if result.new_admission_ids:
                                context = replace(context, new_admission_ids=result.new_admission_ids)
                            if result.changed_from:
                                context = replace(context, changed_from=min(context.changed_from or result.changed_from,result.changed_from))
                    changed = any(result.changed_rows for result in batch_results)
                    missing_reports = _missing_reporting(connection, plan.reports, code, retained)
                    if changed:
                        step_started = perf_counter()
                        from data.writers.legacy import sync_sources
                        dirty_from = context.changed_from or min((result.changed_from for result in batch_results if result.changed_from), default=retained.start_date)
                        source_changes = {result.name for result in batch_results if result.changed_rows}
                        if plan.backfill != 'canonical_sources' and (plan.backfill or source_changes & {'admissions','discharges','payer_changes'}):
                            sync_sources(connection, (code,), dirty_from, retained.end_date, organization_id=plan.organization_id)
                        from reporting.projections.payer_labels import refresh_payer_labels
                        refresh_payer_labels(connection,plan.organization_id, facility_codes=(code,))
                        timings['canonical_sync'] = round(perf_counter() - step_started, 2)
                        if missing_reports:
                            dirty_from = retained.start_date
                        step_started = perf_counter()
                        refresh_reports(connection, plan.reports, ReportScope(dirty_from,retained.end_date,
                            (code,), organization_id=plan.organization_id))
                        timings['reporting'] = round(perf_counter() - step_started, 2)
                    elif missing_reports:
                        refresh_reports(connection, missing_reports, ReportScope(retained.start_date,retained.end_date,
                            (code,),organization_id=plan.organization_id))
                details = {'attempts':attempts, 'timings_seconds': timings, 'results': [{'dataset':item.name,'rows':item.row_count,'changed':item.changed_rows} for item in batch_results]}
                connection.execute(batches.update().where(batches.c.run_id == run_id, batches.c.batch_key == batch_key)
                    .values(status='complete', details=details, updated_at=func.now()))
                results.extend(batch_results)
            current_batch = None
            log(f'  {batch_key}: finished in {perf_counter() - batch_started:.2f}s.')
        with database.begin() as connection:
            connection.execute(runs.update().where(runs.c.run_id == run_id).values(status='complete',finished_at=func.now()))
    except BaseException as error:
        with database.begin() as connection:
            if current_batch:
                prior = connection.execute(select(batches).where(batches.c.run_id == run_id,batches.c.batch_key == current_batch)).mappings().one_or_none()
                attempts = (prior['details'].get('attempts',0) if prior else 0) + 1
                failure = insert(batches).values(run_id=run_id,batch_key=current_batch,status='failed',
                    details={'attempts':attempts,'error_type':type(error).__name__})
                connection.execute(failure.on_conflict_do_update(index_elements=[batches.c.run_id,batches.c.batch_key],
                    set_={'status':'failed','details':failure.excluded.details,'updated_at':func.now()},where=batches.c.status != 'complete'))
            connection.execute(runs.update().where(runs.c.run_id == run_id).values(status='failed',finished_at=func.now(),error_type=type(error).__name__))
        log(f'Run {run_id} stopped; completed facility batches remain committed. Resume this run ID to continue.')
        raise
    log(f'Run {run_id} complete.')
    # Preserve legacy callers which expect one result per named dataset.
    totals = {}
    for result in results:
        previous = totals.get(result.name, SeedResult(result.name,0,0))
        totals[result.name] = SeedResult(result.name,previous.row_count+result.row_count,previous.changed_rows+result.changed_rows)
    return list(totals.values())


def run_seeders(**kwargs):
    """New loads use dataset stages; old saved plans keep their recovery semantics."""
    legacy = kwargs.get('operation') == 'refresh'
    if kwargs.get('resume_run_id'):
        database = kwargs.get('engine') if kwargs.get('engine') is not None else get_engine()
        with database.connect() as connection:
            saved = connection.scalar(select(runs.c.plan).where(runs.c.run_id == kwargs['resume_run_id']))
        if saved is None:
            raise ValueError('Unknown seed run ID.')
        with database.connect() as connection:
            status = connection.scalar(select(runs.c.status).where(runs.c.run_id == kwargs['resume_run_id']))
        if status == 'superseded':
            raise ValueError('This run was superseded by a full reset and cannot be resumed.')
        legacy = saved.get('pipeline_version', 1) == 1 or saved.get('operation') == 'refresh'
        if saved.get('pipeline_version') == 2 and not legacy:
            from seeding.legacy_phased import run_phased
            return run_phased(**kwargs)
    if legacy:
        if kwargs.pop('sources_only', False):
            raise ValueError('--sources-only is available for new source-stage runs only.')
        return _run_legacy_seeders(**kwargs)
    from seeding.phased import run_phased
    return run_phased(**kwargs)
