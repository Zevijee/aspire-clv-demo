"""Aggregate daily payer census facts in PostgreSQL.

Movements are additive and sum over any set of rows. Census is not: it is a
level, not a flow, so opening comes from the first day of the range and closing
from the last. Summing census across days would count every resident once per
day they were present.

Net change is closing minus opening, which equals admissions + changes_in -
discharges - changes_out over the same rows. The table stores both sides and a
CHECK keeps them equal, so either can be used and they cannot drift.
"""
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import and_, case, func, select, tuple_
from sqlalchemy.engine import Connection

from shared.database.schema import (
    daily_payer_census_facts as facts, daily_runs, facilities,
    monthly_payer_census_facts as months, portfolios, regions)
from ...common.errors import ApiError
from ...common.locations import LocationSelection, facility_locations
from .schemas import MonthlyQuery, OverviewQuery

GENERATOR = 'net_change_summary'
ZERO = dict(opening_census=0, closing_census=0, admissions=0, discharges=0,
    payer_changes_in=0, payer_changes_out=0)


def _payer_filter(query):
    """The payer selection as an expression rather than a WHERE clause.

    The payer breakdown deliberately ignores the payer filter, so applying it in
    WHERE would force a second scan. Applied inside the aggregates instead, one
    scan can carry both the filtered report and the unfiltered breakdown.
    """
    return facts.c.payer_type.in_(query.payer_types) if query.payer_types else None


def _measures(query, *, apply_payer=True, prefix=''):
    """Flows sum over the range; census is read at the two boundary dates."""
    keep = _payer_filter(query) if apply_payer else None

    def summed(column):
        return func.coalesce(func.sum(
            column if keep is None else case((keep, column), else_=0)), 0)

    def at(column, day):
        on_day = facts.c.summary_date == day
        return func.coalesce(func.sum(
            case((on_day if keep is None else and_(on_day, keep), column), else_=0)), 0)

    return (
        at(facts.c.opening_census, query.start_date).label(prefix + 'opening_census'),
        at(facts.c.closing_census, query.end_date).label(prefix + 'closing_census'),
        summed(facts.c.admissions).label(prefix + 'admissions'),
        summed(facts.c.discharges).label(prefix + 'discharges'),
        summed(facts.c.changes_in).label(prefix + 'payer_changes_in'),
        summed(facts.c.changes_out).label(prefix + 'payer_changes_out'),
        # Grouped by date these two are that day's own opening and closing, which
        # the boundary-pinned pair above cannot express. Carried alongside so the
        # daily series needs no scan of its own.
        summed(facts.c.opening_census).label(prefix + 'day_opening'),
        summed(facts.c.closing_census).label(prefix + 'day_closing'),
    )


def _level_id(level):
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


def _conditions(query, facility_ids, *, apply_payer=True):
    conditions = [facts.c.summary_date.between(query.start_date, query.end_date)]
    if facility_ids is not None:
        conditions.append(facts.c.facility_id.in_(facility_ids))
    if apply_payer and query.payer_types:
        conditions.append(facts.c.payer_type.in_(query.payer_types))
    return conditions


def _metrics(row, days, facility_count=None):
    net = row['closing_census'] - row['opening_census']
    result = dict(opening_census=row['opening_census'], closing_census=row['closing_census'],
        admissions=row['admissions'], discharges=row['discharges'],
        payer_changes_in=row['payer_changes_in'], payer_changes_out=row['payer_changes_out'],
        net_change=net, average_per_day=round(net / days, 2))
    if facility_count is not None:
        result['facility_count'] = facility_count
    return result


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
    first, last, generated_at = connection.execute(select(
        func.min(daily_runs.c.simulation_date), func.max(daily_runs.c.simulation_date),
        func.max(daily_runs.c.completed_at)).where(daily_runs.c.generator == GENERATOR)).one()
    covered = connection.scalar(select(func.count()).select_from(daily_runs).where(
        daily_runs.c.generator == GENERATOR,
        daily_runs.c.simulation_date.between(query.start_date, query.end_date)))
    if covered != query.days:
        available = f'{first} through {last}' if first is not None else 'no completed dates'
        raise ApiError('summary_unavailable', f'Payer census facts are available for {available}. '
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

    facility_ids = (None if selected_ids and len(selected_ids) == len(all_rows)
        else sorted(selected_ids))
    # The payer filter lives inside the aggregates, not here, so the breakdown
    # that ignores it can come from the same rows.
    every = _conditions(query, facility_ids, apply_payer=False)
    id_column = _level_id(query.group_by)

    # One scan. Four grouping sets: the grand total, one row per location, one per
    # day, and one per payer type. The first three read the payer-filtered
    # measures; the payer rows read the unfiltered ones beside them.
    grouped_rows = connection.execute(select(
        id_column.label('scope'), facts.c.summary_date, facts.c.payer_type,
        func.grouping(id_column).label('no_scope'),
        func.grouping(facts.c.summary_date).label('no_date'),
        func.grouping(facts.c.payer_type).label('no_payer'),
        *_measures(query),
        *_measures(query, apply_payer=False, prefix='any_'))
        .select_from(_source(query.group_by)).where(*every)
        .group_by(func.grouping_sets(
            tuple_(), tuple_(id_column), tuple_(facts.c.summary_date),
            tuple_(facts.c.payer_type)))
    ).mappings().all()

    total_row = next(row for row in grouped_rows
        if row['no_scope'] and row['no_date'] and row['no_payer'])
    location_rows = {str(row['scope']): row for row in grouped_rows if not row['no_scope']}
    # A day's own opening and closing, not the range boundaries.
    daily_rows = {row['summary_date']: dict(row, opening_census=row['day_opening'],
        closing_census=row['day_closing']) for row in grouped_rows if not row['no_date']}
    by_payer = [dict(payer_type=row['payer_type'],
        **{key: row['any_' + key] for key in
            ('opening_census', 'closing_census', 'admissions', 'discharges',
             'payer_changes_in', 'payer_changes_out')})
        for row in grouped_rows if not row['no_payer']]

    return dict(
        range=dict(start=query.start_date, end=query.end_date, days=days), group_by=query.group_by,
        totals=_metrics(total_row, days),
        locations=[dict(id=key[1], level=key[0], name=paths[key][-1]['name'], path=paths[key],
            facility_ids=sorted(groups[key]),
            **_metrics(location_rows.get(key[1], ZERO), days, facility_count=len(groups[key])))
            for key in sorted(groups, key=lambda key: (paths[key][-1]['name'], key))],
        by_payer=[dict(payer_type=row['payer_type'], **_metrics(row, days))
            for row in sorted(by_payer, key=lambda row: row['payer_type'])],
        daily=[dict(date=day, **_metrics(daily_rows.get(day, ZERO), 1))
            for day in (query.start_date + timedelta(days=index) for index in range(days))],
        data_status=dict(complete=True, available_from=first, available_through=last,
            generated_at=generated_at, schema_version=1),
    )


def monthly_locations(connection: Connection, query: MonthlyQuery):
    """Per-facility monthly totals for the trending report.

    Net change is the summed flow rather than closing minus opening: over a whole
    month the two are equal, and the sum needs no boundary lookup.
    """
    selected = ([] if query.match_none else
        connection.execute(facility_locations(query)).mappings().all())
    locations = [dict(facility_id=row['facility_id'], facility_name=row['facility_name'],
        state=row['state'], portfolio=row['portfolio_name'], region=row['region_name'])
        for row in selected]
    if not locations:
        return dict(locations=[], items=[])

    conditions = [months.c.month_start.between(
        query.start_date.replace(day=1), query.end_date)]
    all_rows = connection.execute(facility_locations(LocationSelection())).mappings().all()
    if len(selected) != len(all_rows):
        conditions.append(months.c.facility_id.in_([row['facility_id'] for row in selected]))
    if query.payer_types:
        conditions.append(months.c.payer_type.in_(query.payer_types))
    net = (func.sum(months.c.admissions) + func.sum(months.c.changes_in)
        - func.sum(months.c.discharges) - func.sum(months.c.changes_out))
    rows = connection.execute(select(
        months.c.facility_id,
        func.to_char(months.c.month_start, 'YYYY-MM').label('month'),
        func.sum(months.c.admissions).label('admissions'),
        func.sum(months.c.discharges).label('discharges'),
        net.label('net_change'),
    ).where(*conditions).group_by(months.c.facility_id, months.c.month_start)).mappings().all()
    return dict(locations=locations, items=[dict(row) for row in rows])


def monthly_trend(connection: Connection, query: MonthlyQuery):
    """Monthly totals for the trending charts, with their days nested.

    Totals come from the monthly rollup. The days come from one lean aggregate
    over the daily table, because the report shows the highest and lowest day
    inside each month and that cannot be read from a monthly grain.

    This exists instead of reusing /overview because that endpoint computes
    grouping sets, a payer breakdown and a separate census pass that this report
    never displays -- 1,507ms against 175ms here for the same range.
    """
    selected = ([] if query.match_none else
        connection.execute(facility_locations(query)).mappings().all())
    if not selected:
        return dict(months=[])
    all_rows = connection.execute(facility_locations(LocationSelection())).mappings().all()
    scoped = (None if len(selected) == len(all_rows)
        else [row['facility_id'] for row in selected])

    def limit(table, date_column, start):
        conditions = [date_column.between(start, query.end_date)]
        if scoped is not None:
            conditions.append(table.c.facility_id.in_(scoped))
        if query.payer_types:
            conditions.append(table.c.payer_type.in_(query.payer_types))
        return conditions

    first_month = query.start_date.replace(day=1)
    month_label = func.to_char(months.c.month_start, 'YYYY-MM')
    totals = {row['month']: row for row in connection.execute(select(
        month_label.label('month'), months.c.month_start,
        func.sum(months.c.admissions).label('admissions'),
        func.sum(months.c.discharges).label('discharges'),
        func.sum(months.c.changes_in).label('payer_changes_in'),
        func.sum(months.c.changes_out).label('payer_changes_out'),
        func.sum(months.c.opening_census).label('opening_census'),
        func.sum(months.c.closing_census).label('closing_census'),
    ).where(*limit(months, months.c.month_start, first_month))
        .group_by(month_label, months.c.month_start)).mappings().all()}

    daily = connection.execute(select(
        facts.c.summary_date,
        func.sum(facts.c.admissions).label('admissions'),
        func.sum(facts.c.discharges).label('discharges'),
        func.sum(facts.c.changes_in).label('payer_changes_in'),
        func.sum(facts.c.changes_out).label('payer_changes_out'),
        func.sum(facts.c.opening_census).label('opening_census'),
        func.sum(facts.c.closing_census).label('closing_census'),
    ).where(*limit(facts, facts.c.summary_date, query.start_date))
        .group_by(facts.c.summary_date).order_by(facts.c.summary_date)).mappings().all()

    def measures(row):
        return dict(admissions=row['admissions'], discharges=row['discharges'],
            payer_changes_in=row['payer_changes_in'], payer_changes_out=row['payer_changes_out'],
            opening_census=row['opening_census'], closing_census=row['closing_census'],
            value=row['closing_census'] - row['opening_census'])

    by_month = defaultdict(list)
    for row in daily:
        by_month[row['summary_date'].strftime('%Y-%m')].append(
            dict(date=row['summary_date'], **measures(row)))
    result = []
    for label in sorted(totals):
        days = by_month.get(label, [])
        # The stored month may start before the requested range, so opening and
        # closing come from the days actually shown rather than the whole month.
        row = dict(totals[label])
        if days:
            row['opening_census'] = days[0]['opening_census']
            row['closing_census'] = days[-1]['closing_census']
            for key in ('admissions', 'discharges', 'payer_changes_in', 'payer_changes_out'):
                row[key] = sum(day[key] for day in days)
        result.append(dict(month=label, date=totals[label]['month_start'],
            end_date=days[-1]['date'] if days else totals[label]['month_start'],
            **measures(row), days=days))
    return dict(months=result)
