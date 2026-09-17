"""Canonical source writes shared by ingestion and demo loading.

The caller owns the transaction and supplies resolved identities. Foreign keys
enforce residents before stays and stays before coverage. No fake generation or
report refresh belongs here.
"""
from sqlalchemy import select
from data.models import canonical as c
from data.writers.core import write_rows


def write_residents(connection, rows, *, organization_id, source_system, batch_size=1000):
    records = [dict(row, organization_id=organization_id) for row in rows]
    result = write_rows(connection, c.residents, records, batch_size=batch_size)
    write_rows(connection, c.resident_source_keys, [dict(organization_id=organization_id,
        source_system=source_system, external_key=row['resident_id'], resident_id=row['resident_id'])
        for row in records], batch_size=batch_size)
    return result


def _write_owned(connection, table, rows, id_column, organization_id, source_system, batch_size):
    records = [dict(row, organization_id=organization_id, source_system=source_system) for row in rows]
    for offset in range(0, len(records), batch_size):
        ids = [row[id_column] for row in records[offset:offset + batch_size]]
        conflict = connection.scalar(select(table.c[id_column]).where(
            table.c.organization_id == organization_id, table.c[id_column].in_(ids),
            table.c.source_system != source_system).limit(1))
        if conflict:
            raise ValueError('A source write cannot replace a record owned by another source system.')
    return write_rows(connection, table, records, batch_size=batch_size)


def write_census_stays(connection, rows, *, organization_id, source_system, batch_size=1000):
    result = _write_owned(connection, c.census_stays, rows, 'stay_id', organization_id, source_system, batch_size)
    write_rows(connection, c.stay_source_keys, [dict(organization_id=organization_id,
        source_system=source_system, external_key=row['stay_id'], stay_id=row['stay_id'])
        for row in rows], batch_size=batch_size)
    return result


def write_payer_stays(connection, rows, *, organization_id, source_system, batch_size=1000):
    return _write_owned(connection, c.payer_stays, rows, 'payer_stay_id',
        organization_id, source_system, batch_size)


def replace_payer_stays(connection, rows, *, organization_id, source_system, batch_size=1000):
    """Replace complete interval histories for the explicitly supplied stays.

    Call only for an authorized replacement, supplying each stay's retained
    history as well as its corrected intervals. Delete before inserting so
    changing interval dates cannot collide with obsolete unique date keys.
    The caller's transaction makes the replacement atomic.
    """
    if not connection.in_transaction():
        raise ValueError('Coverage replacement requires a caller-owned transaction.')
    rows = list(rows)
    ids = sorted({row['stay_id'] for row in rows})
    for offset in range(0, len(ids), batch_size):
        scope = (c.payer_stays.c.organization_id == organization_id,
            c.payer_stays.c.stay_id.in_(ids[offset:offset + batch_size]))
        if connection.scalar(select(c.payer_stays.c.payer_stay_id).where(*scope,
                c.payer_stays.c.source_system != source_system).limit(1)):
            raise ValueError('Coverage replacement cannot overwrite another source system history.')
        connection.execute(c.payer_stays.delete().where(*scope,
            c.payer_stays.c.source_system == source_system))
    return write_payer_stays(connection, rows, organization_id=organization_id,
        source_system=source_system, batch_size=batch_size)
