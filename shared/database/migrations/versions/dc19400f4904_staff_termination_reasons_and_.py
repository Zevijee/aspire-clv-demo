"""staff termination reasons and replacements

Revision: dc19400f4904
Parent: 40a93d80327d
"""
from alembic import op
import sqlalchemy as sa


revision = 'dc19400f4904'
down_revision = '40a93d80327d'
branch_labels = None
depends_on = None
# List any immutable helper/data files imported by this revision, relative to migrations/.
artifacts = ()
# For a later NOT NULL/drop/constraint migration that requires earlier data work.
required_backfills = ()


# The codes as of this revision (shared/turnover_reasons.py), written out: a
# revision must not import a module that may change after it.
REASON_CODES = ('better_pay', 'schedule', 'personal', 'relocated', 'school', 'retired', 'job_abandonment',
    'attendance', 'performance', 'policy')


def upgrade():
    op.add_column('staff_members', sa.Column('termination_reason', sa.String(), nullable=True))
    op.add_column('staff_members', sa.Column('replaces_staff_id', sa.Uuid(), nullable=True))
    # Leavers already on the roster have no reason yet; a placeholder until the
    # roster is rebuilt with drawn ones, which the generator's rule change brings.
    op.execute("UPDATE staff_members SET termination_reason = 'personal' WHERE termination_date IS NOT NULL")
    # Autogenerate writes no CHECK constraints: by hand, as the staged schema has them.
    op.create_check_constraint('staff_members_termination_reason_check', 'staff_members',
        '(termination_reason IS NULL) = (termination_date IS NULL)')
    op.create_check_constraint('staff_members_termination_reason_code_check', 'staff_members',
        'termination_reason IS NULL OR termination_reason IN (' + ', '.join(f"'{code}'" for code in REASON_CODES) + ')')


def downgrade():
    raise ValueError('Use a new corrective migration; automatic downgrades are disabled.')
