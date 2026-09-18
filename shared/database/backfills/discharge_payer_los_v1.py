"""Repair historical discharge LOS from the final payer period, in UUID order.

Immutable job: corrections belong in a new file with a new job ID.
Future rows are already written correctly by the generator.
"""
from sqlalchemy import text

name = '0001_discharge_payer_los'
depends_on = ()
required_revision = '0001_shared_database'
required_tables = ('discharge_logs', 'res_payer_stays')


def run_batch(connection, checkpoint, batch_size):
    checkpoint = dict(checkpoint)
    if 'upper' not in checkpoint:
        upper = connection.scalar(text('SELECT stay_id FROM discharge_logs ORDER BY stay_id DESC LIMIT 1'))
        checkpoint['upper'] = str(upper) if upper else None
    if checkpoint['upper'] is None:
        return checkpoint, 0, 0, True
    rows = connection.execute(text('''
        SELECT d.stay_id, d.discharge_date, d.payer_id, d.los,
               p.start_date, p.end_date, p.payer_id AS final_payer_id
        FROM discharge_logs d
        LEFT JOIN LATERAL (
            SELECT start_date, end_date, payer_id FROM res_payer_stays
            WHERE stay_id = d.stay_id AND end_reason = 'discharge'
            ORDER BY period_number DESC LIMIT 1
        ) p ON true
        WHERE d.stay_id <= CAST(:upper AS uuid)
          AND (CAST(:after AS uuid) IS NULL OR d.stay_id > CAST(:after AS uuid))
        ORDER BY d.stay_id LIMIT :batch_size
    '''), dict(upper=checkpoint['upper'], after=checkpoint.get('after'), batch_size=batch_size)).mappings().all()
    updates = []
    for row in rows:
        if (row['start_date'] is None or row['end_date'] != row['discharge_date']
                or row['payer_id'] != row['final_payer_id']):
            raise ValueError('Discharge LOS backfill needs a matching final payer period for '
                f"stay {row['stay_id']}. Repair its source data, then rerun upgrade to resume.")
        los = (row['discharge_date'] - row['start_date']).days
        if los <= 0:
            raise ValueError(f"Invalid final payer dates for stay {row['stay_id']}.")
        if row['los'] != los:
            updates.append(dict(stay_id=row['stay_id'], los=los))
    if updates:
        connection.execute(text('UPDATE discharge_logs SET los=:los WHERE stay_id=:stay_id'), updates)
    if rows:
        checkpoint['after'] = str(rows[-1]['stay_id'])
    complete = not rows or checkpoint.get('after') == checkpoint['upper']
    return checkpoint, len(rows), len(updates), complete
