"""Monthly ADT totals shared by demo and production."""
from sqlalchemy import Column, Date, Integer, MetaData, String, Table
metadata = MetaData()
monthly = Table('adt_activity_monthly', metadata,
    Column('facility_code', String(12), primary_key=True),
    Column('month', Date, primary_key=True),
    Column('opening_census', Integer, nullable=False),
    Column('closing_census', Integer, nullable=False),
    Column('admissions', Integer, nullable=False),
    Column('discharges', Integer, nullable=False),
    Column('net_change', Integer, nullable=False),
)
