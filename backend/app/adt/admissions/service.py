"""Aggregate additive admission facts in PostgreSQL.

Parent location totals are GROUP BY results over the facility grain, so a scope is
never combined with its own children and no scope-day needs to be stored. Absence
of a fact row means zero; completeness comes from the seeder's date checkpoints.
"""
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import func, select, tuple_
from sqlalchemy.engine import Connection

from shared.database.schema import (
    daily_admission_facts as facts, daily_runs, facilities, payers, portfolios, regions)
from ...common.errors import ApiError
from ...common.locations import LocationSelection, facility_locations
from .schemas import OverviewQuery

GENERATOR = 'admissions_summary'
ZERO = dict(admissions=0, readmissions=0, readmissions_30_day=0, medicaid_pending_admissions=0)


def _measures():
    """Additive sums only.

    Distinct referring hospitals is not additive, and counting it here costs more
    than every other aggregate combined. The hospital breakdown already lists the
    distinct names per scope, so totals and location rows count that instead; only
    the daily rows, which have no name breakdown, need their own distinct count.
    """
    return (
        func.coalesce(func.sum(facts.c.admissions), 0).label('admissions'),
        func.coalesce(func.sum(facts.c.readmissions), 0).label('readmissions'),
        func.coalesce(func.sum(facts.c.readmissions_30_day), 0).label('readmissions_30_day'),
        func.coalesce(func.sum(facts.c.medicaid_pending_admissions), 0).label('medicaid_pending_admissions'),
    )


def _level_id(level):
    """The grouping key only; display names come from the resolved location paths.

    Join no more of the hierarchy than the key needs. Facility ids are already on
    the fact rows, so grouping by facility joins nothing at all.
    """
    return {
        'facility': facts.c.facility_id,
        'region': facilities.c.region_id,
        'portfolio': regions.c.portfolio_id,
        'state': portfolios.c.state,
    }[level]


def _source(level=None, *, payer_type=False):
    source = facts
    chain = {'facility': 0, 'region': 1, 'portfolio': 2, 'state': 3}.get(level, 0)
    if chain >= 1:
        source = source.join(facilities, facts.c.facility_id == facilities.c.facility_id)
    if chain >= 2:
        source = source.join(regions, facilities.c.region_id == regions.c.region_id)
    if chain >= 3:
        source = source.join(portfolios, regions.c.portfolio_id == portfolios.c.portfolio_id)
    if payer_type:
        source = source.join(payers, facts.c.payer_id == payers.c.payer_id)
    return source


def _conditions(query, facility_ids, *, apply_payer=True, apply_source=True):
    """Selections narrow data; they are not an access-control boundary."""
    conditions = [facts.c.summary_date.between(query.start_date, query.end_date)]
    if facility_ids is not None:
        conditions.append(facts.c.facility_id.in_(facility_ids))
    if apply_payer and query.payer_types:
        # Resolve payer types through a subquery so the fact scan needs no join.
        conditions.append(facts.c.payer_id.in_(
            select(payers.c.payer_id).where(payers.c.payer_type.in_(query.payer_types))))
    if apply_source and query.source_types:
        conditions.append(facts.c.source_type.in_(query.source_types))
    return conditions


def _grouped(connection, columns, conditions, *, group_by, source=None):
    statement = (select(*columns).select_from(source if source is not None else facts)
        .where(*conditions).group_by(*group_by))
    return connection.execute(statement).mappings().all()


def _metrics(row, days, referring_hospitals):
    return dict(admissions=row['admissions'], readmissions=row['readmissions'],
        readmissions_30_day=row['readmissions_30_day'],
        medicaid_pending_admissions=row['medicaid_pending_admissions'],
        referring_hospitals=referring_hospitals,
        average_per_day=round(row['admissions'] / days, 2))


def _hospital_rows(counts):
    return [dict(hospital_name=name, admissions=count)
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


def _hierarchy(rows):
    members, paths = defaultdict(set), {}
    for row in rows:
        path = [dict(level='state', id=row['state'], name=row['state']),
            dict(level='portfolio', id=str(row['portfolio_id']), name=row['portfolio_name']),
            dict(level='region', id=str(row['region_id']), name=row['region_name']),
            dict(level='facility', id=str(row['facility_id']), name=row['facility_name'])]
        for index, part in enumerate(path):
            key = (part['level'], part['id'])
            members[key].add(row['facility_id'])
            paths[key] = path[:index + 1]
    return members, paths


def _coverage(connection, query):
    """Completeness is the seeder's committed date checkpoints, not row presence.

    A completed day with no admissions has no fact rows and must read as zero.
    """
    first, last, generated_at = connection.execute(select(
        func.min(daily_runs.c.simulation_date), func.max(daily_runs.c.simulation_date),
        func.max(daily_runs.c.completed_at)).where(daily_runs.c.generator == GENERATOR)).one()
    covered = connection.scalar(select(func.count()).select_from(daily_runs).where(
        daily_runs.c.generator == GENERATOR,
        daily_runs.c.simulation_date.between(query.start_date, query.end_date)))
    if covered != query.days:
        available = f'{first} through {last}' if first is not None else 'no completed dates'
        raise ApiError('summary_unavailable', f'Admission facts are available for {available}. '
            'The requested period includes missing days. Run the seeder update or select completed dates.', 409)
    return first, last, generated_at


def overview(connection: Connection, query: OverviewQuery):
    first, last, generated_at = _coverage(connection, query)
    all_rows = connection.execute(facility_locations(LocationSelection())).mappings().all()
    selected = ([] if query.match_none else
        connection.execute(facility_locations(query)).mappings().all())
    selected_ids = {row['facility_id'] for row in selected}
    members, paths = _hierarchy(all_rows)
    groups = {key: ids & selected_ids for key, ids in members.items()
        if key[0] == query.group_by and ids & selected_ids}
    days = query.days

    # Skip the IN list when nothing is excluded; an empty selection matches nothing.
    facility_ids = (None if selected_ids and len(selected_ids) == len(all_rows)
        else sorted(selected_ids))
    both = _conditions(query, facility_ids)
    id_column = _level_id(query.group_by)
    level_source = _source(query.group_by)
    admissions = func.sum(facts.c.admissions).label('admissions')

    # Totals, daily trend and location rows share one scan through grouping sets.
    grouped_rows = _grouped(connection,
        (id_column.label('scope'), facts.c.summary_date,
         func.grouping(id_column).label('no_scope'),
         func.grouping(facts.c.summary_date).label('no_date'), *_measures()),
        both, source=level_source,
        group_by=[func.grouping_sets(tuple_(), tuple_(id_column), tuple_(facts.c.summary_date))])
    total_row = next(row for row in grouped_rows if row['no_scope'] and row['no_date'])
    daily_rows = {row['summary_date']: row for row in grouped_rows if not row['no_date']}
    location_rows = {str(row['scope']): row for row in grouped_rows if not row['no_scope']}

    # Hospital breakdowns overall and per location, also from one scan.
    hospital_filter = [*both, facts.c.source_type == 'Hospital']
    hospitals, location_hospitals = {}, defaultdict(dict)
    for row in _grouped(connection, (id_column.label('scope'), facts.c.source_name,
            func.grouping(id_column).label('no_scope'), admissions), hospital_filter,
            source=level_source,
            group_by=[func.grouping_sets(tuple_(facts.c.source_name),
                tuple_(id_column, facts.c.source_name))]):
        if row['no_scope']:
            hospitals[row['source_name']] = row['admissions']
        else:
            location_hospitals[str(row['scope'])][row['source_name']] = row['admissions']

    # Distinct hospitals per day, the one scope with no name breakdown to count.
    # Deduplicating first and counting rows beats COUNT(DISTINCT) per group, which
    # sorts inside every group.
    distinct_pairs = (select(facts.c.summary_date, facts.c.source_name)
        .where(*hospital_filter).distinct().subquery())
    daily_hospitals = {row['summary_date']: row['referring_hospitals']
        for row in connection.execute(
            select(distinct_pairs.c.summary_date, func.count().label('referring_hospitals'))
            .group_by(distinct_pairs.c.summary_date)).mappings()}

    # Interactive facets omit their own filter and retain the other.
    by_payer = _grouped(connection, (payers.c.payer_type, admissions),
        _conditions(query, facility_ids, apply_payer=False),
        source=_source(payer_type=True), group_by=[payers.c.payer_type])
    by_source = _grouped(connection, (facts.c.source_type, admissions),
        _conditions(query, facility_ids, apply_source=False), group_by=[facts.c.source_type])

    return dict(
        range=dict(start=query.start_date, end=query.end_date, days=days), group_by=query.group_by,
        totals=_metrics(total_row, days, len(hospitals)),
        locations=[dict(id=key[1], level=key[0], name=paths[key][-1]['name'], path=paths[key],
            facility_ids=sorted(groups[key]),
            hospitals=_hospital_rows(location_hospitals.get(key[1], {})),
            **_metrics(location_rows.get(key[1], ZERO), days, len(location_hospitals.get(key[1], {}))))
            for key in sorted(groups, key=lambda key: (paths[key][-1]['name'], key))],
        by_payer=[dict(payer_type=row['payer_type'], admissions=row['admissions'])
            for row in sorted(by_payer, key=lambda row: row['payer_type'])],
        by_source=[dict(source_type=row['source_type'], admissions=row['admissions'])
            for row in sorted(by_source, key=lambda row: row['source_type'])],
        hospitals=_hospital_rows(hospitals),
        daily=[dict(date=day, **_metrics(daily_rows.get(day, ZERO), 1, daily_hospitals.get(day, 0)))
            for day in (query.start_date + timedelta(days=index) for index in range(days))],
        data_status=dict(complete=True, available_from=first, available_through=last,
            generated_at=generated_at, schema_version=1),
    )
