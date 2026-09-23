"""Aggregate additive discharge facts in PostgreSQL.

Same rules as admissions: parent scopes are GROUP BY results over the facility
grain, absence of a row means zero, and completeness comes from the seeder's date
checkpoints. Length of stay is summed and divided once — never averaged from
per-row averages, which is wrong at every level above facility.
"""
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import case, func, select, tuple_
from sqlalchemy.engine import Connection

from shared.database.schema import (
    daily_discharge_facts as facts, daily_runs, facilities,
    monthly_discharge_facts as months, payers, portfolios, regions)
from ...common.errors import ApiError
from ...common.locations import LocationSelection, facility_locations
from .schemas import OverviewQuery

GENERATOR = 'discharges_summary'
ZERO = dict(discharges=0, hospital_transfers=0, ama_discharges=0,
    deceased_discharges=0, length_of_stay_days=0)


def _measures():
    """Additive sums only. Every displayed metric divides these, never the reverse."""
    # Transfers and deaths are the destination, so they need no stored measure.
    destined = lambda kind: func.coalesce(func.sum(  # noqa: E731 - one expression, read inline
        case((facts.c.destination_type == kind, facts.c.discharges), else_=0)), 0)
    return (
        func.coalesce(func.sum(facts.c.discharges), 0).label('discharges'),
        destined('Hospital').label('hospital_transfers'),
        func.coalesce(func.sum(facts.c.ama_discharges), 0).label('ama_discharges'),
        destined('Funeral Home').label('deceased_discharges'),
        func.coalesce(func.sum(facts.c.length_of_stay_days), 0).label('length_of_stay_days'),
    )


def _level_id(level):
    """The grouping key only; names come from the resolved location paths."""
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


def _conditions(query, facility_ids, *, apply_payer=True, apply_destination=True):
    """Selections narrow data; they are not an access-control boundary."""
    conditions = [facts.c.summary_date.between(query.start_date, query.end_date)]
    if facility_ids is not None:
        conditions.append(facts.c.facility_id.in_(facility_ids))
    if apply_payer and query.payer_types:
        # Resolve payer types through a subquery so the fact scan needs no join.
        conditions.append(facts.c.payer_id.in_(
            select(payers.c.payer_id).where(payers.c.payer_type.in_(query.payer_types))))
    if apply_destination and query.destination_types:
        conditions.append(facts.c.destination_type.in_(query.destination_types))
    return conditions


def _grouped(connection, columns, conditions, *, group_by, source=None):
    statement = (select(*columns).select_from(source if source is not None else facts)
        .where(*conditions).group_by(*group_by))
    return connection.execute(statement).mappings().all()


def _metrics(row, days):
    discharges = row['discharges']
    stay_days = row['length_of_stay_days']
    return dict(discharges=discharges, hospital_transfers=row['hospital_transfers'],
        ama_discharges=row['ama_discharges'], deceased_discharges=row['deceased_discharges'],
        length_of_stay_days=stay_days,
        # Sum and divide once. A mean of per-facility means is not the group mean.
        average_length_of_stay=round(stay_days / discharges, 2) if discharges else 0.0,
        average_per_day=round(discharges / days, 2))


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
        raise ApiError('summary_unavailable', f'Discharge facts are available for {available}. '
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
    every = _conditions(query, facility_ids)
    id_column = _level_id(query.group_by)
    level_source = _source(query.group_by)
    discharges = func.sum(facts.c.discharges).label('discharges')

    # Totals, daily trend and location rows share one scan through grouping sets.
    grouped_rows = _grouped(connection,
        (id_column.label('scope'), facts.c.summary_date,
         func.grouping(id_column).label('no_scope'),
         func.grouping(facts.c.summary_date).label('no_date'), *_measures()),
        every, source=level_source,
        group_by=[func.grouping_sets(tuple_(), tuple_(id_column), tuple_(facts.c.summary_date))])
    total_row = next(row for row in grouped_rows if row['no_scope'] and row['no_date'])
    daily_rows = {row['summary_date']: row for row in grouped_rows if not row['no_date']}
    location_rows = {str(row['scope']): row for row in grouped_rows if not row['no_scope']}

    # Interactive facets omit their own filter and retain the others.
    by_payer = _grouped(connection, (payers.c.payer_type, discharges),
        _conditions(query, facility_ids, apply_payer=False),
        source=_source(payer_type=True), group_by=[payers.c.payer_type])
    by_destination = _grouped(connection, (facts.c.destination_type, discharges),
        _conditions(query, facility_ids, apply_destination=False),
        group_by=[facts.c.destination_type])

    return dict(
        range=dict(start=query.start_date, end=query.end_date, days=days), group_by=query.group_by,
        totals=_metrics(total_row, days),
        locations=[dict(id=key[1], level=key[0], name=paths[key][-1]['name'], path=paths[key],
            facility_ids=sorted(groups[key]),
            **_metrics(location_rows.get(key[1], ZERO), days))
            for key in sorted(groups, key=lambda key: (paths[key][-1]['name'], key))],
        by_payer=[dict(payer_type=row['payer_type'], discharges=row['discharges'])
            for row in sorted(by_payer, key=lambda row: row['payer_type'])],
        by_destination=[dict(destination_type=row['destination_type'], discharges=row['discharges'])
            for row in sorted(by_destination, key=lambda row: row['destination_type'])],
        # Disjoint by construction, so Routine is the remainder and the four sum
        # to total discharges. Derived from the totals rather than queried again.
        by_disposition=[dict(discharge_type=kind, discharges=count) for kind, count in (
            ('AMA', total_row['ama_discharges']),
            ('Expired', total_row['deceased_discharges']),
            ('Routine', total_row['discharges'] - total_row['hospital_transfers']
                - total_row['ama_discharges'] - total_row['deceased_discharges']),
            ('Transfer', total_row['hospital_transfers']))],
        daily=[dict(date=day, **_metrics(daily_rows.get(day, ZERO), 1))
            for day in (query.start_date + timedelta(days=index) for index in range(days))],
        data_status=dict(complete=True, available_from=first, available_through=last,
            generated_at=generated_at, schema_version=1),
    )


def _monthly_conditions(query, facility_ids, *, apply_destination=True):
    conditions = [months.c.month_start.between(
        query.start_date.replace(day=1), query.end_date)]
    if facility_ids is not None:
        conditions.append(months.c.facility_id.in_(facility_ids))
    if query.payer_types:
        conditions.append(months.c.payer_type.in_(query.payer_types))
    if apply_destination and query.destination_types:
        conditions.append(months.c.destination_type.in_(query.destination_types))
    return conditions


def _daily_conditions(query, facility_ids):
    """The day series stays on the daily table: a month-grain rollup cannot
    answer the report's highest and lowest day columns."""
    conditions = [facts.c.summary_date.between(query.start_date, query.end_date)]
    if facility_ids is not None:
        conditions.append(facts.c.facility_id.in_(facility_ids))
    if query.payer_types:
        conditions.append(facts.c.payer_id.in_(
            select(payers.c.payer_id).where(payers.c.payer_type.in_(query.payer_types))))
    if query.destination_types:
        conditions.append(facts.c.destination_type.in_(query.destination_types))
    return conditions


def _selected_facility_ids(connection, query):
    all_rows = connection.execute(facility_locations(LocationSelection())).mappings().all()
    selected = ([] if query.match_none else
        connection.execute(facility_locations(query)).mappings().all())
    if selected and len(selected) == len(all_rows):
        return None, selected
    return sorted(row['facility_id'] for row in selected), selected


def monthly_trend(connection: Connection, query):
    """Monthly discharges by destination, with their days nested.

    The admissions mirror image, reading monthly_discharge_facts. The days come
    from the daily table because the report shows the highest and lowest day in
    each month, which no month-grain table can answer.
    """
    _coverage(connection, query)
    facility_ids, _ = _selected_facility_ids(connection, query)
    summed = func.coalesce(func.sum(months.c.discharges), 0).label('discharges')

    totals = {row['month_start']: row['discharges'] for row in connection.execute(
        select(months.c.month_start, summed)
        .where(*_monthly_conditions(query, facility_ids))
        .group_by(months.c.month_start)).mappings()}

    # The destination breakdown drops its own filter, so the control keeps
    # showing what the selection is being compared against.
    by_destination = connection.execute(select(months.c.destination_type, summed)
        .where(*_monthly_conditions(query, facility_ids, apply_destination=False))
        .group_by(months.c.destination_type)).mappings().all()

    days = defaultdict(list)
    for row in connection.execute(select(
            facts.c.summary_date, func.coalesce(func.sum(facts.c.discharges), 0).label('discharges'))
            .where(*_daily_conditions(query, facility_ids))
            .group_by(facts.c.summary_date).order_by(facts.c.summary_date)).mappings():
        days[row['summary_date'].replace(day=1)].append(
            dict(date=row['summary_date'], discharges=row['discharges']))

    trend = []
    for month_start in sorted(totals):
        inside = days.get(month_start, [])
        trend.append(dict(
            month=month_start.strftime('%Y-%m'), date=month_start,
            end_date=inside[-1]['date'] if inside else month_start,
            discharges=totals[month_start], days=inside))
    return dict(months=trend, by_destination=[
        dict(destination_type=row['destination_type'], discharges=row['discharges'])
        for row in sorted(by_destination, key=lambda row: row['destination_type'])])


def monthly_locations(connection: Connection, query):
    """Per-facility monthly discharges, under the same filters as the trend."""
    _coverage(connection, query)
    facility_ids, selected = _selected_facility_ids(connection, query)
    locations = [dict(facility_id=row['facility_id'], facility_name=row['facility_name'],
        state=row['state'], portfolio=row['portfolio_name'], region=row['region_name'])
        for row in selected]
    if not locations:
        return dict(locations=[], items=[])
    rows = connection.execute(select(
        months.c.facility_id, func.to_char(months.c.month_start, 'YYYY-MM').label('month'),
        func.coalesce(func.sum(months.c.discharges), 0).label('discharges'))
        .where(*_monthly_conditions(query, facility_ids))
        .group_by(months.c.facility_id, months.c.month_start)).mappings().all()
    return dict(locations=locations, items=[dict(row) for row in rows])
