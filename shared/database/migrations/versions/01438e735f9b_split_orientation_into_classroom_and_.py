"""split orientation into classroom and floor

Revision: 01438e735f9b
Parent: de59ca37a20b
"""
from alembic import op
import sqlalchemy as sa


revision = '01438e735f9b'
down_revision = 'de59ca37a20b'
branch_labels = None
depends_on = None
# List any immutable helper/data files imported by this revision, relative to migrations/.
artifacts = ()
# For a later NOT NULL/drop/constraint migration that requires earlier data work.
required_backfills = ()


# Orientation splits into the classroom and the floor. Both tables are rebuilt
# by the update that applies this (onboarding_summary's rules change, and
# staffing_cost_summary is built from it), so until then each row's orientation
# is carried over whole as classroom: totals stay right in between.
TABLES = (
    ('daily_onboarding_facts', (7, 1), (10, 2)),
    ('monthly_staffing_cost_facts', (10, 1), (13, 2)),
)


def upgrade():
    for table, hours, wages in TABLES:
        for kind in ('classroom', 'floor'):
            op.add_column(table, sa.Column(f'{kind}_orientation_hours', sa.Numeric(*hours), nullable=True))
            op.add_column(table, sa.Column(f'{kind}_orientation_wages', sa.Numeric(*wages), nullable=True))
        op.execute(f"""UPDATE {table} SET classroom_orientation_hours = orientation_hours,
            classroom_orientation_wages = orientation_wages, floor_orientation_hours = 0, floor_orientation_wages = 0""")
        for kind in ('classroom', 'floor'):
            op.alter_column(table, f'{kind}_orientation_hours', nullable=False)
            op.alter_column(table, f'{kind}_orientation_wages', nullable=False)
        # Dropping the columns drops daily_onboarding_facts_check, which names them.
        op.drop_column(table, 'orientation_wages')
        op.drop_column(table, 'orientation_hours')
    op.create_check_constraint('daily_onboarding_facts_check', 'daily_onboarding_facts',
        'new_hires > 0 AND bonuses >= 0 AND classroom_orientation_hours >= 0 '
        'AND classroom_orientation_wages >= 0 AND floor_orientation_hours >= 0 AND floor_orientation_wages >= 0')


def downgrade():
    raise ValueError('Use a new corrective migration; automatic downgrades are disabled.')
