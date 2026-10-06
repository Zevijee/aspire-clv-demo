"""add coded date to pdpm assessments

Revision: 435157998fcf
Parent: 7894c57a2aee
"""
from alembic import op
import sqlalchemy as sa


revision = '435157998fcf'
down_revision = '7894c57a2aee'
branch_labels = None
depends_on = None
# List any immutable helper/data files imported by this revision, relative to migrations/.
artifacts = ()
# For a later NOT NULL/drop/constraint migration that requires earlier data work.
required_backfills = ()


def upgrade():
    # Added nullable, filled, then made NOT NULL: the table is populated, and a
    # required column with no default would fail. Existing rows are filled with
    # what they meant until now -- coded from the payer period's first day, the
    # start of its first census row -- and the next census_logs rebuild draws
    # the real coding lag.
    op.add_column('pdpm_assessments', sa.Column('coded_date', sa.Date(), nullable=True))
    op.execute("""
        UPDATE pdpm_assessments a SET coded_date = c.start
        FROM (SELECT payer_stay_id, lower(in_bed) AS start FROM census_logs WHERE segment = 1) c
        WHERE c.payer_stay_id = a.payer_stay_id
    """)
    op.alter_column('pdpm_assessments', 'coded_date', nullable=False)


def downgrade():
    raise ValueError('Use a new corrective migration; automatic downgrades are disabled.')
