"""Track Medicaid applications independently of retroactive payer assignments."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0002_medicaid_applications'
down_revision = '0001_shared_database'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('medicaid_applications',
        sa.Column('stay_id', sa.Uuid(), sa.ForeignKey('res_stays.stay_id'), primary_key=True),
        sa.Column('payer_stay_id', sa.Uuid(), sa.ForeignKey('res_payer_stays.payer_stay_id'), nullable=False, unique=True),
        sa.Column('application_date', sa.Date(), nullable=False),
        sa.Column('approved_date', sa.Date()),
        sa.Column('approved_payer_id', sa.Uuid(), sa.ForeignKey('payers.payer_id')),
        sa.CheckConstraint('(approved_date IS NULL AND approved_payer_id IS NULL) OR '
            '(approved_date IS NOT NULL AND approved_payer_id IS NOT NULL AND approved_date >= application_date)'),
    )
    op.create_index('ix_medicaid_applications_application_date', 'medicaid_applications', ['application_date'])
    op.create_index('ix_medicaid_applications_approved_date', 'medicaid_applications', ['approved_date'])
    op.add_column('sandbox_adt_active_stays', sa.Column('medicaid_approval', postgresql.JSONB()))


def downgrade():
    raise RuntimeError('Downgrade would discard Medicaid application history; use a reviewed forward migration.')
