"""add the ncna staffing role

Revision: de59ca37a20b
Parent: aee7e6ca4ead
"""
from alembic import op
import sqlalchemy as sa


revision = 'de59ca37a20b'
down_revision = 'aee7e6ca4ead'
branch_labels = None
depends_on = None
# List any immutable helper/data files imported by this revision, relative to migrations/.
artifacts = ()
# For a later NOT NULL/drop/constraint migration that requires earlier data work.
required_backfills = ()


# The staffing roles as shared/staffing.py now lists them: NCNA, the
# non-certified nursing assistant, joins Direct Care after CNA. Written out,
# not imported: this migration must mean the same thing whatever the roles
# become later.
ROLE_CODES = (
    'administrator', 'business_office_manager', 'hr_payroll',
    'rn', 'lpn', 'lpn_supervisor', 'lpn_wound_nurse', 'cna', 'ncna', 'cma',
    'cook', 'dietary_aide', 'dietary_manager', 'dietician',
    'housekeeper', 'housekeeping_director', 'laundry_aide',
    'maintenance_director', 'social_services_director', 'transportation_driver',
    'adon_lpn', 'mds_rn', 'staffing_coordinator',
)
# Every table whose role column carries the check. Their rows all pass the
# wider check, so nothing is emptied: the staffing generators add NCNA's rows in
# the update that applies this, whose rules fingerprint sees shared/staffing.py change.
TABLES = ('daily_staffing_facts', 'daily_staff_hours', 'staff_members', 'daily_agency_facts',
    'daily_overtime_facts', 'daily_onboarding_facts', 'daily_training_facts', 'monthly_staffing_cost_facts')


def upgrade():
    allowed = ', '.join(f"'{code}'" for code in ROLE_CODES)
    for table in TABLES:
        op.drop_constraint(f'{table}_role_check', table, type_='check')
        op.create_check_constraint(f'{table}_role_check', table, f'role IN ({allowed})')


def downgrade():
    raise ValueError('Use a new corrective migration; automatic downgrades are disabled.')
