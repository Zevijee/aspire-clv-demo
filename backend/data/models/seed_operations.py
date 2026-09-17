"""Demo-operation state. The schema also exists, unused, in production."""
from sqlalchemy import Column, Date, DateTime, Integer, JSON, MetaData, String, Table, func

metadata = MetaData()
target_identity = Table('seed_target_identity', metadata,
    Column('id', Integer, primary_key=True),
    Column('environment', String(20), nullable=False),
    Column('database_name', String(128), nullable=False),
    Column('instance_id', String(128), nullable=False),
)
batches = Table('seed_run_batches', metadata,
    Column('run_id', String(36), primary_key=True),
    Column('batch_key', String(160), primary_key=True),
    Column('status', String(20), nullable=False),
    Column('details', JSON, nullable=False),
    Column('updated_at', DateTime(timezone=True), server_default=func.now(), nullable=False),
)
boundaries = Table('seed_boundaries', metadata,
    Column('dataset', String(80), primary_key=True),
    Column('scope_key', String(128), primary_key=True),
    Column('through_date', Date, primary_key=True),
    Column('version', String(80), nullable=False),
    Column('scenario_key', String(120), nullable=False),
    Column('payload', JSON, nullable=False),
)

# Durable scenario plans are separate from small run/progress metadata. They are
# discarded after movement persistence; failed stages retain them for exact replay.
source_plans = Table('seed_source_plans', metadata,
    Column('run_id', String(36), primary_key=True),
    Column('facility_code', String(12), primary_key=True),
    Column('payload', JSON, nullable=False),
)
