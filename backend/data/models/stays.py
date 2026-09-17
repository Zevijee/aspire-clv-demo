"""Shared table definitions; importing this module does not access the database."""

from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, BigInteger, JSON, MetaData, String, Table, func
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()
Table("facilities", metadata, Column("facility_code", String(12), primary_key=True))
stays = Table(
    "adt_resident_stays",
    metadata,
    Column("stay_id", String(36), primary_key=True),
    Column("facility_code", String(12), ForeignKey("facilities.facility_code"), nullable=False),
    Column("resident_id", String(36), nullable=False),
    Column("resident_name", String(120), nullable=False),
    Column("start_date", Date, nullable=False),
    Column("end_date", Date),
    Column("opening_resident", Boolean, nullable=False),
    Column("initial_payer_type", String(40)),
    Column("initial_payer_name", String(120)),
    CheckConstraint("end_date IS NULL OR end_date >= start_date", name="valid_resident_stay_dates"),
)
census = Table(
    "adt_census_daily",
    metadata,
    Column("facility_code", String(12), ForeignKey("facilities.facility_code"), primary_key=True),
    Column("census_date", Date, primary_key=True),
    Column("opening_census", Integer, nullable=False),
    Column("closing_census", Integer, nullable=False),
    Column("admissions", Integer, nullable=False),
    Column("discharges", Integer, nullable=False),
    CheckConstraint(
        "closing_census = opening_census + admissions - discharges", name="census_daily_balances"
    ),
    CheckConstraint("opening_census >= 0 AND closing_census >= 0", name="census_nonnegative"),
)
state = Table(
    "adt_census_state",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("ready", Boolean, nullable=False),
    Column("version", String(80)),
    Column("start_date", Date),
    Column("end_date", Date),
    Column("input_fingerprint", String(64)),
    Column("discharge_count", Integer),
    Column("stay_count", Integer),
)
