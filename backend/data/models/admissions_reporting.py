"""Shared table definitions; importing this module does not access the database."""

from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, BigInteger, JSON, MetaData, String, Table, func
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()
daily = Table(
    "adt_admissions_daily",
    metadata,
    Column("admission_date", Date, primary_key=True),
    Column("facility_code", String(12), primary_key=True),
    Column("payer_type", String(40), primary_key=True),
    Column("total_admissions", Integer, nullable=False),
    Column("readmission_count", Integer, nullable=False),
    Column("readmission_within_30_days_count", Integer, nullable=False),
)
sources = Table(
    "adt_admissions_sources_daily",
    metadata,
    Column("admission_date", Date, primary_key=True),
    Column("facility_code", String(12), primary_key=True),
    Column("payer_type", String(40), primary_key=True),
    Column("admission_source_type", String(40), primary_key=True),
    Column("admission_source_name", String(160), primary_key=True),
    Column("admission_count", Integer, nullable=False),
)
state = Table(
    "adt_reporting_state",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("revision", BigInteger, nullable=False),
    Column("ready", Boolean, nullable=False),
    Column("first_date", Date),
    Column("latest_date", Date),
    Column("admission_count", BigInteger, nullable=False),
    Column("refreshed_at", DateTime(timezone=True)),
)
cache = Table(
    "adt_report_cache",
    metadata,
    Column("cache_key", String(64), primary_key=True),
    Column("revision", BigInteger, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
