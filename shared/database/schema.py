"""Single relational schema imported by the seeder and future API.

Use manage.py stage and edit staged/schema.py while the API is running.
The sandbox publishes the reviewed schema and migrations when update is requested.
Table/column info holds documentation without changing database DDL.
"""
from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer,
    JSON, MetaData, PrimaryKeyConstraint, SmallInteger, String, Table, UniqueConstraint, Uuid,
    false, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()
migration_history = Table('sandbox_schema_migrations', metadata,
    Column('name', String, primary_key=True),
    Column('checksum', String(64), nullable=False),
    Column('applied_at', DateTime(timezone=True), nullable=False, server_default=func.now()),
)
run_history = Table('sandbox_generator_runs', metadata,
    Column('name', String, primary_key=True),
    Column('row_counts', JSON, nullable=False),
    Column('completed_at', DateTime(timezone=True), nullable=False, server_default=func.now()),
)

states = Table('states', metadata,
    Column('state', String(2), primary_key=True),
)
portfolios = Table('portfolios', metadata,
    Column('portfolio_id', Uuid, primary_key=True),
    Column('state', String(2), ForeignKey('states.state'), nullable=False),
    Column('portfolio', String, nullable=False),
    Column('region_count', Integer, nullable=False),
    Column('facility_count', Integer, nullable=False),
    Column('total_beds', Integer, nullable=False),
    UniqueConstraint('state', 'portfolio'),
    CheckConstraint('region_count >= 0 AND facility_count >= 0 AND total_beds >= 0'),
)
regions = Table('regions', metadata,
    Column('region_id', Uuid, primary_key=True),
    Column('portfolio_id', Uuid, ForeignKey('portfolios.portfolio_id'), nullable=False),
    Column('region', String, nullable=False),
    Column('facility_count', Integer, nullable=False),
    Column('total_beds', Integer, nullable=False),
    UniqueConstraint('portfolio_id', 'region'),
    CheckConstraint('facility_count >= 0 AND total_beds >= 0'),
)
facilities = Table('facilities', metadata,
    Column('facility_id', Uuid, primary_key=True),
    Column('region_id', Uuid, ForeignKey('regions.region_id'), nullable=False),
    Column('facility', String, nullable=False),
    Column('beds', Integer, nullable=False),
    UniqueConstraint('region_id', 'facility'),
    CheckConstraint('beds >= 0'),
)
residents = Table('residents', metadata,
    Column('resident_id', Uuid, primary_key=True),
    Column('facility_id', Uuid, ForeignKey('facilities.facility_id'), nullable=False, index=True),
    Column('gender', String(6), nullable=False),
    Column('first_name', String, nullable=False),
    Column('last_name', String, nullable=False),
    CheckConstraint("gender IN ('male', 'female')"),
    UniqueConstraint('first_name', 'last_name', deferrable=True, initially='DEFERRED'),
)
payers = Table('payers', metadata,
    Column('payer_id', Uuid, primary_key=True),
    Column('payer_type', String, nullable=False, index=True),
    Column('payer_name', String, nullable=False),
    Column('is_skilled', Boolean, nullable=False),
    UniqueConstraint('payer_type', 'payer_name'),
)
res_stays = Table('res_stays', metadata,
    Column('stay_id', Uuid, primary_key=True),
    Column('resident_id', Uuid, ForeignKey('residents.resident_id'), nullable=False, index=True),
    Column('facility_id', Uuid, ForeignKey('facilities.facility_id'), nullable=False, index=True),
    Column('admission_number', Integer, nullable=False),
    Column('admission_date', Date, nullable=False, index=True),
    Column('discharge_date', Date, index=True),
    UniqueConstraint('resident_id', 'admission_number'),
    CheckConstraint('admission_number BETWEEN 1 AND 7'),
    CheckConstraint('discharge_date IS NULL OR discharge_date > admission_date'),
)
res_payer_stays = Table('res_payer_stays', metadata,
    Column('payer_stay_id', Uuid, primary_key=True),
    Column('stay_id', Uuid, ForeignKey('res_stays.stay_id'), nullable=False, index=True),
    Column('payer_id', Uuid, ForeignKey('payers.payer_id'), nullable=False, index=True),
    Column('period_number', Integer, nullable=False),
    Column('start_date', Date, nullable=False, index=True),
    Column('end_date', Date, index=True),
    Column('start_reason', String, nullable=False),
    Column('end_reason', String),
    UniqueConstraint('stay_id', 'period_number'),
    CheckConstraint('period_number BETWEEN 1 AND 3'),
    CheckConstraint('end_date IS NULL OR end_date > start_date'),
    CheckConstraint("(period_number = 1 AND start_reason = 'admission') OR "
        "(period_number > 1 AND start_reason = 'payer_change')"),
    CheckConstraint("(end_date IS NULL AND end_reason IS NULL) OR "
        "(end_date IS NOT NULL AND end_reason IS NOT NULL "
        "AND end_reason IN ('payer_change', 'discharge'))"),
    # Payer change reporting reads only the periods that start a change, which is
    # 38% of this table. A partial index keeps the residents-affected count and
    # the logs off a scan of every period ever recorded.
    Index('ix_res_payer_stays_changes', 'start_date', 'stay_id',
        postgresql_where=text('period_number > 1')),
)

admission_logs = Table('admission_logs', metadata,
    # One admission log per saved admission episode.
    Column('stay_id', Uuid, ForeignKey('res_stays.stay_id'), primary_key=True),
    Column('admission_date', Date, nullable=False, index=True),
    Column('payer_id', Uuid, ForeignKey('payers.payer_id'), nullable=False, index=True),
    Column('source_type', String, nullable=False),
    Column('source_name', String, nullable=False),
    Column('is_readmission', Boolean, nullable=False),
    Column('is_30_day_readmission', Boolean, nullable=False),
    CheckConstraint("source_type IN ('Hospital', 'Skilled Nursing', 'Home', "
        "'Rehab Facility', 'Assisted Living', 'Community')"),
    CheckConstraint("length(trim(source_name)) > 0"),
    CheckConstraint('NOT is_30_day_readmission OR is_readmission'),
)

payer_change_logs = Table('payer_change_logs', metadata,
    # One row per payer period that began as a change, flattened alongside the
    # period it moved from. Unlike admission_logs and discharge_logs this carries
    # no new facts -- everything here is implied by two adjacent rows in
    # res_payer_stays -- but reading it back needs a self-join on
    # period_number - 1, which is what made the payer-change reports the slowest
    # in the app. This trades a derived table for that join.
    Column('payer_stay_id', Uuid, ForeignKey('res_payer_stays.payer_stay_id'), primary_key=True),
    Column('stay_id', Uuid, ForeignKey('res_stays.stay_id'), nullable=False, index=True),
    # Carried so residents affected is a count over this table rather than a
    # second join back through res_stays.
    Column('resident_id', Uuid, ForeignKey('residents.resident_id'), nullable=False, index=True),
    Column('facility_id', Uuid, ForeignKey('facilities.facility_id'), nullable=False),
    Column('change_date', Date, nullable=False, index=True),
    Column('previous_payer_id', Uuid, ForeignKey('payers.payer_id'), nullable=False),
    Column('new_payer_id', Uuid, ForeignKey('payers.payer_id'), nullable=False),
    # The date the ended period began, so its length is a subtraction.
    Column('previous_start_date', Date, nullable=False),
    # Null while the new period is still open. Its length is measured against
    # today, so it is deliberately not stored: it would be stale tomorrow.
    Column('new_end_date', Date),
    # Whether the move crossed payer types or only changed plan inside one.
    Column('is_type_change', Boolean, nullable=False),
    CheckConstraint('change_date > previous_start_date'),
    CheckConstraint('new_end_date IS NULL OR new_end_date > change_date'),
    CheckConstraint('previous_payer_id <> new_payer_id'),
    Index('ix_payer_change_logs_facility', 'facility_id', 'change_date'),
)

medicaid_applications = Table('medicaid_applications', metadata,
    Column('stay_id', Uuid, ForeignKey('res_stays.stay_id'), primary_key=True),
    Column('payer_stay_id', Uuid, ForeignKey('res_payer_stays.payer_stay_id'), nullable=False, unique=True),
    Column('application_date', Date, nullable=False, index=True),
    Column('approved_date', Date, index=True),
    Column('approved_payer_id', Uuid, ForeignKey('payers.payer_id')),
    CheckConstraint('(approved_date IS NULL AND approved_payer_id IS NULL) OR '
        '(approved_date IS NOT NULL AND approved_payer_id IS NOT NULL AND approved_date >= application_date)'),
)

discharge_logs = Table('discharge_logs', metadata,
    Column('stay_id', Uuid, ForeignKey('res_stays.stay_id'), primary_key=True),
    Column('discharge_date', Date, nullable=False, index=True),
    Column('payer_id', Uuid, ForeignKey('payers.payer_id'), nullable=False, index=True),
    Column('destination_type', String, nullable=False),
    Column('destination_name', String, nullable=False),
    Column('is_deceased', Boolean, nullable=False),
    # Left against medical advice. A flag beside is_deceased rather than a
    # disposition column: transfers and deaths are already implied by the
    # destination, so this is the only outcome the destination cannot express.
    Column('is_ama', Boolean, nullable=False, server_default=false()),
    Column('los', Integer, nullable=False),
    CheckConstraint("destination_type IN ('Hospital', 'Skilled Nursing', 'Home', "
        "'Rehab Facility', 'Assisted Living', 'Community', 'Funeral Home')"),
    CheckConstraint("length(trim(destination_name)) > 0"),
    CheckConstraint("is_deceased = (destination_type = 'Funeral Home')"),
    # Keeps the three reported outcomes disjoint, so a stacked chart of
    # transfers, deaths and AMA never counts one discharge twice.
    CheckConstraint("NOT (is_ama AND (is_deceased OR destination_type = 'Hospital'))"),
    CheckConstraint('los > 0'),
)

daily_admission_facts = Table('daily_admission_facts', metadata,
    # One row per (date, facility, payer, referral source) that had admissions.
    # Parent location totals are GROUP BY results, never stored copies, so a
    # scope is never double counted with its own children. Days and facilities
    # with no admissions have no rows; absence means zero, not missing.
    Column('summary_date', Date, nullable=False),
    Column('facility_id', Uuid, ForeignKey('facilities.facility_id'), nullable=False),
    Column('payer_id', Uuid, ForeignKey('payers.payer_id'), nullable=False),
    Column('source_type', String, nullable=False),
    Column('source_name', String, nullable=False),
    Column('admissions', Integer, nullable=False),
    Column('readmissions', Integer, nullable=False),
    Column('readmissions_30_day', Integer, nullable=False),
    Column('medicaid_pending_admissions', Integer, nullable=False),
    PrimaryKeyConstraint('summary_date', 'facility_id', 'payer_id', 'source_type', 'source_name'),
    CheckConstraint("source_type IN ('Hospital', 'Skilled Nursing', 'Home', "
        "'Rehab Facility', 'Assisted Living', 'Community')"),
    CheckConstraint("length(trim(source_name)) > 0"),
    CheckConstraint('admissions > 0'),
    CheckConstraint('readmissions BETWEEN 0 AND admissions'),
    CheckConstraint('readmissions_30_day BETWEEN 0 AND readmissions'),
    CheckConstraint('medicaid_pending_admissions BETWEEN 0 AND admissions'),
    Index('ix_daily_admission_facts_facility', 'facility_id', 'summary_date'),
)

daily_discharge_facts = Table('daily_discharge_facts', metadata,
    # One row per (date, facility, payer, destination) that had discharges. Same
    # rules as daily_admission_facts: parent scopes are GROUP BY results rather
    # than stored rows, and a day with no discharges has no rows.
    Column('summary_date', Date, nullable=False),
    Column('facility_id', Uuid, ForeignKey('facilities.facility_id'), nullable=False),
    Column('payer_id', Uuid, ForeignKey('payers.payer_id'), nullable=False),
    Column('destination_type', String, nullable=False),
    Column('destination_name', String, nullable=False),
    Column('discharges', Integer, nullable=False),
    # Transfers and deaths are read back from destination_type, so only AMA needs
    # its own measure. Every column here is additive across any set of rows.
    Column('ama_discharges', Integer, nullable=False),
    # Length of stay is stored as a sum beside its count, never as an average:
    # averaging stored averages is wrong at every level above facility.
    Column('length_of_stay_days', Integer, nullable=False),
    PrimaryKeyConstraint('summary_date', 'facility_id', 'payer_id',
        'destination_type', 'destination_name'),
    CheckConstraint("destination_type IN ('Hospital', 'Skilled Nursing', 'Home', "
        "'Rehab Facility', 'Assisted Living', 'Community', 'Funeral Home')"),
    CheckConstraint("length(trim(destination_name)) > 0"),
    CheckConstraint('discharges > 0'),
    CheckConstraint('ama_discharges BETWEEN 0 AND discharges'),
    CheckConstraint('length_of_stay_days >= discharges'),
    Index('ix_daily_discharge_facts_facility', 'facility_id', 'summary_date'),
)

daily_payer_change_facts = Table('daily_payer_change_facts', metadata,
    # One row per (date, facility, payer type moved from, payer type moved to).
    # The grain is payer TYPE, not payer id: the reports group by type, and the id
    # grain measured at 99.9% of the source rows, which is not a summary at all.
    # Individual plan names stay in res_payer_stays for the logs to read.
    Column('summary_date', Date, nullable=False),
    Column('facility_id', Uuid, ForeignKey('facilities.facility_id'), nullable=False),
    Column('previous_payer_type', String, nullable=False),
    Column('new_payer_type', String, nullable=False),
    Column('changes', Integer, nullable=False),
    PrimaryKeyConstraint('summary_date', 'facility_id', 'previous_payer_type', 'new_payer_type'),
    CheckConstraint('changes > 0'),
    # Residents affected is a distinct count and cannot be stored here: the same
    # resident can change payer on two days, so no per-day row can be summed into
    # one. The report counts it directly from res_payer_stays instead.
    Index('ix_daily_payer_change_facts_facility', 'facility_id', 'summary_date'),
)

daily_payer_census_facts = Table('daily_payer_census_facts', metadata,
    # adt_daily_census one level down: the same opening/flow/closing identity, but
    # split by payer type. Net change by payer cannot be derived from the facility
    # census, because a payer change moves a resident between payer types without
    # touching the facility total.
    #
    # Deliberately dense -- a row for every day a facility/payer pair exists, not
    # only days with movement. A sparse table with a running total measured three
    # times smaller but needed a LATERAL lookup per pair at each period boundary,
    # which ran 546ms against 73ms for the dense form.
    Column('summary_date', Date, nullable=False),
    Column('facility_id', Uuid, ForeignKey('facilities.facility_id'), nullable=False),
    Column('payer_type', String, nullable=False),
    # Census is bounded by licensed beds and movements by daily volume, so these
    # never approach a smallint. Six narrower columns over millions of rows is
    # worth more than the uniformity of Integer here.
    Column('opening_census', SmallInteger, nullable=False),
    Column('admissions', SmallInteger, nullable=False),
    Column('discharges', SmallInteger, nullable=False),
    # Moves between payer types within the same stay. A plan change inside one
    # payer type is excluded: it is not a move into or out of that type.
    Column('changes_in', SmallInteger, nullable=False),
    Column('changes_out', SmallInteger, nullable=False),
    Column('closing_census', SmallInteger, nullable=False),
    PrimaryKeyConstraint('summary_date', 'facility_id', 'payer_type'),
    CheckConstraint('closing_census = opening_census + admissions + changes_in '
        '- discharges - changes_out'),
    CheckConstraint('opening_census >= 0 AND closing_census >= 0 AND admissions >= 0 '
        'AND discharges >= 0 AND changes_in >= 0 AND changes_out >= 0'),
    Index('ix_daily_payer_census_facts_facility', 'facility_id', 'summary_date'),
)

monthly_payer_census_facts = Table('monthly_payer_census_facts', metadata,
    # A calendar-month rollup of daily_payer_census_facts, for the monthly ADT
    # trending report. Rolling the daily table up on every request measured
    # 362-423ms; at 30 times fewer rows this answers the same questions from a
    # table small enough to stay cached.
    #
    # Flows are summed. Census is not: opening comes from the month's first day
    # and closing from its last, because census is a level rather than a flow.
    Column('month_start', Date, nullable=False),
    Column('facility_id', Uuid, ForeignKey('facilities.facility_id'), nullable=False),
    Column('payer_type', String, nullable=False),
    Column('opening_census', SmallInteger, nullable=False),
    Column('admissions', SmallInteger, nullable=False),
    Column('discharges', SmallInteger, nullable=False),
    Column('changes_in', SmallInteger, nullable=False),
    Column('changes_out', SmallInteger, nullable=False),
    Column('closing_census', SmallInteger, nullable=False),
    PrimaryKeyConstraint('month_start', 'facility_id', 'payer_type'),
    CheckConstraint('closing_census = opening_census + admissions + changes_in '
        '- discharges - changes_out'),
    CheckConstraint('opening_census >= 0 AND closing_census >= 0 AND admissions >= 0 '
        'AND discharges >= 0 AND changes_in >= 0 AND changes_out >= 0'),
    CheckConstraint("date_trunc('month', month_start) = month_start"),
    Index('ix_monthly_payer_census_facts_facility', 'facility_id', 'month_start'),
)

daily_runs = Table('sandbox_daily_runs', metadata,
    Column('generator', String, primary_key=True),
    Column('simulation_date', Date, primary_key=True),
    Column('row_counts', JSON, nullable=False),
    Column('completed_at', DateTime(timezone=True), nullable=False, server_default=func.now()),
)
adt_resident_state = Table('sandbox_adt_residents', metadata,
    Column('resident_id', Uuid, ForeignKey('residents.resident_id'), primary_key=True),
    Column('admission_limit', Integer, nullable=False),
    Column('admissions', Integer, nullable=False),
    Column('last_discharge', Date),
    Column('eligible_after', Date),
    Column('is_deceased', Boolean, nullable=False),
    Column('skilled_used', Integer, nullable=False),
    CheckConstraint('admission_limit BETWEEN 1 AND 7 AND admissions BETWEEN 1 AND admission_limit'),
    CheckConstraint('skilled_used BETWEEN 0 AND 100'),
)
adt_active_stays = Table('sandbox_adt_active_stays', metadata,
    Column('stay_id', Uuid, ForeignKey('res_stays.stay_id'), primary_key=True),
    # Future intentions are kept here, never as completed clinical events.
    Column('planned_discharge', Date, nullable=False),
    Column('payer_plan', JSONB, nullable=False),
    Column('skilled_days', Integer, nullable=False),
    Column('medicaid_approval', JSONB),
)
adt_daily_census = Table('adt_daily_census', metadata,
    Column('facility_id', Uuid, ForeignKey('facilities.facility_id'), primary_key=True),
    Column('census_date', Date, primary_key=True),
    Column('beds', Integer, nullable=False),
    Column('opening_census', Integer, nullable=False),
    Column('admissions', Integer, nullable=False),
    Column('discharges', Integer, nullable=False),
    Column('closing_census', Integer, nullable=False),
    CheckConstraint('closing_census = opening_census + admissions - discharges'),
    CheckConstraint('beds >= 0 AND opening_census >= 0 AND admissions >= 0 AND discharges >= 0'),
    CheckConstraint('closing_census BETWEEN 0 AND beds'),
)


migration_checksums = Table('database_migration_checksums', metadata,
    Column('revision', String(64), primary_key=True),
    Column('checksum', String(64), nullable=False),
    Column('applied_at', DateTime(timezone=True), nullable=False, server_default=func.now()),
)
backfill_runs = Table('database_backfill_runs', metadata,
    Column('name', String, primary_key=True),
    Column('checksum', String(64), nullable=False),
    Column('status', String, nullable=False),
    Column('checkpoint', JSONB, nullable=False),
    Column('processed', Integer, nullable=False, server_default='0'),
    Column('changed', Integer, nullable=False, server_default='0'),
    Column('updated_at', DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("status IN ('pending', 'running', 'deferred', 'complete')"),
    CheckConstraint('processed >= 0 AND changed >= 0'),
)

# Documentation stays beside the schema. `info` does not change database DDL.
_descriptions = {
    'states': 'Top-level state codes; counts are derived from child records.',
    'portfolios': 'Portfolios within states. Stored reference counts describe the source facility catalog.',
    'regions': 'Regions within portfolios; facility groups used by hospital referral weighting.',
    'facilities': 'Facilities and their licensed/demo bed capacity.',
    'residents': 'Saved resident identities associated with a facility. Stays reference these saved IDs.',
    'payers': 'Payer catalog. Skilled classification applies to Medicare categories and VA.',
    'res_stays': 'Admission-to-discharge episodes. A null discharge date means currently admitted.',
    'res_payer_stays': 'Payer periods inside an admission episode. The active period has no end date.',
    'admission_logs': 'One actual admission event per episode, including referring source and readmission flags.',
    'medicaid_applications': 'Admissions that started pending Medicaid. Preserves application/approval metrics after payer records are retroactively corrected.',
    'discharge_logs': 'One actual discharge event per closed episode. LOS measures the final payer period.',
    'payer_change_logs': 'One row per payer change, flattened with the period it moved from. Derived from res_payer_stays to spare every report the self-join on period_number - 1.',
    'daily_admission_facts': 'Additive daily admission measures at facility/payer/source grain. Reports group these rows; parent scopes are not stored.',
    'daily_discharge_facts': 'Additive daily discharge measures at facility/payer/destination/disposition grain. Length of stay is a sum beside its count so any grouping divides correctly.',
    'daily_payer_change_facts': 'Additive daily payer-change counts at facility/from-type/to-type grain. Residents affected is a distinct count and is read from res_payer_stays instead.',
    'daily_payer_census_facts': 'Daily census and movement by payer type: opening + admissions + changes in - discharges - changes out = closing. Sums back to adt_daily_census.',
    'monthly_payer_census_facts': 'Calendar-month rollup of daily_payer_census_facts for monthly trending. Flows are summed; census is taken from the first and last day of each month.',
    'adt_daily_census': 'Daily facility census: opening + admissions - discharges = closing.',
    'sandbox_schema_migrations': 'Preserved legacy SQL migration history; new migrations use Alembic.',
    'sandbox_generator_runs': 'Reference-generator completion records used to retain existing data.',
    'sandbox_daily_runs': 'Committed generator/day checkpoints; independent of schema and backfill versions.',
    'sandbox_adt_residents': 'Internal simulation state for readmissions, eligibility and cumulative skilled days.',
    'sandbox_adt_active_stays': 'Internal future simulation plans. These are not completed clinical events.',
    'database_migration_checksums': 'Checksums of applied Alembic revisions and their frozen artifacts.',
    'database_backfill_runs': 'Immutable job identity, durable batch checkpoint and cumulative progress per database.',
}
for _name, _description in _descriptions.items():
    metadata.tables[_name].info['description'] = _description

discharge_logs.c.los.info['description'] = 'Discharge date minus the final payer period start date, in days; not admission LOS.'
discharge_logs.c.is_ama.info['description'] = 'Left against medical advice. Deaths and acute transfers are already implied by destination_type, so neither is eligible and the three outcomes stay disjoint.'
daily_discharge_facts.c.ama_discharges.info['description'] = 'Discharges against medical advice among the grouped rows. Transfers and deaths need no measure: they are destination_type Hospital and Funeral Home.'
daily_discharge_facts.c.length_of_stay_days.info['description'] = 'Summed length of stay for the grouped discharges. Divide by discharges for an average; never store the average.'
daily_payer_change_facts.c.changes.info['description'] = 'Payer periods that began as a change from the previous period, at payer-type grain. A change within one payer type (plan only) has previous_payer_type = new_payer_type.'
daily_payer_change_facts.c.previous_payer_type.info['description'] = 'Payer type of the period that ended on this date.'
daily_payer_change_facts.c.new_payer_type.info['description'] = 'Payer type of the period that began on this date.'
admission_logs.c.is_readmission.info['description'] = 'Resident has a previous admission episode.'
admission_logs.c.is_30_day_readmission.info['description'] = 'Return within 30 days of the previous discharge; also a readmission.'
daily_admission_facts.c.source_name.info['description'] = 'Referring source name; referring-hospital metrics count distinct names where source_type is Hospital.'
daily_admission_facts.c.medicaid_pending_admissions.info['description'] = 'Admissions that began pending Medicaid; retained after retroactive payer approval.'
res_payer_stays.c.end_date.info['description'] = 'Exclusive period end; null until payer change or discharge actually occurs.'
medicaid_applications.c.application_date.info['description'] = 'Admission date when Medicaid coverage was pending; a row permanently identifies a pending-at-admission case.'
medicaid_applications.c.approved_date.info['description'] = 'Actual approval date; null while unresolved. Approved coverage is retroactive to application_date.'
adt_active_stays.c.medicaid_approval.info['description'] = 'Private planned approval date and payer ID; not a completed approval event.'
backfill_runs.c.checkpoint.info['description'] = 'Job-owned JSON cursor/watermark committed atomically with each batch.'
