"""monthly pdpm category days

Revision: 1d47c4a12e87
Parent: dc19400f4904
"""
from alembic import op
import sqlalchemy as sa


revision = '1d47c4a12e87'
down_revision = 'dc19400f4904'
branch_labels = None
depends_on = None
# List any immutable helper/data files imported by this revision, relative to migrations/.
artifacts = ()
# For a later NOT NULL/drop/constraint migration that requires earlier data work.
required_backfills = ()


COLUMNS = ('coded_days', 'depression_days', 'medical_management_days', 'slp_sa_days', 'behavioral_days',
    'reduced_physical_function_days', 'nursing_gg_15_16_days')
CATEGORIES = COLUMNS[1:]


def upgrade():
    # The table is populated: each column starts at zero for the rows already
    # there, and the default is dropped after. The generator's rule change
    # rebuilds the table in the same update, which fills them.
    for column in COLUMNS:
        op.add_column('monthly_pdpm_census_facts', sa.Column(column, sa.Integer(), nullable=False, server_default='0'))
        op.alter_column('monthly_pdpm_census_facts', column, server_default=None)
    # Autogenerate writes no CHECK constraints: by hand, as the staged schema has them.
    op.create_check_constraint('ck_monthly_pdpm_census_facts_coded_days', 'monthly_pdpm_census_facts',
        'coded_days BETWEEN 0 AND resident_days')
    op.create_check_constraint('ck_monthly_pdpm_census_facts_category_days', 'monthly_pdpm_census_facts',
        ' AND '.join(f'{column} BETWEEN 0 AND coded_days' for column in CATEGORIES))


def downgrade():
    raise ValueError('Use a new corrective migration; automatic downgrades are disabled.')
