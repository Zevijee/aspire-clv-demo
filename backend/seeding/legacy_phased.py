"""Version-2 recovery only; new runs use the resident-first pipeline."""
from dataclasses import replace
from datetime import date
from time import perf_counter
from uuid import uuid4
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert
from data.db import get_engine
from data.locking import lock_source_scope
from data.migrations.__main__ import require_schema
from data.models.seed_tracking import runs
from data.models.seed_operations import batches
from data.models.reporting_publication import loads
from data.models.facilities import facilities
from seeding.base import SeedContext, SeedResult, SeedWindow
from seeding.planner import build_plan
from seeding.state.target import require_demo_target


def run_phased(*, as_of=None, rebuild=False, targets=None, engine=None, registry=None, log=print,
               operation=None, history_months=36, replace_from=None, facility_codes=(), entity_ids=(),
               organization_id='aspire-demo', scenario_key='aspire-demo', versions=None, changed_fields=(),
               backfill=None, batch_size=1000, concurrency=1, resume_run_id=None, demo_instance=None,
               sources_only=False):
    from seeding.runner import (_lock, _retained_window, _resume_plan, _protect_source_ownership,
        _verify_dependencies, _clear_owned_population, _missing_reporting)
    from seeding.registry import SOURCES, default_registry
    database = engine if engine is not None else get_engine()
    run_id = resume_run_id or str(uuid4())
    plan = None if resume_run_id else build_plan(operation or ('rebuild' if rebuild else 'update'), targets,
        as_of, history_months, replace_from, facility_codes=facility_codes, entity_ids=entity_ids,
        organization_id=organization_id, scenario_key=scenario_key, versions=versions,
        changed_fields=changed_fields, backfill=backfill, batch_size=batch_size, concurrency=concurrency)
    with database.begin() as connection:
        require_schema(connection)
        require_demo_target(connection, demo_instance)
        if resume_run_id:
            recorded = connection.execute(select(runs).where(runs.c.run_id == run_id).with_for_update()).mappings().one_or_none()
            if not recorded or recorded['status'] in ('complete', 'superseded'):
                raise ValueError('Resume requires an incomplete run.')
            plan = _resume_plan(recorded['plan'])
            sources_only = recorded['plan'].get('sources_only', False)
            actual = {name: SOURCES[name].version for name in plan.sources} if not plan.backfill else {plan.backfill: '1'}
            if actual != dict(plan.versions):
                raise ValueError('Generator versions changed; cannot resume this plan.')
        else:
            codes = plan.facility_codes
            if not codes:
                codes = tuple(connection.scalars(select(facilities.c.facility_code).where(
                    facilities.c.organization_id == plan.organization_id).order_by(facilities.c.facility_code)))
                if not codes or 'facilities' in plan.sources:
                    from seeding.reference_data.facilities import build_facility_rows
                    codes = tuple(row['facility_code'] for row in build_facility_rows())
            if not codes:
                raise ValueError('No facilities selected.')
            plan = replace(plan, facility_codes=codes)
            _protect_source_ownership(connection, plan)
            if plan.entity_ids and plan.backfill == 'hospital_assignments':
                from data.models.admissions import admissions
                interval = plan.replacement or plan.window
                found = set(connection.scalars(select(admissions.c.admission_id).where(
                    admissions.c.admission_id.in_(plan.entity_ids), admissions.c.facility_code.in_(codes),
                    admissions.c.admission_source_type == 'Hospital',
                    admissions.c.admission_date.between(interval.start_date, interval.end_date))))
                if found != set(plan.entity_ids):
                    raise ValueError('An admission ID is outside the selected hospital/facility/date scope.')
        lock_source_scope(connection, plan.organization_id)
        pending = connection.scalar(select(loads.c.load_id).where(loads.c.organization_id == plan.organization_id,
            loads.c.status.not_in(('complete', 'superseded')), loads.c.load_id != run_id).limit(1))
        if pending:
            raise ValueError(f'Source load {pending} is unfinished. Resume it or finish its reporting first.')
        if not resume_run_id:
            description = dict(plan.describe(), pipeline_version=2, sources_only=sources_only, source_order=list(plan.sources))
            connection.execute(runs.insert().values(run_id=run_id, status='running', operation=plan.operation, plan=description))
            connection.execute(loads.insert().values(load_id=run_id, organization_id=plan.organization_id,
                status='loading', scope={'tasks': []}))
            from data.models.admissions_reporting import state
            connection.execute(state.update().where(state.c.id == 1).values(ready=False, revision=state.c.revision + 1))
        else:
            connection.execute(runs.update().where(runs.c.run_id == run_id).values(status='running', error_type=None, finished_at=None))
    source_registry = {item.name: item for item in (registry if registry is not None else default_registry())}
    references = [name for name in plan.sources if not SOURCES[name].date_based]
    history = [name for name in plan.sources if SOURCES[name].date_based]
    work = [(f'reference:{name}', name, None) for name in references]
    if plan.operation == 'full-reset':
        work += [(f'reset:{code}', 'reset', code) for code in plan.facility_codes]
    if plan.backfill:
        work += [(f'backfill:{code}', 'backfill', code) for code in plan.facility_codes]
    else:
        work += [(f'{name}:{code}', name, code) for name in history for code in plan.facility_codes]
    if history or plan.backfill:
        work += [(f'residents:{code}', 'residents', code) for code in plan.facility_codes]
    work += [(f'canonical:{code}', 'canonical', code) for code in plan.facility_codes]
    current_batch = None
    results = []
    windows = {}
    with database.connect() as connection:
        completed = {row['batch_key']: row['details'] for row in connection.execute(select(batches).where(
            batches.c.run_id == run_id, batches.c.status == 'complete')).mappings()}
    log(f'Run {run_id}: source data first; reporting second; {len(plan.facility_codes)} facilities.')
    try:
        for batch_key, name, code in work:
            if batch_key in completed:
                continue
            current_batch = batch_key
            started = perf_counter()
            with database.begin() as connection:
                require_demo_target(connection, demo_instance)
                _lock(connection, 'run:' + run_id)
                lock_source_scope(connection, plan.organization_id)
                prior = connection.execute(select(batches).where(batches.c.run_id == run_id,
                    batches.c.batch_key == batch_key, batches.c.status == 'complete')).mappings().one_or_none()
                if prior:
                    completed[batch_key] = prior['details']
                    continue
                _protect_source_ownership(connection, replace(plan, facility_codes=(code,)) if code else plan)
                if code not in windows:
                    windows[code] = plan.window if not code or plan.operation == 'full-reset' else _retained_window(connection, plan.window, (code,))
                window = windows[code]
                if plan.replacement and plan.replacement.start_date < window.start_date:
                    raise ValueError('Repair starts before retained source history.')
                upstream = [value for key, value in completed.items() if code and key.endswith(':' + code)]
                dirty = [date.fromisoformat(value['changed_from']) for value in upstream if value.get('changed_from')]
                new_ids = completed.get(f'admissions:{code}', {}).get('new_admission_ids', [])
                context = SeedContext(connection, window, batch_size=plan.batch_size, log=log,
                    facility_codes=(code,) if code else plan.facility_codes, entity_ids=plan.entity_ids,
                    scenario_key=plan.scenario_key, operation=plan.operation, changed_fields=plan.changed_fields,
                    rebuild=name in plan.rebuilds, replace_window=plan.replacement,
                    new_admission_ids=tuple(new_ids), changed_from=min(dirty) if dirty else None)
                detail = {'through': window.end_date.isoformat(), 'from': window.start_date.isoformat()}
                result = SeedResult(name, 0, 0)
                if name == 'reset':
                    _clear_owned_population(connection, code)
                    detail['changed_from'] = window.start_date.isoformat()
                elif name == 'residents':
                    if dirty:
                        from data.writers.legacy import sync_residents
                        result = SeedResult(name, sync_residents(connection, (code,), organization_id=plan.organization_id), 0)
                elif name == 'canonical':
                    from data.models.stays import census
                    has_history = connection.scalar(select(census.c.census_date).where(census.c.facility_code == code).limit(1)) is not None
                    reference_changed = any(value.get('changed_rows') for key, value in completed.items() if key.startswith('reference:'))
                    changed = bool(dirty) or (reference_changed and has_history)
                    missing = _missing_reporting(connection, plan.reports, code, window) if has_history else ()
                    if changed:
                        from data.writers.legacy import sync_sources
                        from reporting.projections.payer_labels import refresh_payer_labels
                        if plan.backfill != 'canonical_sources' and (history or plan.backfill):
                            sync_sources(connection, (code,), min(dirty) if dirty else window.start_date,
                                window.end_date, organization_id=plan.organization_id,
                                residents_prepared=bool(dirty) and f'residents:{code}' in completed)
                        refresh_payer_labels(connection, plan.organization_id, facility_codes=(code,))
                    if changed or missing:
                        detail['report_from'] = (window.start_date if missing or reference_changed else min(dirty)).isoformat()
                elif name == 'backfill':
                    from seeding.backfills import run_backfill
                    result = run_backfill(plan.backfill, context, organization_id=plan.organization_id)
                else:
                    if code:
                        # Validate dependencies of this stage, including prior stages committed in this run.
                        _verify_dependencies(connection, replace(plan, window=window, sources=(name,)), code)
                    result = source_registry[name].seed(context)
                    source_registry[name].validate(context, result)
                    if name == 'facilities':
                        from data.writers.legacy import sync_reference_data
                        sync_reference_data(connection, plan.facility_codes, window.start_date, window.end_date,
                            organization_id=plan.organization_id)
                detail.update(changed_rows=result.changed_rows, rows=result.row_count,
                    new_admission_ids=list(result.new_admission_ids), seconds=round(perf_counter()-started, 2))
                if result.changed_rows:
                    detail['changed_from'] = (result.changed_from or window.start_date).isoformat()
                statement = insert(batches).values(run_id=run_id, batch_key=batch_key, status='complete', details=detail)
                connection.execute(statement.on_conflict_do_update(index_elements=[batches.c.run_id, batches.c.batch_key],
                    set_={'status':'complete', 'details':detail, 'updated_at':func.now()}))
                results.append(result)
            current_batch = None
            completed[batch_key] = detail
            log(f'  {batch_key}: finished in {perf_counter()-started:.2f}s.')
        with database.begin() as connection:
            lock_source_scope(connection, plan.organization_id)
            groups = {}
            for row in connection.execute(select(batches).where(batches.c.run_id == run_id,
                    batches.c.status == 'complete', batches.c.batch_key.like('canonical:%'))).mappings():
                detail = row['details']
                if detail.get('report_from'):
                    groups.setdefault((detail['report_from'], detail['through']), []).append(row['batch_key'].split(':', 1)[1])
            tasks = [{'from': start, 'through': end, 'facilities': codes, 'reports': list(plan.reports)}
                     for (start, end), codes in sorted(groups.items())]
            connection.execute(loads.update().where(loads.c.load_id == run_id, loads.c.status != 'complete').values(
                status='sources_complete', scope={'tasks':tasks, 'replace_history': plan.operation == 'full-reset'}, updated_at=func.now()))
        if not sources_only:
            from reporting.publication.loads import finish_load
            started = perf_counter()
            with database.begin() as connection:
                finish_load(connection, run_id)
            log(f'  reporting: finished in {perf_counter()-started:.2f}s.')
        with database.begin() as connection:
            connection.execute(runs.update().where(runs.c.run_id == run_id).values(status='complete', finished_at=func.now()))
    except BaseException as error:
        with database.begin() as connection:
            connection.execute(runs.update().where(runs.c.run_id == run_id).values(status='failed',
                error_type=type(error).__name__, finished_at=func.now()))
        log(f'Run {run_id} stopped at {current_batch or "reporting"}; resume retains completed source stages.')
        raise
    log(f'Sources complete. Build reports with python -m reporting --load-id {run_id}' if sources_only else f'Run {run_id} complete.')
    totals = {}
    for result in results:
        prior = totals.get(result.name, SeedResult(result.name, 0, 0))
        totals[result.name] = SeedResult(result.name, prior.row_count + result.row_count,
            prior.changed_rows + result.changed_rows)
    return list(totals.values())
