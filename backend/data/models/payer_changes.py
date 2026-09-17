"""Shared table definitions; importing this module does not access the database."""

from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, BigInteger, JSON, MetaData, String, Table, func
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()
Table("facilities", metadata, Column("facility_code", String(12), primary_key=True))
payer_changes = Table(
    "adt_payer_changes",
    metadata,
    Column("change_id", String(36), primary_key=True),
    Column("facility_code", String(12), ForeignKey("facilities.facility_code"), nullable=False),
    Column("resident_id", String(36), nullable=False),
    Column("resident_name", String(120), nullable=False),
    Column("effective_date", Date, nullable=False),
    Column("previous_payer_start_date", Date, nullable=False),
    Column("new_payer_end_date", Date, nullable=True),
    Column("previous_payer_type", String(40), nullable=False),
    Column("previous_payer_name", String(120), nullable=False),
    Column("new_payer_type", String(40), nullable=False),
    Column("new_payer_name", String(120), nullable=False),
    Column("change_category", String(40), nullable=False),
    CheckConstraint(
        "(change_category = 'Payer type' AND previous_payer_type <> new_payer_type) OR "
        "(change_category = 'Plan only' AND previous_payer_type = new_payer_type "
        "AND previous_payer_name <> new_payer_name)",
        name="valid_payer_change_category",
    ),
    Index("ix_payer_changes_date_id", "effective_date", "change_id"),
    Index("ix_payer_changes_facility_date", "facility_code", "effective_date"),
    Index("ix_payer_changes_previous_date", "previous_payer_type", "effective_date"),
)
