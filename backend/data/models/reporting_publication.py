"""Complete reporting dates, including known zero activity, shared by every writer."""
from sqlalchemy import Column, Date, DateTime, ForeignKey, Index, JSON, MetaData, String, Table, func

from data.models.facilities import facilities

metadata = MetaData()
loads = Table('reporting_source_loads', metadata,
    Column('load_id', String(36), primary_key=True),
    Column('organization_id', String(64), nullable=False),
    Column('status', String(24), nullable=False),
    Column('scope', JSON, nullable=False),
    Column('updated_at', DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index('ix_reporting_load_status', 'status', 'organization_id'),
)
coverage = Table(
    "reporting_dataset_coverage", metadata,
    Column("dataset", String(80), primary_key=True),
    Column("facility_code", String(12), ForeignKey(facilities.c.facility_code), primary_key=True),
    Column("date", Date, primary_key=True),
    Column("rules_version", String(80), nullable=False),
    Column("refreshed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("ix_reporting_coverage_facility_date", "facility_code", "date"),
)
