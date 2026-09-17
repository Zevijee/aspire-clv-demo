"""Shared table definitions; importing this module does not access the database."""

from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, BigInteger, JSON, MetaData, String, Table, func
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()
states = Table('states', metadata,
    Column('state_code', String(2), primary_key=True),
    Column('name', String(80), nullable=False),
)
facilities = Table(
    "facilities",
    metadata,
    Column("facility_code", String(12), primary_key=True),
    Column("organization_id", String(64)),
    Column("name", String(160), nullable=False, unique=True),
    Column("city", String(80), nullable=False),
    Column("state", String(2), ForeignKey(states.c.state_code, name='fk_facilities_state'), nullable=False),
    Column("portfolio", String(80), nullable=False),
    Column("region", String(80), nullable=False),
    Column("market", String(100), nullable=False),
    Column("operating_group", String(100), nullable=False),
    Column("licensed_beds", Integer, nullable=False),
    Column("primary_service", String(100), nullable=False),
    Column("acuity_profile", String(20), nullable=False),
    Column("operating_maturity", String(20), nullable=False),
    Column("opened_date", Date, nullable=False),
    Column("services", JSON, nullable=False),
)
