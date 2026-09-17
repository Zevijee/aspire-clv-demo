"""Named source corrections; none call a population generator."""
from sqlalchemy import select, text, update
from data.models.admissions import admissions
from data.models.facilities import facilities
from data.writers.legacy import sync_sources
from seeding.base import SeedResult


def run_backfill(name, context, *, organization_id='aspire-demo'):
    code = context.facility_codes[0]
    window = context.replace_window or context.window
    if name == 'canonical_sources':
        sync_sources(context.connection, (code,), window.start_date, window.end_date, organization_id=organization_id)
        return SeedResult(name, 0, 1, window.start_date)
    if name == 'initial_payer':
        changed = context.connection.execute(text("""
            UPDATE adt_resident_stays s SET initial_payer_type=a.payer_type, initial_payer_name=a.payer_name
            FROM adt_admissions a WHERE s.facility_code=:code AND s.stay_id=a.admission_id
              AND s.start_date BETWEEN :start AND :end
              AND (s.initial_payer_type IS NULL OR s.initial_payer_name IS NULL)
        """), {'code': code, 'start': window.start_date, 'end': window.end_date}).rowcount
        return SeedResult(name, changed, changed, window.start_date if changed else None)
    if name == 'hospital_assignments':
        from seeding.reference_data.hospital_directory import choose_referring_hospital
        facility = dict(context.connection.execute(select(facilities).where(facilities.c.facility_code == code)).mappings().one())
        query = select(admissions.c.admission_id, admissions.c.admission_date, admissions.c.admission_source_name).where(
            admissions.c.facility_code == code, admissions.c.admission_source_type == 'Hospital',
            admissions.c.admission_date.between(window.start_date, window.end_date))
        if context.entity_ids:
            query = query.where(admissions.c.admission_id.in_(context.entity_ids))
        count, changed = 0, 0
        for row in context.connection.execute(query).mappings():
            count += 1
            name = choose_referring_hospital(facility, row['admission_id'], row['admission_date'])
            if name != row['admission_source_name']:
                changed += context.connection.execute(update(admissions).where(admissions.c.admission_id == row['admission_id'])
                    .values(admission_source_name=name)).rowcount
        return SeedResult('hospital_assignments', count, changed, window.start_date if changed else None)
    raise ValueError('Unknown named backfill.')
