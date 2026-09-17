"""Plan a resident/stay scenario once, then persist it in dependency order.

Planning may resolve readmissions using simulated departures, but writes no
admissions or stays. The durable plan lets every subsequent dataset stage use
the same resolved residents without repeating the simulation on resume.
"""
from dataclasses import replace
from datetime import date
from sqlalchemy import select
from data.models import canonical as c
from data.models.admissions import admissions
from data.models.discharges import discharges
from data.models.stays import stays
from data.models.payer_periods import periods
from data.models.seed_operations import source_plans
from data.writers.core import write_rows
from data.writers.sources import write_residents, write_census_stays
from domain.identities import source_id
from seeding.base import SeedResult


def _encode(value):
    if isinstance(value, date):
        return {'$date': value.isoformat()}
    if isinstance(value, dict):
        return {key: _encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(item) for item in value]
    return value


def _decode(value):
    if isinstance(value, dict):
        if set(value) == {'$date'}:
            return date.fromisoformat(value['$date'])
        return {key: _decode(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode(item) for item in value]
    return value


def load_plan(context, run_id):
    payload = context.connection.scalar(select(source_plans.c.payload).where(
        source_plans.c.run_id == run_id,
        source_plans.c.facility_code == context.facility_codes[0]))
    if payload is None:
        raise ValueError('Missing resident source plan; resume the resident stage before loading stays.')
    return _decode(payload)


def prepare_residents(context, run_id, source_names, rebuilds, organization_id):
    from seeding.generators.admissions import plan_admissions
    from seeding.generators.resident_movement import plan_movement
    connection = context.connection
    code = context.facility_codes[0]
    existing = [dict(row) for row in connection.execute(select(admissions).where(
        admissions.c.facility_code == code)).mappings()]
    admission_plan = plan_admissions(replace(context, rebuild='admissions' in rebuilds)) if 'admissions' in source_names else None
    by_id = {row['admission_id']: row for row in existing}
    new_ids = []
    changed_from = context.changed_from
    if admission_plan:
        replacing = set(admission_plan['replacing_days'])
        by_id = {key: row for key, row in by_id.items() if row['admission_date'] not in replacing}
        for row in admission_plan['rows']:
            if row['admission_id'] not in by_id:
                by_id[row['admission_id']] = row
                new_ids.append(row['admission_id'])
        if new_ids or replacing:
            first = admission_plan['first_changed']
            changed_from = min(changed_from, first) if changed_from else first
    movement = plan_movement(replace(context, rebuild='discharges' in rebuilds,
        changed_from=changed_from, new_admission_ids=tuple(new_ids)), list(by_id.values()))
    if movement:
        for identity in movement['identities']:
            by_id[identity['admission_id']].update(identity)
        if admission_plan:
            admission_plan['rows'] = [by_id[row['admission_id']] for row in admission_plan['rows']]
    # Adopt already-existing identities as well, without rewriting admission IDs.
    retained_stays = [dict(row) for row in connection.execute(select(stays).where(
        stays.c.facility_code == code)).mappings()]
    resident_names = {row['resident_id']: row['resident_name'] for row in retained_stays}
    resident_names.update({row['resident_id']: row['resident_name'] for row in by_id.values()})
    if movement:
        resident_names.update({row['resident_id']: row['resident_name'] for row in movement['stays']})
    result = write_residents(connection, [dict(resident_id=key, display_name=name)
        for key, name in resident_names.items()], organization_id=organization_id,
        source_system='legacy-adt', batch_size=context.batch_size)
    payload = dict(admissions=admission_plan, movement=movement,
        admission_rows=list(by_id.values()))
    write_rows(connection, source_plans, [dict(run_id=run_id, facility_code=code, payload=_encode(payload))])
    # Resident creation alone must not widen the movement/report repair interval.
    return SeedResult('residents', len(resident_names), result.changed,
        movement['replay_start'] if movement else None)


def persist_stays(context, planned, organization_id):
    connection = context.connection
    code = context.facility_codes[0]
    movement = planned['movement']
    rows = list(movement['stays']) if movement else []
    # An older database may have source rows not yet copied into the shared schema.
    # Only adopt those missing rows, before generating any new event projections.
    known = set(connection.scalars(select(c.census_stays.c.stay_id).where(
        c.census_stays.c.organization_id == organization_id, c.census_stays.c.facility_code == code)))
    planned_ids = {row['stay_id'] for row in rows}
    rows.extend(dict(row) for row in connection.execute(select(stays).where(
        stays.c.facility_code == code)).mappings() if row['stay_id'] not in known | planned_ids)
    if not rows:
        return SeedResult('census_stays', 0, 0)
    entries = {row['admission_id']: row for row in planned['admission_rows']}
    exits = {(row['resident_id'], row['start_date']): row for row in connection.execute(
        select(discharges).where(discharges.c.facility_code == code)).mappings()}
    if movement:
        # Replayed stays may now remain open; never retain an obsolete exit.
        exits = {key: row for key, row in exits.items() if row['discharge_date'] < movement['replay_start']}
        exits.update({(row['resident_id'], row['start_date']): row for row in movement['discharges']})
    locations = set()
    for row in entries.values():
        locations.add((row['admission_source_type'], row['admission_source_name']))
    for row in exits.values():
        locations.add((row['destination_type'], row['destination_name']))
    location_ids = {}
    location_rows, keys = [], []
    for kind, name in sorted(locations):
        if not name:
            continue
        key = f'{len(kind)}:{kind}{name}'
        ident = source_id(organization_id, 'legacy-adt', 'location', key)
        location_ids[(kind, name)] = ident
        location_rows.append(dict(organization_id=organization_id, location_id=ident,
            code=ident, name=name, location_type=kind, is_active=True))
        keys.append(dict(organization_id=organization_id, source_system='legacy-adt', external_key=key, location_id=ident))
    write_rows(connection, c.external_locations, location_rows, mode='ignore', batch_size=context.batch_size)
    write_rows(connection, c.location_source_keys, keys, batch_size=context.batch_size)
    records = []
    for row in rows:
        entry = entries.get(row['stay_id'], {})
        exit_row = exits.get((row['resident_id'], row['start_date']), {}) if row['end_date'] else {}
        records.append(dict(stay_id=row['stay_id'], resident_id=row['resident_id'], facility_code=code,
            admission_date=row['start_date'], discharge_date=row['end_date'],
            known_from=min(row['start_date'], context.window.start_date), start_known=True, time_precision='date',
            source_location_id=location_ids.get((entry.get('admission_source_type'), entry.get('admission_source_name'))),
            destination_location_id=location_ids.get((exit_row.get('destination_type'), exit_row.get('destination_name'))),
            source_type=entry.get('admission_source_type'), destination_type=exit_row.get('destination_type'),
            discharge_type=exit_row.get('discharge_type'), source_readmission_flag=entry.get('is_readmission'),
            readmission_gap_days=entry.get('readmission_days_since_prior')))
    result = write_census_stays(connection, records, organization_id=organization_id,
        source_system='legacy-adt', batch_size=context.batch_size)
    return SeedResult('census_stays', len(records), result.changed,
        movement['replay_start'] if movement else context.window.start_date)


def remove_obsolete_stays(context, organization_id):
    """Only explicit repairs remove canonical stays absent from repaired sources."""
    connection = context.connection
    scoped_stays = select(c.census_stays.c.stay_id).where(
        c.census_stays.c.organization_id == organization_id,
        c.census_stays.c.facility_code.in_(context.facility_codes),
        c.census_stays.c.source_system == 'legacy-adt')
    connection.execute(c.payer_stays.delete().where(c.payer_stays.c.organization_id == organization_id,
        c.payer_stays.c.source_system == 'legacy-adt', c.payer_stays.c.stay_id.in_(scoped_stays),
        ~c.payer_stays.c.payer_stay_id.in_(select(periods.c.period_id))))
    obsolete = select(c.census_stays.c.stay_id).where(
        c.census_stays.c.organization_id == organization_id,
        c.census_stays.c.facility_code.in_(context.facility_codes),
        c.census_stays.c.source_system == 'legacy-adt',
        ~c.census_stays.c.stay_id.in_(select(stays.c.stay_id)))
    connection.execute(c.payer_stays.delete().where(c.payer_stays.c.organization_id == organization_id,
        c.payer_stays.c.source_system == 'legacy-adt', c.payer_stays.c.stay_id.in_(obsolete)))
    connection.execute(c.stay_source_keys.delete().where(c.stay_source_keys.c.organization_id == organization_id,
        c.stay_source_keys.c.source_system == 'legacy-adt', c.stay_source_keys.c.stay_id.in_(obsolete)))
    connection.execute(c.census_stays.delete().where(c.census_stays.c.organization_id == organization_id,
        c.census_stays.c.stay_id.in_(obsolete)))
