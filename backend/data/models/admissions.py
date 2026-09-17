"""Shared table definitions; importing this module does not access the database."""

from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, BigInteger, JSON, MetaData, String, Table, func
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()
facility_reference = Table(
    "facilities",
    metadata,
    Column("facility_code", String(12), primary_key=True),
)
admissions = Table(
    "adt_admissions",
    metadata,
    Column("admission_id", String(36), primary_key=True),
    Column("facility_code", String(12), ForeignKey("facilities.facility_code"), nullable=False),
    Column("resident_id", String(36), nullable=False),
    Column("resident_name", String(120), nullable=False),
    Column("admission_date", Date, nullable=False),
    Column("payer_type", String(40), nullable=False),
    Column("payer_name", String(120), nullable=False),
    Column("admission_source_type", String(40), nullable=False),
    Column("admission_source_name", String(160), nullable=False),
    Column("is_readmission", Boolean, nullable=False),
    Column("readmission_days_since_prior", Integer, nullable=True),
    CheckConstraint(
        "payer_type IN ('Medicare', 'Medicare Advantage', 'Medicare HMO', 'Managed Medicaid', "
        "'Medicaid', 'Hospice', 'Private Pay')",
        name="valid_adt_admission_payer_type",
    ),
)
