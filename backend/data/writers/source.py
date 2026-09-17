"""Canonical ingestion contract shared by demo generation and production ETL.

Call inside a transaction; follow with reporting.refresh_from_canonical for the
affected scope in that same transaction. This module never invokes reporting or
generation itself. Each source record supplies stable IDs and an explicit tenant.
"""
from sqlalchemy import select, text

from data.models import canonical
from data.locking import lock_source_scope
from data.writers.core import upsert_rows


def write_source_batch(connection, organization_id, records, *, facility_codes, batch_size=1000):
    if not connection.in_transaction():
        raise ValueError('Canonical writes require an explicit caller-owned transaction.')
    if not organization_id or not facility_codes:
        raise ValueError("Canonical source writes require an organization and explicit facility scope.")
    codes = tuple(sorted(set(facility_codes)))
    facilities = connection.execute(select(canonical.facility_reference).where(
        canonical.facility_reference.c.facility_code.in_(codes))).mappings().all()
    if len(facilities) != len(codes) or any(row['organization_id'] != organization_id for row in facilities):
        raise ValueError("Every requested facility must belong to the organization.")
    tables = {table.name: table for table in canonical.metadata.sorted_tables
              if 'organization_id' in table.c and table.name not in ('facilities', 'organizations', 'ingestion_issues')}
    if set(records) - set(tables):
        raise ValueError('Unknown or separately managed source entities: ' + ', '.join(sorted(set(records) - set(tables))))
    # Serialize corrections for this organization's shared people/intervals as well
    # as facilities; cross-facility transfers cannot race an overlap validation.
    lock_source_scope(connection, organization_id)
    result = {}
    for name, table in tables.items():
        if name not in records:
            continue
        def prepared_rows():
            for supplied in records[name]:
                row = dict(supplied)
                if row.get('organization_id', organization_id) != organization_id:
                    raise ValueError('A source batch cannot mix organization identities.')
                if 'facility_code' in row and row['facility_code'] not in codes:
                    raise ValueError('Source facility is outside the requested scope.')
                existing = None
                key_columns = [column.name for column in table.primary_key if column.name != 'organization_id']
                if all(key in row for key in key_columns):
                    predicate = [table.c.organization_id == organization_id]
                    predicate.extend(table.c[key] == row[key] for key in key_columns)
                    existing = connection.execute(select(table).where(*predicate)).mappings().first()
                if existing and 'facility_code' in existing and existing['facility_code'] not in codes:
                    raise ValueError('Existing source row belongs to a facility outside the requested scope.')
                if existing and 'source_system' in existing and existing['source_system'] != row.get('source_system'):
                    raise ValueError('A source writer cannot overwrite another source system record.')
                for candidate in (existing, row):
                    if not candidate:
                        continue
                    if candidate.get('room_id') and name != 'rooms':
                        owner = connection.scalar(select(canonical.rooms.c.facility_code).where(
                            canonical.rooms.c.organization_id == organization_id,
                            canonical.rooms.c.room_id == candidate['room_id']))
                        if owner not in codes:
                            raise ValueError('Referenced room is outside the requested scope.')
                    if candidate.get('stay_id') and name != 'census_stays':
                        owner = connection.scalar(select(canonical.census_stays.c.facility_code).where(
                            canonical.census_stays.c.organization_id == organization_id,
                            canonical.census_stays.c.stay_id == candidate['stay_id']))
                        if owner not in codes:
                            raise ValueError('Referenced stay is outside the requested scope.')
                    if candidate.get('bed_id') and name != 'beds':
                        room = canonical.beds.join(canonical.rooms,
                            (canonical.beds.c.organization_id == canonical.rooms.c.organization_id)
                            & (canonical.beds.c.room_id == canonical.rooms.c.room_id))
                        owner = connection.scalar(select(canonical.rooms.c.facility_code).select_from(room).where(
                            canonical.beds.c.organization_id == organization_id,
                            canonical.beds.c.bed_id == candidate['bed_id']))
                        if owner not in codes:
                            raise ValueError('Referenced bed is missing or outside the requested facility scope.')
                row['organization_id'] = organization_id
                yield row
        result[name] = upsert_rows(connection, table, prepared_rows(), batch_size=batch_size)
    validate_source_history(connection, organization_id, codes)
    return result


def validate_source_history(connection, organization_id, facility_codes):
    """Publication invariants, not a test suite. Reject ambiguous source histories."""
    args = {'organization': organization_id, 'codes': list(facility_codes)}
    checks = {
        'Overlapping census stays for one resident': """
            SELECT 1 FROM census_stays a JOIN census_stays b
              ON a.organization_id=b.organization_id AND a.resident_id=b.resident_id AND a.stay_id<>b.stay_id
            WHERE a.organization_id=:organization AND a.facility_code=ANY(:codes)
              AND daterange(coalesce(a.admission_date,a.known_from), a.discharge_date, '[)')
                  && daterange(coalesce(b.admission_date,b.known_from), b.discharge_date, '[)') LIMIT 1""",
        'Payer period is outside its census stay': """
            SELECT 1 FROM payer_stays p JOIN census_stays s USING(organization_id,stay_id)
            WHERE s.organization_id=:organization AND s.facility_code=ANY(:codes)
              AND (p.started_on < coalesce(s.admission_date,s.known_from)
                OR (s.discharge_date IS NOT NULL AND (p.ended_on IS NULL OR p.ended_on>s.discharge_date))) LIMIT 1""",
        'Overlapping primary payer periods': """
            SELECT 1 FROM payer_stays p JOIN census_stays s USING(organization_id,stay_id)
            JOIN payer_stays q ON p.organization_id=q.organization_id AND p.stay_id=q.stay_id
                AND p.payer_stay_id<>q.payer_stay_id
            WHERE s.organization_id=:organization AND s.facility_code=ANY(:codes)
              AND daterange(p.started_on,p.ended_on,'[)') && daterange(q.started_on,q.ended_on,'[)') LIMIT 1""",
        'Bed assignment belongs to another facility': """
            SELECT 1 FROM resident_bed_assignments a JOIN census_stays s USING(organization_id,stay_id)
            JOIN beds b ON b.organization_id=a.organization_id AND b.bed_id=a.bed_id
            JOIN rooms r ON r.organization_id=b.organization_id AND r.room_id=b.room_id
            WHERE a.organization_id=:organization AND s.facility_code=ANY(:codes)
              AND s.facility_code<>r.facility_code LIMIT 1""",
        'Overlapping bed assignments': """
            SELECT 1 FROM resident_bed_assignments a JOIN resident_bed_assignments b
              ON a.organization_id=b.organization_id AND a.assignment_id<>b.assignment_id
                AND (a.bed_id=b.bed_id OR a.stay_id=b.stay_id)
            JOIN census_stays s ON s.organization_id=a.organization_id AND s.stay_id=a.stay_id
            WHERE a.organization_id=:organization AND s.facility_code=ANY(:codes)
              AND tstzrange(a.started_at,a.ended_at,'[)') && tstzrange(b.started_at,b.ended_at,'[)') LIMIT 1""",
        'Bed reservations overlap for different residents': """
            SELECT 1 FROM bed_reservations a JOIN bed_reservations b
              ON a.organization_id=b.organization_id AND a.bed_id=b.bed_id
                AND a.reservation_id<>b.reservation_id AND a.resident_id<>b.resident_id
            JOIN beds bed ON bed.organization_id=a.organization_id AND bed.bed_id=a.bed_id
            JOIN rooms r ON r.organization_id=bed.organization_id AND r.room_id=bed.room_id
            WHERE a.organization_id=:organization AND r.facility_code=ANY(:codes)
              AND tstzrange(a.started_at,a.ended_at,'[)') && tstzrange(b.started_at,b.ended_at,'[)') LIMIT 1""",
    }
    for message, sql in checks.items():
        if connection.scalar(text(sql), args):
            raise ValueError(message + '; correct the source records before publishing.')
