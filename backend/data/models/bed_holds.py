"""Daily reserved-bed snapshots supplied by operational data or demo generation."""
from sqlalchemy import Column, Date, ForeignKey, Integer, MetaData, String, Table, CheckConstraint
metadata = MetaData()
Table("facilities", metadata, Column("facility_code", String(12), primary_key=True))
bed_holds = Table("census_bed_holds_daily", metadata,
    Column("facility_code", String(12), ForeignKey("facilities.facility_code"), primary_key=True),
    Column("census_date", Date, primary_key=True),
    Column("bed_holds", Integer, nullable=False),
    CheckConstraint("bed_holds >= 0", name="bed_holds_nonnegative"))
