"""Compatibility payer-interval read model; DDL is migration-owned."""
from sqlalchemy import Column, Date, MetaData, String, Table
metadata = MetaData()
periods = Table('adt_payer_periods', metadata,
    Column('period_id', String(36), primary_key=True), Column('stay_id', String(36), nullable=False),
    Column('facility_code', String(12), nullable=False), Column('start_date', Date, nullable=False),
    Column('end_date', Date), Column('payer_type', String(40), nullable=False),
    Column('payer_name', String(120), nullable=False))
