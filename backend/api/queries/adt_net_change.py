"""SQL readers. Connections are supplied by services; imports never access a database."""

from datetime import date, timedelta
import json

from sqlalchemy import func, inspect, or_, select, text
from sqlalchemy.engine import Connection

from api.queries.errors import ReportQueryError
from api.queries.table_filters import state_label
from data.models.adt_values import PAYER_TYPES
from data.models.facilities import facilities
from data.models.payer_changes import payer_changes
from data.models.stays import census, state
"""Reconciled census and resident movement over an inclusive reporting period."""


def daily_net_change(connection: Connection, start_date: date, end_date: date,
                     payer_type: list[str] | None = None,
                     locations: str = '[]', path: str = '[]') -> dict:
    if start_date > end_date or any(p not in PAYER_TYPES for p in payer_type or []):
        raise ReportQueryError(422, 'Invalid dates or payers.')
    try:
        selected, scope = json.loads(locations), json.loads(path)
        if (not isinstance(selected, list) or not isinstance(scope, list)
                or len(scope) > 4 or any(not isinstance(x, str) for x in scope)
                or any(not isinstance(p, list) or not 1 <= len(p) <= 4
                       or any(not isinstance(x, str) for x in p) for p in selected)):
            raise ValueError()
    except (ValueError, TypeError) as error:
        raise ReportQueryError(422, 'Invalid locations.') from error
    publication = connection.execute(select(state).where(state.c.id == 1)).mappings().one_or_none()
    if not publication or not publication['ready']:
        raise ReportQueryError(503, 'Census history needs refreshing.')
    if start_date < publication['start_date'] or end_date > publication['end_date']:
        raise ReportQueryError(422, 'Choose dates within the available census history.')
    rows = connection.execute(select(facilities.c.facility_code, state_label,
        facilities.c.portfolio, facilities.c.region, facilities.c.name)).all()
    codes = [row[0] for row in rows if list(row[1:1 + len(scope)]) == scope
             and (not selected or any(list(row[1:1 + len(p)]) == p for p in selected))]
    values = {}
    opening = 0
    if payer_type:
        if not inspect(connection).has_table('adt_payer_census_state') or not connection.scalar(
            text('SELECT ready FROM adt_payer_census_state WHERE id=1')
        ):
            raise ReportQueryError(503, 'Payer census history needs refreshing.')
        query = text('''
            WITH movements AS (
                SELECT admission_date AS day, facility_code, payer_type, 1 AS delta, 'admissions' AS kind
                FROM adt_admissions WHERE admission_date BETWEEN :start AND :end
                UNION ALL
                SELECT discharge_date, facility_code, payer_type, -1, 'discharges' FROM adt_discharges
                WHERE discharge_date BETWEEN :start AND :end
                UNION ALL
                SELECT effective_date, facility_code, new_payer_type, 1, 'payer_changes_in' FROM adt_payer_changes
                WHERE effective_date BETWEEN :start AND :end AND change_category='Payer type'
                UNION ALL
                SELECT effective_date, facility_code, previous_payer_type, -1, 'payer_changes_out' FROM adt_payer_changes
                WHERE effective_date BETWEEN :start AND :end AND change_category='Payer type'
             ) SELECT day, sum(delta) AS value,
                count(*) FILTER (WHERE kind='admissions') AS admissions,
                count(*) FILTER (WHERE kind='discharges') AS discharges,
                count(*) FILTER (WHERE kind='payer_changes_in') AS payer_changes_in,
                count(*) FILTER (WHERE kind='payer_changes_out') AS payer_changes_out
            FROM movements
            WHERE facility_code=ANY(:codes) AND payer_type=ANY(:payers) GROUP BY day
        ''')
        values = {row['day']: dict(row) for row in connection.execute(query,
            {'start': start_date, 'end': end_date, 'codes': codes, 'payers': payer_type}).mappings()}
        opening = connection.scalar(text('''
            SELECT count(*) FROM adt_payer_periods
            WHERE facility_code=ANY(:codes) AND payer_type=ANY(:payers)
              AND start_date < :start AND (end_date IS NULL OR end_date >= :start)
        '''), {'codes': codes, 'payers': payer_type, 'start': start_date})
    elif codes:
        opening = connection.scalar(select(func.sum(census.c.opening_census)).where(
            census.c.census_date == start_date, census.c.facility_code.in_(codes))) or 0
        values = {row['day']: dict(row) for row in connection.execute(select(
            census.c.census_date.label('day'),
            func.sum(census.c.closing_census - census.c.opening_census).label('value'),
            func.sum(census.c.admissions).label('admissions'),
            func.sum(census.c.discharges).label('discharges'))
            .where(census.c.census_date.between(start_date, end_date),
                   census.c.facility_code.in_(codes)).group_by(census.c.census_date)).mappings()}

    items = []
    for i in range((end_date - start_date).days + 1):
        day = start_date + timedelta(days=i)
        movement = values.get(day, {})
        change = int(movement.get('value', 0))
        closing = opening + change
        items.append({'date': day, 'value': change,
                      'opening_census': opening, 'closing_census': closing,
                      **{key: int(movement.get(key, 0)) for key in
                         ('admissions', 'discharges', 'payer_changes_in', 'payer_changes_out')}})
        opening = closing
    return {'items': items}


def monthly_locations(connection: Connection, start_date: date, end_date: date,
                      payer_type: list[str] | None = None) -> dict:
    if start_date > end_date or any(p not in PAYER_TYPES for p in payer_type or []):
        raise ReportQueryError(422, 'Invalid dates or payers.')
    publication = connection.execute(select(state).where(state.c.id == 1)).mappings().one_or_none()
    if not publication or not publication['ready']:
        raise ReportQueryError(503, 'Census history needs refreshing.')
    if start_date < publication['start_date'] or end_date > publication['end_date']:
        raise ReportQueryError(422, 'Choose dates within the available census history.')
    locations = connection.execute(select(facilities.c.facility_code,
        facilities.c.name.label('facility_name'), state_label.label('state'),
        facilities.c.portfolio, facilities.c.region)).mappings().all()
    movements = connection.execute(text('''
        WITH movements AS (
            SELECT facility_code, admission_date AS day, payer_type,
                1 AS admissions, 0 AS discharges, 1 AS net_change
            FROM adt_admissions WHERE admission_date BETWEEN :start AND :end
            UNION ALL
            SELECT facility_code, discharge_date, payer_type, 0, 1, -1
            FROM adt_discharges WHERE discharge_date BETWEEN :start AND :end
            UNION ALL
            SELECT facility_code, effective_date, new_payer_type, 0, 0, 1
            FROM adt_payer_changes WHERE :filtered AND change_category='Payer type'
                AND effective_date BETWEEN :start AND :end
            UNION ALL
            SELECT facility_code, effective_date, previous_payer_type, 0, 0, -1
            FROM adt_payer_changes WHERE :filtered AND change_category='Payer type'
                AND effective_date BETWEEN :start AND :end
        ) SELECT facility_code, to_char(day, 'YYYY-MM') AS month,
            sum(admissions) AS admissions, sum(discharges) AS discharges,
            sum(net_change) AS net_change
        FROM movements WHERE NOT :filtered OR payer_type=ANY(:payers)
        GROUP BY facility_code, to_char(day, 'YYYY-MM')
    '''), {'start': start_date, 'end': end_date, 'filtered': bool(payer_type),
           'payers': payer_type or []}).mappings().all()
    return {'locations': [dict(row) for row in locations], 'items': [dict(row) for row in movements]}


def payer_net_change(connection: Connection, start_date: date, end_date: date) -> dict:
    if start_date > end_date:
        raise ReportQueryError(422, 'start_date must not be after end_date.')
    if not inspect(connection).has_table('adt_payer_census_state'):
        raise ReportQueryError(503, 'Payer census history is not available yet.')
    publication = connection.execute(text(
        'SELECT * FROM adt_payer_census_state WHERE id=1'
    )).mappings().one_or_none()
    census_ready = connection.scalar(select(state.c.ready).where(state.c.id == 1))
    if not publication or not publication['ready'] or not census_ready:
        raise ReportQueryError(503, 'Payer census history needs refreshing. Please try again later.')
    if start_date < publication['start_date'] or end_date > publication['end_date']:
        raise ReportQueryError(422,
            f"Choose dates between {publication['start_date']} and {publication['end_date']}.")
    movements = connection.execute(text("""
        WITH movement AS (
            SELECT facility_code, payer_type,
                count(*) FILTER (WHERE start_date < :start AND
                    (end_date IS NULL OR end_date >= :start)) AS opening_census,
                count(*) FILTER (WHERE start_date <= :end AND
                    (end_date IS NULL OR end_date > :end)) AS closing_census,
                0::bigint AS admissions, 0::bigint AS discharges,
                0::bigint AS payer_changes_in, 0::bigint AS payer_changes_out
            FROM adt_payer_periods GROUP BY 1,2
            UNION ALL
            SELECT facility_code, payer_type, 0,0,count(*),0,0,0 FROM adt_admissions
                WHERE admission_date BETWEEN :start AND :end GROUP BY 1,2
            UNION ALL
            SELECT facility_code, payer_type, 0,0,0,count(*),0,0 FROM adt_discharges
                WHERE discharge_date BETWEEN :start AND :end GROUP BY 1,2
            UNION ALL
            SELECT facility_code, new_payer_type, 0,0,0,0,count(*),0 FROM adt_payer_changes
                WHERE effective_date BETWEEN :start AND :end
                    AND change_category='Payer type' GROUP BY 1,2
            UNION ALL
            SELECT facility_code, previous_payer_type, 0,0,0,0,0,count(*) FROM adt_payer_changes
                WHERE effective_date BETWEEN :start AND :end
                    AND change_category='Payer type' GROUP BY 1,2
        )
        SELECT facility_code, payer_type, sum(opening_census)::bigint AS opening_census,
            sum(closing_census)::bigint AS closing_census,
            sum(admissions)::bigint AS admissions, sum(discharges)::bigint AS discharges,
            sum(payer_changes_in)::bigint AS payer_changes_in,
            sum(payer_changes_out)::bigint AS payer_changes_out,
            sum(closing_census-opening_census)::bigint AS net_change
        FROM movement GROUP BY 1,2
    """), {'start': start_date, 'end': end_date}).mappings().all()
    lookup = {(row['facility_code'], row['payer_type']): dict(row) for row in movements}
    locations = connection.execute(select(
        facilities.c.facility_code, facilities.c.name.label('facility_name'),
        state_label.label('state'), facilities.c.portfolio, facilities.c.region
    )).mappings().all()
    metrics = ('opening_census', 'closing_census', 'admissions', 'discharges',
               'payer_changes_in', 'payer_changes_out', 'net_change')
    return {'items': [
        {**dict(location), 'payer_type': payer,
         **{key: lookup.get((location['facility_code'], payer), {}).get(key, 0) for key in metrics}}
        for location in locations for payer in PAYER_TYPES
    ]}


def net_change(connection: Connection, start_date: date, end_date: date,
               payer_type: list[str] | None = None) -> dict:
    if payer_type and any(payer not in PAYER_TYPES for payer in payer_type):
        raise ReportQueryError(422, 'Unknown payer type.')
    if start_date > end_date:
        raise ReportQueryError(422, "start_date must not be after end_date.")
    try:
        prior_end = start_date - timedelta(days=1)
        prior_start = start_date - timedelta(days=(end_date - start_date).days + 1)
    except OverflowError as error:
        raise ReportQueryError(422, "Date range exceeds the supported comparison period.") from error
    if not inspect(connection).has_table(state.name):
        raise ReportQueryError(503, "Census history is not available yet.")
    publication = (
        connection.execute(select(state).where(state.c.id == 1)).mappings().one_or_none()
    )
    if not publication or not publication["ready"]:
        raise ReportQueryError(503, "Census history is being refreshed. Please try again shortly.")
    if start_date < publication["start_date"] or end_date > publication["end_date"]:
        raise ReportQueryError(
            422,
            f"Choose dates between {publication['start_date']} and {publication['end_date']}.",
        )
    prior_available = prior_start >= publication["start_date"]
    if not inspect(connection).has_table('adt_payer_census_state') or not connection.scalar(
        text('SELECT ready FROM adt_payer_census_state WHERE id=1')
    ):
        raise ReportQueryError(503, 'Payer census history needs refreshing.')
    change_filters = [payer_changes.c.effective_date.between(start_date, end_date),
                      payer_changes.c.change_category == 'Payer type']
    if payer_type:
        change_filters.append(or_(payer_changes.c.previous_payer_type.in_(payer_type),
                                  payer_changes.c.new_payer_type.in_(payer_type)))
    unique_changes = dict(connection.execute(select(payer_changes.c.facility_code,
        func.count(func.distinct(payer_changes.c.change_id)))
        .where(*change_filters).group_by(payer_changes.c.facility_code)).all())
    if payer_type:
        current_payers = payer_net_change(connection, start_date, end_date)['items']
        prior_payers = payer_net_change(connection, prior_start, prior_end)['items'] if prior_available else []
        selected = set(payer_type)
        prior_lookup = {}
        for row in prior_payers:
            if row['payer_type'] in selected:
                code = row['facility_code']
                prior_lookup[code] = prior_lookup.get(code, 0) + row['net_change']
        grouped = {}
        metrics = ('opening_census', 'closing_census', 'admissions', 'discharges',
                   'payer_changes_in', 'payer_changes_out', 'net_change')
        for row in current_payers:
            if row['payer_type'] not in selected:
                continue
            code = row['facility_code']
            if code not in grouped:
                grouped[code] = {key: row[key] for key in
                                 ('facility_code', 'facility_name', 'state', 'portfolio', 'region')}
                grouped[code].update({metric: 0 for metric in metrics})
                grouped[code]['prior_net_change'] = prior_lookup.get(code)
                grouped[code]['payer_changes'] = unique_changes.get(code, 0)
            for metric in metrics:
                grouped[code][metric] += row[metric]
        return {
            'items': list(grouped.values()),
            'prior_start_date': prior_start, 'prior_end_date': prior_end,
            'census_available': True, 'prior_available': prior_available,
        }
    current = census.c.census_date.between(start_date, end_date)
    prior = census.c.census_date.between(prior_start, prior_end)
    counts = (
        select(
            census.c.facility_code,
            func.max(census.c.opening_census)
            .filter(census.c.census_date == start_date)
            .label("opening_census"),
            func.max(census.c.closing_census)
            .filter(census.c.census_date == end_date)
            .label("closing_census"),
            func.sum(census.c.admissions).filter(current).label("admissions"),
            func.sum(census.c.discharges).filter(current).label("discharges"),
            func.sum(census.c.admissions - census.c.discharges)
            .filter(current)
            .label("net_change"),
            func.sum(census.c.admissions - census.c.discharges)
            .filter(prior)
            .label("prior_net_change"),
        )
        .where(census.c.census_date.between(prior_start, end_date))
        .group_by(census.c.facility_code)
        .subquery()
    )
    rows = (
        connection.execute(
            select(
                facilities.c.facility_code,
                facilities.c.name.label("facility_name"),
                state_label.label("state"),
                facilities.c.portfolio,
                facilities.c.region,
                *(
                    counts.c[key]
                    for key in (
                        "opening_census",
                        "closing_census",
                        "admissions",
                        "discharges",
                        "net_change",
                        "prior_net_change",
                    )
                ),
            )
            .select_from(
                facilities.join(counts, facilities.c.facility_code == counts.c.facility_code)
            )
            .order_by(facilities.c.facility_code)
        )
        .mappings()
        .all()
    )
    return {
        "items": [
            {**dict(row), "prior_net_change": row["prior_net_change"] if prior_available else None,
             "payer_changes": unique_changes.get(row['facility_code'], 0)}
            for row in rows
        ],
        "prior_start_date": prior_start,
        "prior_end_date": prior_end,
        "census_available": True,
        "prior_available": prior_available,
    }
