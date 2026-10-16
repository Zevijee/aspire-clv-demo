"""coded residents counted in their coding month

Revision: 9f12ea5ad29f
Parent: 47d4f047dfa9
"""
from alembic import op
import sqlalchemy as sa


revision = '9f12ea5ad29f'
down_revision = '47d4f047dfa9'
branch_labels = None
depends_on = None
# List any immutable helper/data files imported by this revision, relative to migrations/.
artifacts = ()
# For a later NOT NULL/drop/constraint migration that requires earlier data work.
required_backfills = ()


def upgrade():
    # No DDL: the _residents columns of monthly_pdpm_census_facts now count
    # residents in the month they were coded, not every month they carry the
    # code. The generator's rule change rebuilds them in the same update.
    pass


def downgrade():
    raise ValueError('Use a new corrective migration; automatic downgrades are disabled.')
