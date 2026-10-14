"""staffing roles become departments and positions

Empties the six staffing tables and replaces their role checks; the update
that applies it rebuilds them from the new roles.

Revision: a765c386a2e8
Parent: 7e1f9fd6d196
"""
from alembic import op
import sqlalchemy as sa


revision = 'a765c386a2e8'
down_revision = '7e1f9fd6d196'
branch_labels = None
depends_on = None
# List any immutable helper/data files imported by this revision, relative to migrations/.
artifacts = ()
# For a later NOT NULL/drop/constraint migration that requires earlier data work.
required_backfills = ()


# The staffing roles as shared/staffing.py now lists them: four departments,
# their role groups and 22 positions, replacing the 11 nursing, therapy and
# support roles. Written out, not imported: this migration must mean the same
# thing whatever the roles become later.
ROLE_CODES = (
    'administrator', 'business_office_manager', 'hr_payroll',
    'rn', 'lpn', 'lpn_supervisor', 'lpn_wound_nurse', 'cna', 'cma',
    'cook', 'dietary_aide', 'dietary_manager', 'dietician',
    'housekeeper', 'housekeeping_director', 'laundry_aide',
    'maintenance_director', 'social_services_director', 'transportation_driver',
    'adon_lpn', 'mds_rn', 'staffing_coordinator',
)
# Every table whose role column carries the check. All of them are generated
# from the roles, so their old rows are emptied here -- they would fail the new
# check -- and the staffing generators rebuild them in the same update, whose
# rules fingerprint sees shared/staffing.py change.
TABLES = ('daily_staffing_facts', 'daily_staff_hours', 'staff_members', 'daily_agency_facts',
    'daily_overtime_facts', 'daily_onboarding_facts')


def upgrade():
    # One TRUNCATE: daily_staff_hours references staff_members.
    op.execute('TRUNCATE ' + ', '.join(TABLES))
    allowed = ', '.join(f"'{code}'" for code in ROLE_CODES)
    for table in TABLES:
        op.drop_constraint(f'{table}_role_check', table, type_='check')
        op.create_check_constraint(f'{table}_role_check', table, f'role IN ({allowed})')


def downgrade():
    raise ValueError('Use a new corrective migration; automatic downgrades are disabled.')
