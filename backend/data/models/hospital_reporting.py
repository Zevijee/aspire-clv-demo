"""Shared table definitions; importing this module does not access the database."""

from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, BigInteger, JSON, MetaData, String, Table, func
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()
hospitals = Table('adt_referring_hospitals', metadata,
    Column('hospital', String(160), primary_key=True),
    Column('state', String(2), nullable=False),
    Column('portfolio', String(80), nullable=False),
    Column('region', String(80), nullable=False))
monthly = Table('adt_referring_hospital_monthly', metadata,
    Column('month', Date, primary_key=True),
    Column('hospital', String(160), primary_key=True),
    Column('facility_code', String(12), primary_key=True),
    Column('payer_type', String(40), primary_key=True),
    Column('admissions', Integer, nullable=False),
    Column('readmissions', Integer, nullable=False),
    Column('readmissions_within_30', Integer, nullable=False),
    Index('ix_hospital_monthly_hospital_month', 'hospital', 'month'))
publication = Table('adt_referring_hospital_publication', metadata,
    Column('id', Integer, primary_key=True),
    Column('start_date', Date, nullable=False),
    Column('end_date', Date, nullable=False))
