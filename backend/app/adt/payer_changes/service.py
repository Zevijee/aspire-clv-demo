"""Aggregate additive payer-change facts in PostgreSQL.

Same rules as admissions and discharges: parent scopes are GROUP BY results over
the facility grain, absence of a row means zero, and completeness comes from the
seeder's date checkpoints.

Residents affected is the exception. It is a distinct count, so it cannot come
from the fact table -- a resident who changes payer twice in a period would be
counted twice by any sum of per-day rows. It is counted live from
payer_change_logs, which already carries the resident and the facility on each
change and so needs none of the joins the raw payer periods did.
"""
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import distinct, func, select, tuple_
from sqlalchemy.engine import Connection

from shared.database.schema import (
    daily_payer_change_facts as facts, daily_runs, facilities,
    payer_change_logs as changes, payers, portfolios, regions)
from ...common.errors import ApiError
from ...common.locations import LocationSelection, facility_locations
from .schemas import OverviewQuery

GENERATOR = 'payer_changes_summary'
ZERO = dict(changes=0)


def _level_id(level):
    """The grouping key only; names come from the resolved location paths."""
    return {
        'facility': facts.c.facility_id,
        'region': facilities.c.region_id,
        'portfolio': regions.c.portfolio_id,
        'state': portfolios.c.state,
    }[level]


def _source(level=None):
    source = facts
    chain = {'facility': 0, 'region': 1, 'portfolio': 2, 'state': 3}.get(level, 0)
    if chain >= 1:
        source = source.join(facilities, facts.c.facility_id == facilities.c.facility_id)
    if chain >= 2:
        source = source.join(regions, facilities.c.region_id == regions.c.region_id)
    if chain >= 3:
        source = source.join(portfolios, regions.c.portfolio_id == portfolios.c.portfolio_id)
    return source


def _conditions(query, facility_ids):
    """Selections narrow data; they are not an access-control boundary."""
    conditions = [facts.c.summary_date.between(query.start_date, query.end_date)]
    if facility_ids is not None:
        conditions.append(facts.c.facility_id.in_(facility_ids))
    if query.type_changes_only:
        conditions.append(facts.c.previous_payer_type != facts.c.new_payer_type)
    if query.payer_types:
        conditions.append(facts.c.new_payer_type.in_(query.payer_types))
    if query.previous_payer_types:
        conditions.append(facts.c.previous_payer_type.in_(query.previous_payer_types))
    return conditions


def _metrics(row, days):
    changes = row['changes']
    return dict(changes=changes, average_per_day=round(changes / days, 2))


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
    """Completeness is the seeder's committed checkpoints, not row presence."""
    first, last, generated_at = connection.execute(select(
        func.min(daily_runs.c.simulation_date), func.max(daily_runs.c.simulation_date),
        func.max(daily_runs.c.completed_at)).where(daily_runs.c.generator == GENERATOR)).one()
    covered = connection.scalar(select(func.count()).select_from(daily_runs).where(
        daily_runs.c.generator == GENERATOR,
        daily_runs.c.simulation_date.between(query.start_date, query.end_date)))
    if covered != query.days:
        available = f'{first} through {last}' if first is not None else 'no completed dates'
        raise ApiError('summary_unavailable', f'Payer change facts are available for {available}. '
            'The requested period includes missing days. Run the seeder update or select completed dates.', 409)
    return first, last, generated_at


def _resident_counts(connection, query, facility_ids, group_by):
    """Exact distinct residents per scope, counted from the payer change logs.

    A COUNT(DISTINCT) cannot be rolled up from stored per-day rows, so it is
    counted live. It reads payer_change_logs rather than res_payer_stays: the
    log row already carries the resident, the facility and whether the move
    crossed payer types, so none of the joins the source needed are required.
    """
    source = (changes
        .join(facilities, facilities.c.facility_id == changes.c.facility_id)
        .join(regions, regions.c.region_id == facilities.c.region_id)
        .join(portfolios, portfolios.c.portfolio_id == regions.c.portfolio_id))
    conditions = [changes.c.change_date.between(query.start_date, query.end_date)]
    if facility_ids is not None:
        conditions.append(changes.c.facility_id.in_(facility_ids))
    if query.type_changes_only:
        conditions.append(changes.c.is_type_change)
    if query.payer_types or query.previous_payer_types:
        new_payer = payers.alias('new_payer')
        previous_payer = payers.alias('previous_payer')
        source = (source
            .join(new_payer, new_payer.c.payer_id == changes.c.new_payer_id)
            .join(previous_payer, previous_payer.c.payer_id == changes.c.previous_payer_id))
        if query.payer_types:
            conditions.append(new_payer.c.payer_type.in_(query.payer_types))
        if query.previous_payer_types:
            conditions.append(previous_payer.c.payer_type.in_(query.previous_payer_types))
    scope = {'facility': changes.c.facility_id, 'region': facilities.c.region_id,
        'portfolio': regions.c.portfolio_id, 'state': portfolios.c.state}[group_by]
    residents = func.count(distinct(changes.c.resident_id))
    rows = connection.execute(select(scope.label('scope'), residents.label('residents'))
        .select_from(source).where(*conditions).group_by(scope)).mappings().all()
    total = connection.scalar(select(residents).select_from(source).where(*conditions)) or 0
    return {str(row['scope']): row['residents'] for row in rows}, total


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
    every = _conditions(query, facility_ids)
    id_column = _level_id(query.group_by)
    change_count = func.coalesce(func.sum(facts.c.changes), 0).label('changes')

    # Totals, daily trend and location rows share one scan through grouping sets.
    grouped_rows = connection.execute(select(
        id_column.label('scope'), facts.c.summary_date,
        func.grouping(id_column).label('no_scope'),
        func.grouping(facts.c.summary_date).label('no_date'), change_count)
        .select_from(_source(query.group_by)).where(*every)
        .group_by(func.grouping_sets(tuple_(), tuple_(id_column), tuple_(facts.c.summary_date)))
    ).mappings().all()
    total_row = next(row for row in grouped_rows if row['no_scope'] and row['no_date'])
    daily_rows = {row['summary_date']: row for row in grouped_rows if not row['no_date']}
    location_rows = {str(row['scope']): row for row in grouped_rows if not row['no_scope']}

    # The transition matrix drives the donuts: one row per from/to payer pair.
    transitions = connection.execute(select(
        facts.c.previous_payer_type, facts.c.new_payer_type, change_count)
        .where(*every).group_by(facts.c.previous_payer_type, facts.c.new_payer_type)).mappings().all()

    residents_by_scope, residents_total = _resident_counts(
        connection, query, facility_ids, query.group_by)

    return dict(
        range=dict(start=query.start_date, end=query.end_date, days=days), group_by=query.group_by,
        totals=_metrics(total_row, days), residents=residents_total,
        locations=[dict(id=key[1], level=key[0], name=paths[key][-1]['name'], path=paths[key],
            facility_ids=sorted(groups[key]), residents=residents_by_scope.get(key[1], 0),
            **_metrics(location_rows.get(key[1], ZERO), days))
            for key in sorted(groups, key=lambda key: (paths[key][-1]['name'], key))],
        transitions=[dict(previous_payer_type=row['previous_payer_type'],
            new_payer_type=row['new_payer_type'], changes=row['changes'])
            for row in sorted(transitions, key=lambda row:
                (row['previous_payer_type'], row['new_payer_type']))],
        daily=[dict(date=day, **_metrics(daily_rows.get(day, ZERO), 1))
            for day in (query.start_date + timedelta(days=index) for index in range(days))],
        data_status=dict(complete=True, available_from=first, available_through=last,
            generated_at=generated_at, schema_version=1),
    )
