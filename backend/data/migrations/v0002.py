"""Allow Medicare HMO alongside existing payer types without changing any records."""
from sqlalchemy import text


def upgrade(connection):
    connection.execute(text('ALTER TABLE adt_admissions DROP CONSTRAINT IF EXISTS valid_adt_admission_payer_type'))
    connection.execute(text("""
        ALTER TABLE adt_admissions ADD CONSTRAINT valid_adt_admission_payer_type
        CHECK (payer_type IN ('Medicare', 'Medicare Advantage', 'Medicare HMO',
                              'Managed Medicaid', 'Medicaid', 'Hospice', 'Private Pay'))
    """))
