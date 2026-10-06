"""add ard to pdpm assessments

Revision: febf9d4d5027
Parent: 435157998fcf
"""
from alembic import op
import sqlalchemy as sa


revision = 'febf9d4d5027'
down_revision = '435157998fcf'
branch_labels = None
depends_on = None
# List any immutable helper/data files imported by this revision, relative to migrations/.
artifacts = ()
# For a later NOT NULL/drop/constraint migration that requires earlier data work.
required_backfills = ()


def upgrade():
    # Added nullable, filled, then made NOT NULL, as coded_date was: existing
    # rows take the payer period's first day, and the next census_logs rebuild
    # draws the real ARD.
    op.add_column('pdpm_assessments', sa.Column('ard', sa.Date(), nullable=True))
    op.execute("""
        UPDATE pdpm_assessments a SET ard = c.start
        FROM (SELECT payer_stay_id, lower(in_bed) AS start FROM census_logs WHERE segment = 1) c
        WHERE c.payer_stay_id = a.payer_stay_id
    """)
    op.alter_column('pdpm_assessments', 'ard', nullable=False)


def downgrade():
    raise ValueError('Use a new corrective migration; automatic downgrades are disabled.')
