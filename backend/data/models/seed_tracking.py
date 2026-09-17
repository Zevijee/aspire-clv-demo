from sqlalchemy import Column, Date, DateTime, Integer, JSON, MetaData, String, Table, func

metadata = MetaData()
datasets = Table(
    "seed_datasets",
    metadata,
    Column("name", String(80), primary_key=True),
    Column("version", String(80), nullable=False),
    Column("input_fingerprint", String(64), nullable=False),
)
coverage = Table(
    "seed_daily_coverage",
    metadata,
    Column("dataset", String(80), primary_key=True),
    Column("seed_date", Date, primary_key=True),
    Column("row_count", Integer, nullable=False),
)


runs = Table('seed_runs', metadata,
    Column('run_id', String(36), primary_key=True),
    Column('status', String(20), nullable=False),
    Column('operation', String(20), nullable=False),
    Column('plan', JSON, nullable=False),
    Column('started_at', DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column('finished_at', DateTime(timezone=True)),
    Column('error_type', String(120)),
)
