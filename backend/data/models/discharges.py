"""Shared table definitions; importing this module does not access the database."""

from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, BigInteger, JSON, MetaData, String, Table, func
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()
Table("facilities", metadata, Column("facility_code", String(12), primary_key=True))
discharges = Table(
    "adt_discharges",
    metadata,
    Column("discharge_id", String(36), primary_key=True),
    Column("facility_code", String(12), ForeignKey("facilities.facility_code"), nullable=False),
    Column("resident_id", String(36), nullable=False),
    Column("resident_name", String(120), nullable=False),
    Column("start_date", Date, nullable=False),
    Column("discharge_date", Date, nullable=False),
    Column("payer_type", String(40), nullable=False),
    Column("payer_name", String(120), nullable=False),
    Column("destination_type", String(40), nullable=False),
    Column("destination_name", String(160), nullable=False),
    Column("discharge_type", String(40), nullable=False),
    Column("los_days", Integer, nullable=False),
    CheckConstraint("discharge_date >= start_date", name="valid_discharge_dates"),
    CheckConstraint("los_days = discharge_date - start_date", name="valid_discharge_los"),
    CheckConstraint(
        "discharge_type IN ('Routine', 'Transfer', 'Deceased', 'AMA')", name="valid_discharge_type"
    ),
    Index("ix_discharges_date_id", "discharge_date", "discharge_id"),
    Index("ix_discharges_facility_date", "facility_code", "discharge_date"),
)
