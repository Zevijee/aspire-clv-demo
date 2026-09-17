"""Shared state references, adopting existing facility codes without reseeding."""
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from data.models.facilities import states, facilities
from domain.us_states import US_STATES


def upgrade(connection):
    states.create(connection, checkfirst=True)
    # Shared reference data, not fake facility/population generation.
    names = dict(US_STATES)
    for code in connection.scalars(select(facilities.c.state).distinct()):
        names.setdefault(code, code)
    connection.execute(insert(states).values([
        dict(state_code=code, name=name) for code, name in names.items()
    ]).on_conflict_do_nothing(index_elements=['state_code']))
    exists = connection.scalar(text("""SELECT 1 FROM pg_constraint
        WHERE conrelid='facilities'::regclass AND conname='fk_facilities_state'"""))
    if not exists:
        connection.execute(text('ALTER TABLE facilities ADD CONSTRAINT fk_facilities_state '
            'FOREIGN KEY (state) REFERENCES states (state_code)'))
