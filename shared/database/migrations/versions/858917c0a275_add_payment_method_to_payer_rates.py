"""add payment method to payer rates

Revision: 858917c0a275
Parent: 6e0cb6c216ca
"""
from alembic import op
import sqlalchemy as sa


revision = '858917c0a275'
down_revision = '6e0cb6c216ca'
branch_labels = None
depends_on = None
# List any immutable helper/data files imported by this revision, relative to migrations/.
artifacts = ()
# For a later NOT NULL/drop/constraint migration that requires earlier data work.
required_backfills = ()


# How each existing contract pays, fixed here so this revision's checksum covers
# it. The same rule as PayerRateGenerator: Original Medicare pays PDPM; Medicare
# Advantage contracts draw from the facility and plan ids -- 20% of HMO and 80% of
# other Advantage contracts pay PDPM, the rest a flat per diem; every other payer
# pays per diem. The separator is written ':' || 'payment-method' because a
# literal ':payment' reads as a bind parameter to SQLAlchemy's text(); the
# first attempt failed on it and rolled back without applying anything.
FILL = """
UPDATE facility_payer_rates r
SET payment_method = CASE
    WHEN p.payer_type = 'medicare' THEN 'pdpm'
    WHEN p.payer_type IN ('medicare_hmo', 'medicare_comm') THEN
        CASE WHEN ('x' || substr(md5(r.facility_id::text || ':' || r.payer_id::text || ':' || 'payment-method'),
                1, 8))::bit(32)::bigint / 4294967296.0
            < CASE p.payer_type WHEN 'medicare_hmo' THEN 0.2 ELSE 0.8 END
        THEN 'pdpm' ELSE 'per_diem' END
    ELSE 'per_diem' END
FROM payers p
WHERE p.payer_id = r.payer_id
"""


def upgrade():
    # Added nullable, filled, then required: a NOT NULL column cannot be added
    # to a populated table without a default, and no single default is right.
    op.add_column('facility_payer_rates', sa.Column('payment_method', sa.String(), nullable=True))
    op.execute(FILL)
    op.alter_column('facility_payer_rates', 'payment_method', nullable=False)
    op.create_check_constraint('facility_payer_rates_payment_method_check', 'facility_payer_rates',
        "payment_method IN ('pdpm', 'per_diem')")


def downgrade():
    raise ValueError('Use a new corrective migration; automatic downgrades are disabled.')
