"""${message}

Revision: ${up_revision}
Parent: ${down_revision | comma,n}
"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}
# List any immutable helper/data files imported by this revision, relative to migrations/.
artifacts = ()
# For a later NOT NULL/drop/constraint migration that requires earlier data work.
required_backfills = ()


def upgrade():
    ${upgrades if upgrades else "pass"}


def downgrade():
    raise ValueError('Use a new corrective migration; automatic downgrades are disabled.')
