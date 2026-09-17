"""Explicit bridge from existing seed outputs to shared canonical identities.

The bridge is used only for a requested backfill or a changed generator batch.
It never runs on API startup. Existing resident/stay/coverage IDs are retained;
names are not evidence for merging residents. New ingestion can write the same
canonical tables directly through the shared writers.
"""
from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects.postgresql import insert

from data.models import canonical as c
from data.models.admissions import admissions
from data.models.discharges import discharges
from data.models.facilities import facilities
from data.models.payer_periods import periods
from data.models.stays import stays
from data.writers.core import upsert_rows
from data.writers.references import ensure_legacy_payer
from domain.identities import source_id


def sync_reference_data(connection, facility_codes, start_date, end_date, *, organization_id="aspire-demo", create_missing=True):
    """Capture facility references without touching resident or movement history."""
    if not facility_codes:
        raise ValueError("Canonical synchronization requires explicit facility codes.")
    codes = tuple(sorted(set(facility_codes)))
    params = {"organization": organization_id, "codes": list(codes)}
    connection.execute(insert(c.organizations).values(organization_id=organization_id,
        name=organization_id, reporting_timezone="America/New_York").on_conflict_do_nothing())
    # Refuse reparenting a facility to another tenant through a seed/backfill.
    conflicts = connection.scalar(text("""
        SELECT count(*) FROM facilities WHERE facility_code=ANY(:codes)
        AND organization_id IS NOT NULL AND organization_id<>:organization
    """), params)
    if conflicts:
        raise ValueError("Facility ownership conflicts with the requested organization.")
    connection.execute(text("""UPDATE facilities SET organization_id=:organization
        WHERE facility_code=ANY(:codes) AND organization_id IS NULL"""), params)
    for row in connection.execute(select(facilities).where(facilities.c.facility_code.in_(codes))).mappings():
        portfolio_code = f"{row['state']}:{row['portfolio']}"
        region_code = f"{portfolio_code}:{row['region']}"
        portfolio_id = source_id(organization_id, "legacy-adt", "portfolio", portfolio_code)
        region_id = source_id(organization_id, "legacy-adt", "region", region_code)
        for table, values in ((c.portfolios, dict(portfolio_id=portfolio_id, code=portfolio_code, name=row['portfolio'])),
                              (c.regions, dict(region_id=region_id, code=region_code, name=row['region']))):
            if create_missing:
                connection.execute(insert(table).values(organization_id=organization_id, **values).on_conflict_do_nothing())
        active = connection.execute(select(c.facility_hierarchy_periods).where(
            c.facility_hierarchy_periods.c.organization_id == organization_id,
            c.facility_hierarchy_periods.c.facility_code == row['facility_code'],
            c.facility_hierarchy_periods.c.ended_on.is_(None))).mappings().first()
        if active is None or (active['portfolio_id'], active['region_id']) != (portfolio_id, region_id):
            if active and end_date <= active['started_on']:
                raise ValueError('Backdated hierarchy changes require an explicit effective-date correction.')
            if active:
                connection.execute(c.facility_hierarchy_periods.update().where(
                    c.facility_hierarchy_periods.c.organization_id == organization_id,
                    c.facility_hierarchy_periods.c.hierarchy_period_id == active['hierarchy_period_id']).values(ended_on=end_date))
            hierarchy_id = source_id(organization_id, 'legacy-adt', 'hierarchy', f"{row['facility_code']}:{end_date}")
            connection.execute(c.facility_hierarchy_periods.insert().values(organization_id=organization_id,
                hierarchy_period_id=hierarchy_id, facility_code=row['facility_code'], portfolio_id=portfolio_id,
                region_id=region_id, started_on=end_date))
        capacity = connection.execute(select(c.facility_capacity_periods).where(
            c.facility_capacity_periods.c.organization_id == organization_id,
            c.facility_capacity_periods.c.facility_code == row['facility_code'],
            c.facility_capacity_periods.c.ended_on.is_(None))).mappings().first()
        if capacity is None or capacity['licensed_beds'] != row['licensed_beds']:
            if capacity and end_date <= capacity['started_on']:
                raise ValueError('Backdated capacity changes require an explicit effective-date correction.')
            if capacity:
                connection.execute(c.facility_capacity_periods.update().where(
                    c.facility_capacity_periods.c.organization_id == organization_id,
                    c.facility_capacity_periods.c.capacity_period_id == capacity['capacity_period_id']).values(ended_on=end_date))
            capacity_id = source_id(organization_id, 'legacy-adt', 'capacity', f"{row['facility_code']}:{end_date}")
            connection.execute(c.facility_capacity_periods.insert().values(organization_id=organization_id,
                capacity_period_id=capacity_id, facility_code=row['facility_code'], licensed_beds=row['licensed_beds'],
                operational_beds=None, started_on=end_date))
    return codes


def _sync_residents(connection, stay_filter, organization_id):
    query = select(stays.c.resident_id, func.max(stays.c.resident_name).label('name')).where(
        stay_filter).group_by(stays.c.resident_id)
    count = 0
    for batch in connection.execute(query).mappings().partitions(1000):
        count += upsert_rows(connection, c.residents, [dict(organization_id=organization_id,
            resident_id=r['resident_id'], display_name=r['name']) for r in batch])
        upsert_rows(connection, c.resident_source_keys, [dict(organization_id=organization_id,
            source_system='legacy-adt', external_key=r['resident_id'], resident_id=r['resident_id']) for r in batch])
    return count


def sync_residents(connection, facility_codes, *, organization_id='aspire-demo'):
    """Materialize resolved resident identities before canonical stay records."""
    if not facility_codes or not connection.in_transaction():
        raise ValueError('Resident synchronization requires a transaction and facility scope.')
    owners = dict(connection.execute(select(facilities.c.facility_code, facilities.c.organization_id)
        .where(facilities.c.facility_code.in_(facility_codes))).all())
    if set(owners) != set(facility_codes) or any(owner != organization_id for owner in owners.values()):
        raise ValueError('Resident synchronization crosses facility ownership.')
    return _sync_residents(connection, stays.c.facility_code.in_(facility_codes), organization_id)


def sync_sources(connection, facility_codes, start_date, end_date, *, organization_id="aspire-demo", residents_prepared=False):
    """Backfill selected legacy-owned histories; preserve IDs and all retained dates.

    Current references are captured separately from missing historical hierarchy
    dates. The source range never implies permission to delete older history.
    """
    codes = sync_reference_data(connection, facility_codes, start_date, end_date,
                                organization_id=organization_id)
    params = {"organization": organization_id, "codes": list(codes)}

    # New/changed admissions, exits and still-open stays are the only histories
    # affected by an incremental date interval. A first canonical import includes
    # the facility's complete retained history without changing its source IDs.
    canonical_facilities = set(connection.scalars(select(c.census_stays.c.facility_code).where(
        c.census_stays.c.organization_id == organization_id,
        c.census_stays.c.facility_code.in_(codes)).distinct()))
    stay_filter = stays.c.facility_code.in_(codes)
    if canonical_facilities:
        stay_filter = stay_filter & or_(stays.c.facility_code.not_in(canonical_facilities), stays.c.start_date >= start_date,
                                       stays.c.end_date >= start_date, stays.c.end_date.is_(None))
    affected_stays = select(stays.c.stay_id).where(stay_filter)
    discharge_filter = discharges.c.facility_code.in_(codes)
    if canonical_facilities:
        discharge_filter = discharge_filter & or_(discharges.c.facility_code.not_in(canonical_facilities),
                                                  discharges.c.discharge_date >= start_date)
    location_ids = {}
    location_inputs = [select(admissions.c.admission_source_type, admissions.c.admission_source_name).where(
        admissions.c.admission_id.in_(affected_stays)).distinct(),
        select(discharges.c.destination_type, discharges.c.destination_name).where(
            discharge_filter).distinct()]
    for statement in location_inputs:
        for kind, name in connection.execute(statement):
            if not name:
                continue
            key = f"{len(kind)}:{kind}{name}"
            ident = source_id(organization_id, "legacy-adt", "location", key)
            connection.execute(insert(c.external_locations).values(organization_id=organization_id,
                location_id=ident, code=ident, name=name, location_type=kind, is_active=True).on_conflict_do_nothing())
            upsert_rows(connection, c.location_source_keys, [dict(organization_id=organization_id,
                source_system="legacy-adt", external_key=key, location_id=ident)])
            location_ids[(kind, name)] = ident

    # Existing demo source IDs are already stable; do not create new identities.
    if not residents_prepared:
        _sync_residents(connection, stay_filter, organization_id)

    discharge_lookup = discharges.alias("exit")
    admission_lookup = admissions.alias("entry")
    joined = stays.outerjoin(admission_lookup, admission_lookup.c.admission_id == stays.c.stay_id).outerjoin(
        discharge_lookup, (discharge_lookup.c.resident_id == stays.c.resident_id)
        & (discharge_lookup.c.facility_code == stays.c.facility_code)
        & (discharge_lookup.c.start_date == stays.c.start_date))
    query = select(stays, admission_lookup.c.admission_source_type, admission_lookup.c.admission_source_name,
        admission_lookup.c.is_readmission, admission_lookup.c.readmission_days_since_prior,
        discharge_lookup.c.discharge_type, discharge_lookup.c.destination_type,
        discharge_lookup.c.destination_name).select_from(joined).where(stay_filter)
    stay_count = 0
    for batch in connection.execute(query).mappings().partitions(1000):
        foreign_owner = connection.scalar(select(c.census_stays.c.stay_id).where(
            c.census_stays.c.organization_id == organization_id,
            c.census_stays.c.stay_id.in_([r['stay_id'] for r in batch]),
            c.census_stays.c.source_system != 'legacy-adt').limit(1))
        if foreign_owner:
            raise ValueError('Legacy synchronization cannot overwrite another source system stay.')
        rows = [dict(organization_id=organization_id, stay_id=r['stay_id'], resident_id=r['resident_id'],
            facility_code=r['facility_code'], admission_date=r['start_date'], discharge_date=r['end_date'],
            known_from=min(r['start_date'], start_date), start_known=True, time_precision="date",
            source_location_id=location_ids.get((r['admission_source_type'], r['admission_source_name'])),
            destination_location_id=location_ids.get((r['destination_type'], r['destination_name'])),
            source_type=r['admission_source_type'], destination_type=r['destination_type'],
            discharge_type=r['discharge_type'], source_readmission_flag=r['is_readmission'],
            readmission_gap_days=r['readmission_days_since_prior'], source_system="legacy-adt") for r in batch]
        stay_count += upsert_rows(connection, c.census_stays, rows)
        upsert_rows(connection, c.stay_source_keys, [dict(organization_id=organization_id, source_system="legacy-adt",
            external_key=r['stay_id'], stay_id=r['stay_id']) for r in batch])

    period_filter = periods.c.facility_code.in_(codes) & periods.c.stay_id.in_(affected_stays)
    plan_ids = {(kind, name): ensure_legacy_payer(connection, organization_id, kind, name)
        for kind, name in connection.execute(select(periods.c.payer_type, periods.c.payer_name).where(
            period_filter).distinct())}
    for batch in connection.execute(select(periods).where(period_filter)).mappings().partitions(1000):
        foreign_owner = connection.scalar(select(c.payer_stays.c.payer_stay_id).where(
            c.payer_stays.c.organization_id == organization_id,
            c.payer_stays.c.payer_stay_id.in_([r['period_id'] for r in batch]),
            c.payer_stays.c.source_system != 'legacy-adt').limit(1))
        if foreign_owner:
            raise ValueError('Legacy synchronization cannot overwrite another source system coverage.')
        upsert_rows(connection, c.payer_stays, [dict(organization_id=organization_id,
            source_system="legacy-adt",
            payer_stay_id=r['period_id'], stay_id=r['stay_id'],
            payer_plan_id=plan_ids[(r['payer_type'], r['payer_name'])], started_on=r['start_date'],
            ended_on=r['end_date'], time_precision="date", source_sequence=0) for r in batch])

    # Delete only bridge-owned records actually removed from the selected source.
    # Manually supplied/ETL records use other source_system values and are retained.
    connection.execute(text("""DELETE FROM payer_stays p USING census_stays s
        WHERE p.organization_id=:organization AND s.organization_id=p.organization_id
        AND s.stay_id=p.stay_id AND s.source_system='legacy-adt' AND p.source_system='legacy-adt'
        AND s.facility_code=ANY(:codes)
        AND NOT EXISTS (SELECT 1 FROM adt_payer_periods q WHERE q.period_id=p.payer_stay_id)"""), params)
    connection.execute(text("""DELETE FROM stay_source_keys k USING census_stays s
        WHERE k.organization_id=:organization AND s.organization_id=k.organization_id
        AND s.stay_id=k.stay_id AND k.source_system='legacy-adt' AND s.source_system='legacy-adt'
        AND s.facility_code=ANY(:codes) AND NOT EXISTS
        (SELECT 1 FROM adt_resident_stays old WHERE old.stay_id=s.stay_id)"""), params)
    connection.execute(text("""DELETE FROM census_stays s WHERE s.organization_id=:organization
        AND s.source_system='legacy-adt' AND s.facility_code=ANY(:codes)
        AND NOT EXISTS (SELECT 1 FROM adt_resident_stays old WHERE old.stay_id=s.stay_id)"""), params)
    return stay_count
