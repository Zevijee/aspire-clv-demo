"""Single relational schema imported by the seeder and future API.

Use manage.py stage and edit staged/schema.py while the API is running.
The sandbox publishes the reviewed schema and migrations when update is requested.
Table/column info holds documentation without changing database DDL.
"""
from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer,
    JSON, MetaData, Numeric, PrimaryKeyConstraint, SmallInteger, String, Table, UniqueConstraint, Uuid,
    false, func, text,
)
from sqlalchemy.dialects.postgresql import DATERANGE, JSONB

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
# The rules each generator's saved data was built with: a fingerprint of its
# code. update compares them with the code it is running and rebuilds any
# generator whose rules changed, so a deploy that changes generation needs no
# manual --regenerate. Dates alone cannot tell: a finished day looks the same
# whichever code built it.
rule_history = Table('sandbox_generator_rules', metadata,
    Column('name', String, primary_key=True),
    Column('fingerprint', String(64), nullable=False),
    Column('recorded_at', DateTime(timezone=True), nullable=False, server_default=func.now()),
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
referring_hospitals = Table('referring_hospitals', metadata,
    # The hospitals that refer residents in, one row per hospital name. Names are
    # globally unique in hospitals.json, so the name is the key the admission
    # rows already carry and no surrogate id is needed.
    #
    # A hospital refers into exactly one region -- verified: zero of 384 hospitals
    # send admissions to facilities in more than one region -- so region_id is a
    # fact about the hospital rather than a summary of where it happens to send.
    # State and portfolio are joins away through regions and are deliberately not
    # copied here, for the same reason parent location scopes are never stored.
    Column('hospital', String, primary_key=True),
    Column('region_id', Uuid, ForeignKey('regions.region_id'), nullable=False, index=True),
    CheckConstraint('length(trim(hospital)) > 0'),
)

facility_payer_rates = Table('facility_payer_rates', metadata,
    # What each payer plan pays a facility per resident per day. Reference data,
    # like payers: generated from rules by `manage.py payer_rates` in seconds, and
    # never read back by the simulation, so changing a rate needs no reseed.
    #
    # Keyed by plan rather than payer type because that is where a real contract
    # rate lives -- two Medicaid managed care plans in one state pay differently --
    # and the report's average rate per payer type is then a true resident-weighted
    # average: every resident's rate summed and divided once by the residents.
    Column('facility_id', Uuid, ForeignKey('facilities.facility_id'), nullable=False),
    Column('payer_id', Uuid, ForeignKey('payers.payer_id'), nullable=False),
    Column('daily_rate', Numeric(8, 2), nullable=False),
    # How the contract pays: 'pdpm' from the resident's PDPM code and its CMIs,
    # or 'per_diem', a daily rate the code does not change. A property of the
    # contract, not the plan -- one Medicare Advantage plan can pay PDPM at one
    # facility and a flat rate at the next -- so reports group Medicare
    # Advantage by this as Managed Medicare PDPM and Managed Medicare per diem.
    # Original Medicare is always 'pdpm'.
    Column('payment_method', String, nullable=False),
    PrimaryKeyConstraint('facility_id', 'payer_id'),
    CheckConstraint('daily_rate > 0'),
    CheckConstraint("payment_method IN ('pdpm', 'per_diem')"),
)

users = Table('users', metadata,
    # Who may read this demo. There is exactly one row today, seeded by
    # `manage.py admin_user`, but a table rather than a setting because a
    # password that lives in configuration ends up in a repository sooner or
    # later, and because adding a second reader should not need a deploy.
    #
    # The password itself is never stored. `password_hash` holds a bcrypt digest,
    # which carries its own salt and cost factor, so rotating the cost later
    # needs no schema change.
    Column('user_id', Uuid, primary_key=True),
    Column('username', String, nullable=False),
    Column('password_hash', String, nullable=False),
    Column('created_at', DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint('length(trim(username)) > 0'),
    CheckConstraint("password_hash LIKE '$2%'"),
)
# Declared after the table so it references the real column. Case-insensitive,
# so Admin and admin cannot become two accounts.
Index('ix_users_username', func.lower(users.c.username), unique=True)

refresh_tokens = Table('refresh_tokens', metadata,
    # Long-lived sign-in, so a reader is not sent back to the password form every
    # time the short access cookie expires. The token itself lives only in the
    # browser's HttpOnly cookie; this table holds its SHA-256, so a copy of the
    # database cannot be replayed as a login. A random 256-bit token needs no
    # salt or slow hash -- there is nothing to guess.
    #
    # Every use replaces the token with a new one in the same family. Presenting a
    # token that has already been replaced means two parties hold it, so the whole
    # family is revoked and both must sign in again.
    Column('token_hash', String(64), primary_key=True),
    # One family per sign-in. Sign-out and reuse detection revoke by family.
    Column('family_id', Uuid, nullable=False, index=True),
    # Cascade, so removing a user cannot be blocked by their old sessions.
    Column('user_id', Uuid, ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False),
    Column('issued_at', DateTime(timezone=True), nullable=False),
    Column('expires_at', DateTime(timezone=True), nullable=False),
    # Set when rotated. A second use shortly after is two tabs refreshing at once;
    # a later one is a stolen token.
    Column('replaced_at', DateTime(timezone=True)),
    Column('revoked_at', DateTime(timezone=True)),
    CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'"),
    CheckConstraint('expires_at > issued_at'),
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

census_logs = Table('census_logs', metadata,
    # Who was in a bed, and at what care level and base daily rate, for every day
    # of history -- one row per stretch in a bed at one payer and one care level,
    # not one row per resident per day. Measured: 36.9M rows and ~5.1 GB as a
    # daily table, against under a million here, with the same answers. "In a bed
    # on d" is in_bed @> d; "during a range" is in_bed && range; resident-days
    # are the overlap length, summed.
    #
    # A new row starts when the payer period changes (a payer change, or
    # admission and discharge) or when the care level does. Care level is
    # reassessed every 92 days from admission, as the MDS quarterly assessment
    # is, so a long-stay Medicaid resident's rate can step up mid-stay with no
    # payer change.
    #
    # Skilled payers' day-by-day PDPM rate is deliberately not split in here: it
    # lives in pdpm_rate_logs, keyed by the same payer period, so a stay is not
    # chopped into a new row every week. Rows stop at the latest simulated day.
    #
    # Derived entirely from res_payer_stays and facility_payer_rates, and rebuilt
    # whole on each update, because payer periods are edited after the fact: a
    # discharge closes an open period and a Medicaid approval rewrites the payer.
    Column('payer_stay_id', Uuid, nullable=False),
    # Position within the payer period, from 1, in date order.
    Column('segment', SmallInteger, nullable=False),
    Column('stay_id', Uuid, nullable=False),
    Column('resident_id', Uuid, nullable=False),
    Column('facility_id', Uuid, ForeignKey('facilities.facility_id'), nullable=False),
    Column('payer_id', Uuid, ForeignKey('payers.payer_id'), nullable=False),
    Column('admission_date', Date, nullable=False),
    Column('is_readmission', Boolean, nullable=False),
    # Acuity from the latest assessment. Multiplies the facility and plan rate.
    Column('care_level', String, nullable=False),
    # Half-open [first day in a bed, first day gone). Open-ended while the
    # resident is still here.
    Column('in_bed', DATERANGE, nullable=False),
    # Facility and plan rate times the care level multiplier. For a skilled
    # payer this is the rate before PDPM; the day's rate is in pdpm_rate_logs.
    Column('daily_rate', Numeric(8, 2), nullable=False),
    PrimaryKeyConstraint('payer_stay_id', 'segment'),
    CheckConstraint('NOT isempty(in_bed) AND NOT lower_inf(in_bed)'),
    CheckConstraint('daily_rate > 0'),
    CheckConstraint("care_level IN ('Low', 'Moderate', 'High', 'Complex')"),
    Index('ix_census_logs_in_bed', 'in_bed', postgresql_using='gist'),
)

pdpm_rate_logs = Table('pdpm_rate_logs', metadata,
    # The day-by-day rate of every skilled payer period, under Medicare's PDPM
    # variable per diem: days 1-3 pay more (non-therapy ancillaries at 300%), and
    # from day 21 the therapy share falls 2% every 7 days. One row per rate
    # period -- days 1-3, 4-20, then each week -- so the rate on any day is the
    # row whose in_effect contains it.
    #
    # Kept apart from census_logs, which it refines: a skilled resident's census
    # row stays whole while the rate beneath it steps. For a skilled resident on
    # day d the rate is this table's daily_rate; for everyone else it is the
    # census row's. Rebuilt with census_logs, from it.
    Column('payer_stay_id', Uuid, nullable=False),
    Column('step', SmallInteger, nullable=False),
    # Day of skilled coverage the step starts on, counted from the payer period.
    Column('skilled_day', SmallInteger, nullable=False),
    Column('in_effect', DATERANGE, nullable=False),
    # Multiplies the census row's rate for the step's first day.
    Column('pdpm_factor', Numeric(5, 4), nullable=False),
    Column('daily_rate', Numeric(8, 2), nullable=False),
    PrimaryKeyConstraint('payer_stay_id', 'step'),
    CheckConstraint('NOT isempty(in_effect) AND NOT lower_inf(in_effect)'),
    CheckConstraint('skilled_day >= 1'),
    CheckConstraint('pdpm_factor > 0 AND daily_rate > 0'),
    Index('ix_pdpm_rate_logs_in_effect', 'in_effect', postgresql_using='gist'),
)

pdpm_assessments = Table('pdpm_assessments', metadata,
    # The PDPM classification of every Medicare payer period -- Original
    # Medicare and Medicare Advantage -- as its 5-day assessment would set it:
    # one row per period, applying from its first day.
    #
    # pdpm_code is the four letters of the HIPPS code, one case-mix group per
    # component: PT/OT (A-P), SLP (A-L), nursing (A-Y, ES3 down to PA1) and
    # non-therapy ancillaries (A-F, 12+ comorbidity points down to 0). Each letter
    # maps to its component's CMS case-mix index, so the code is all a report needs.
    #
    # Invented like care level: a function of the payer period id, with nursing
    # drawn from the band the resident's care level implies. Rebuilt with
    # census_logs, from it.
    #
    # The SLP letter counts how many of acute neuro, SLP comorbidity and
    # cognitive impairment are present (0-3) and whether neither, one or both of
    # a mechanically altered diet and a swallowing disorder are, but not which.
    # The five flags record which, and the generator writes the letter from
    # them, so the two always agree: SLP letter = conditions * 3 + (MAD + SD).
    # Acute neuro is only ever set inside the PT/OT acute neuro / non-ortho
    # surgery category, the primary diagnosis it stands for.
    Column('payer_stay_id', Uuid, primary_key=True),
    Column('pdpm_code', String(4), nullable=False),
    Column('acute_neuro', Boolean, nullable=False, server_default=false()),
    Column('slp_comorbidity', Boolean, nullable=False, server_default=false()),
    Column('cognitive_impairment', Boolean, nullable=False, server_default=false()),
    Column('mechanically_altered_diet', Boolean, nullable=False, server_default=false()),
    Column('swallowing_disorder', Boolean, nullable=False, server_default=false()),
    # The nursing function score (0-16) behind the nursing letter, inside the
    # range CMS gives that group: some groups span more than one report band
    # (Extensive Services 0-14, Behavioral 11-16), so the letter alone cannot
    # place them.
    Column('nursing_function_score', SmallInteger, nullable=False, server_default='0'),
    # Whether the resident shows signs of depression. For the special care and
    # clinically complex nursing groups the letter already says so -- the "2"
    # groups are with depression -- and the flag follows it; for the other
    # groups, where depression does not change the group, it is drawn.
    Column('depression', Boolean, nullable=False, server_default=false()),
    # The 5-day assessment's reference date (ARD): day 1-8 of the payer period.
    # Indexed: the PDPM Worksheet filters stays by ARD range.
    Column('ard', Date, nullable=False, index=True),
    # The day this code became available: the ARD plus the time to complete
    # and code the assessment. Before then the resident is in a bed on Medicare
    # with no PDPM score yet, and reports count them as not coded.
    Column('coded_date', Date, nullable=False),
    CheckConstraint("pdpm_code ~ '^[A-P][A-L][A-Y][A-F]$'"),
    CheckConstraint('nursing_function_score BETWEEN 0 AND 16', name='ck_pdpm_assessments_nursing_function_score'),
)

medicaid_assessments = Table('medicaid_assessments', metadata,
    # The case-mix code of every Texas Medicaid resident, for Current Medicaid.
    # Texas pays Medicaid on the PDPM nursing and NTA components alone, so the
    # code is two letters: nursing (A-Y) and NTA (A-F), with the same meanings
    # as letters three and four of a Medicare PDPM code. Florida and
    # Pennsylvania use other systems and have no rows here.
    #
    # One row per census_logs segment of a Medicaid payer period: a segment is a
    # stretch at one care level, and a change of care level is a reassessment
    # with a new code. The nursing letter is drawn from the segment's care
    # level, as Medicare's is; the NTA band from the payer period, since
    # comorbidities persist. Rates are unchanged: Medicaid still pays the
    # census_logs rate. Rebuilt with census_logs, from it.
    Column('payer_stay_id', Uuid, nullable=False),
    Column('segment', SmallInteger, nullable=False),
    Column('code', String(2), nullable=False),
    # The nursing function score (0-16) behind the nursing letter, as on
    # pdpm_assessments: the letter alone cannot place every report band.
    Column('nursing_function_score', SmallInteger, nullable=False),
    # The assessment reference date: within a week of the payer period's start
    # for its first segment, the day the care level changed for the others.
    Column('ard', Date, nullable=False),
    # The day the code became available, a few days after the ARD. Before it
    # the resident has no code and reports count them as not coded.
    Column('coded_date', Date, nullable=False),
    PrimaryKeyConstraint('payer_stay_id', 'segment'),
    CheckConstraint("code ~ '^[A-Y][A-F]$'"),
    CheckConstraint('nursing_function_score BETWEEN 0 AND 16', name='ck_medicaid_assessments_nursing_function_score'),
    CheckConstraint('coded_date >= ard'),
)

pdpm_worksheet_entries = Table('pdpm_worksheet_entries', metadata,
    # What people enter on the PDPM Worksheet, one row per entry, never updated
    # or deleted: the log everyone sees. A cell shows its latest set entry;
    # NTA keeps a list, built from its add and remove entries in order; a reply
    # answers one earlier entry. Unlike every other table here this is written
    # by the API, by signed-in users, not generated -- so a seed --reset-history,
    # which drops every table, also drops what people have entered.
    #
    # One worksheet per Medicare payer period, the period its assessment is for.
    Column('entry_id', Uuid, primary_key=True),
    Column('payer_stay_id', Uuid, nullable=False),
    # The worksheet cell: pt_ot.primary_diagnosis, slp.comorbidity, nta,
    # projected_hipps and so on. The API owns the list and validates values.
    Column('field', String(40), nullable=False),
    # set replaces the cell's value; add and remove change the NTA list;
    # reply answers reply_to, with a note and no value.
    Column('action', String(10), nullable=False),
    Column('value', String(100)),
    Column('note', String),
    Column('reply_to', Uuid, ForeignKey('pdpm_worksheet_entries.entry_id')),
    # The signed-in username, as it was when they wrote it.
    Column('author', String, nullable=False),
    Column('created_at', DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("action IN ('set', 'add', 'remove', 'reply')", name='ck_pdpm_worksheet_entries_action'),
    CheckConstraint("(action = 'reply') = (reply_to IS NOT NULL)", name='ck_pdpm_worksheet_entries_reply'),
    CheckConstraint("action <> 'reply' OR length(trim(note)) > 0", name='ck_pdpm_worksheet_entries_reply_note'),
    Index('ix_pdpm_worksheet_entries_cell', 'payer_stay_id', 'field', 'created_at'),
)

resident_summaries = Table('resident_summaries', metadata,
    # One row per resident ever admitted, totalled across every stay, for the
    # Residents report. Computing these live from res_stays and res_payer_stays
    # measured 2.1s per request -- too slow to sort, filter and page on -- so they
    # are rolled up once per update instead, from saved stays, in seconds.
    #
    # A resident only ever stays at one facility (verified: no exceptions), so
    # facility_id is a fact about the resident rather than a summary of stays.
    # Open stays count their days through the latest simulated day.
    #
    # Names and places are copied in, deliberately. Joining them onto 187,000
    # rows before every sort cost 0.5-1.9s a page; from this table alone it
    # measured 30-150ms. They cannot drift: the table is rebuilt every update.
    Column('resident_id', Uuid, ForeignKey('residents.resident_id'), primary_key=True),
    Column('facility_id', Uuid, ForeignKey('facilities.facility_id'), nullable=False),
    Column('resident_name', String, nullable=False),
    Column('facility_name', String, nullable=False),
    Column('state', String(2), nullable=False),
    Column('portfolio', String, nullable=False),
    Column('region', String, nullable=False),
    Column('stays', SmallInteger, nullable=False),
    # Every stay begins with an admission, so this equals stays; kept because
    # the report shows admissions and discharges side by side.
    Column('admissions', SmallInteger, nullable=False),
    Column('discharges', SmallInteger, nullable=False),
    Column('is_current', Boolean, nullable=False),
    Column('days_in_facility', Integer, nullable=False),
    # Distinct payer plans across every stay, and distinct payer types.
    Column('payers', SmallInteger, nullable=False),
    Column('payer_types', SmallInteger, nullable=False),
    Column('first_admission', Date, nullable=False),
    Column('last_admission', Date, nullable=False),
    Column('last_discharge', Date),
    # The latest simulated day these totals run through.
    Column('as_of', Date, nullable=False),
    CheckConstraint('stays >= 1 AND admissions = stays AND discharges BETWEEN 0 AND stays'),
    CheckConstraint('is_current = (discharges < stays)'),
    CheckConstraint('days_in_facility >= 0 AND payers >= 1 AND payer_types BETWEEN 1 AND payers'),
    Index('ix_resident_summaries_facility', 'facility_id'),
)

facility_beds = Table('facility_beds', metadata,
    # Every licensed bed, laid out in wings and rooms, for the Bed Board. Reference
    # data like facility_payer_rates: generated from each facility's bed count by
    # `manage.py facility_beds`, deterministic, and rebuilt in seconds. The count
    # of rows per facility always equals facilities.beds.
    Column('bed_id', Uuid, primary_key=True),
    Column('facility_id', Uuid, ForeignKey('facilities.facility_id'), nullable=False),
    # Wing letter; rooms in wing n are numbered from n * 100 + 1.
    Column('wing', String(1), nullable=False),
    Column('room', String, nullable=False),
    # A for the first bed in a room, B for the second. A private room has only A.
    Column('bed', String(1), nullable=False),
    UniqueConstraint('facility_id', 'room', 'bed'),
    CheckConstraint("bed IN ('A', 'B')"),
    Index('ix_facility_beds_facility', 'facility_id'),
)

bed_assignments = Table('bed_assignments', metadata,
    # Which bed each stay occupied, and when: one row per stretch in one bed, so a
    # stay normally has one row. Invented here, like care levels -- nothing in the
    # simulation reads it back -- and rebuilt whole from res_stays on every update,
    # replaying each facility's admissions and discharges in date order.
    #
    # Semi-private rooms are kept to one gender when any bed allows it; measured,
    # 0.5% of occupied rooms end up mixed. Census has never exceeded licensed
    # beds (measured), but if it did the extra resident would wait with a null
    # bed_id and move into the first bed that frees, starting a new row.
    Column('stay_id', Uuid, nullable=False),
    # Position within the stay, from 1, in date order.
    Column('move', SmallInteger, nullable=False),
    Column('resident_id', Uuid, nullable=False),
    Column('facility_id', Uuid, ForeignKey('facilities.facility_id'), nullable=False),
    # Null while the facility has no free bed.
    Column('bed_id', Uuid, ForeignKey('facility_beds.bed_id')),
    # Half-open, open-ended while the resident is still here, like census_logs.
    Column('in_bed', DATERANGE, nullable=False),
    PrimaryKeyConstraint('stay_id', 'move'),
    CheckConstraint('NOT isempty(in_bed) AND NOT lower_inf(in_bed)'),
    # A facility has a few thousand rows across all of history, so the board
    # filters them by date after this index rather than needing btree_gist.
    Index('ix_bed_assignments_facility', 'facility_id'),
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

# The clinical reasons a resident is sent to hospital, in the generator's order.
TRANSFER_REASONS = ('Respiratory', 'Cardiac', 'Infection or sepsis', 'Urinary tract infection', 'Fall or injury',
    'Change in mental status', 'Gastrointestinal', 'Dehydration or electrolytes', 'Surgical complication',
    'Planned procedure', 'Other')

transfer_logs = Table('transfer_logs', metadata,
    # One hospital transfer per row: every discharge to a hospital, with what
    # the clinical reports cut it by -- reason, payer, place, how long after
    # admission, where the resident had come from. The same event as its
    # discharge_logs row, which records only where the resident went; this is
    # its clinical record, so transfer reports read one table and can cross any
    # of its columns (reason by payer, by facility, by days since admission).
    #
    # Built from saved stays and logs on every update; the reason is drawn from
    # the stay id, so a rebuild gives every transfer the same reason again.
    # Keyed to the stay, as discharge_logs is, so rebuilding discharge_logs never
    # meets a key pointing into it; a stay has at most one discharge.
    Column('stay_id', Uuid, ForeignKey('res_stays.stay_id'), primary_key=True),
    # The stay's facility, copied in so a range of transfers is read from this
    # table alone, as resident_summaries copies places in.
    Column('facility_id', Uuid, ForeignKey('facilities.facility_id'), nullable=False),
    Column('transfer_date', Date, nullable=False),
    # The payer on the day of the transfer: the discharge's.
    Column('payer_id', Uuid, ForeignKey('payers.payer_id'), nullable=False),
    Column('admission_date', Date, nullable=False),
    # transfer_date - admission_date: length of stay from admission, unlike
    # discharge_logs.los, which counts only the final payer period.
    Column('days_since_admission', Integer, nullable=False),
    # Where the resident was admitted from. Admitted from a hospital and sent
    # back within 30 days is a rehospitalization.
    Column('admission_source_type', String, nullable=False),
    Column('reason', String, nullable=False),
    # The hospital the resident went to: the discharge's destination.
    Column('hospital_name', String, nullable=False),
    CheckConstraint('days_since_admission >= 0'),
    CheckConstraint('transfer_date >= admission_date'),
    CheckConstraint("reason IN (" + ", ".join(f"'{reason}'" for reason in TRANSFER_REASONS) + ")",
        name='ck_transfer_logs_reason'),
    Index('ix_transfer_logs_date', 'transfer_date', 'facility_id'),
)

# The kinds of incident, in the generator's order.
INCIDENT_TYPES = ('Fall', 'Skin tear or bruise', 'Medication error', 'Resident altercation', 'Pressure injury',
    'Elopement or wandering', 'Choking', 'Other')

incident_logs = Table('incident_logs', metadata,
    # One resident incident per row: a fall, a skin tear, a medication error and
    # so on, on a day the resident was in a bed, and the day its investigation
    # closed. Its own event, recorded nowhere else, so clinical reports read it
    # alone and can cross any of its columns.
    #
    # Built from saved stays on every update; each stay's incidents -- how
    # many, which days, what kind, when closed -- are drawn from its id, so a
    # rebuild gives the same incidents.
    Column('incident_id', Uuid, primary_key=True),
    Column('stay_id', Uuid, ForeignKey('res_stays.stay_id'), nullable=False),
    Column('resident_id', Uuid, ForeignKey('residents.resident_id'), nullable=False),
    # The stay's facility, copied in so a range is read from this table alone. A
    # resident only ever stays at one facility, so distinct residents add up.
    Column('facility_id', Uuid, ForeignKey('facilities.facility_id'), nullable=False),
    Column('incident_date', Date, nullable=False),
    Column('incident_type', String, nullable=False),
    # The resident's payer that day: the payer period covering the incident.
    Column('payer_id', Uuid, ForeignKey('payers.payer_id'), nullable=False),
    # The incident sent the resident to a hospital: one per hospital transfer
    # for a fall or injury, on its transfer day, so Incidents and Hospital
    # Transfers agree.
    Column('hospitalized', Boolean, nullable=False),
    # How serious: 1 no injury, 2 minor, 3 moderate, 4 major, 5 severe. Levels 4
    # and 5 are major; every hospitalized incident is one of them.
    Column('severity', SmallInteger, nullable=False),
    # The hour it happened, 0-23; reports group it into morning, afternoon,
    # evening and night.
    Column('incident_hour', SmallInteger, nullable=False),
    # The day its investigation closed. Kept even when it is after the latest
    # simulated day: an incident is open while that day is still to come.
    Column('closed_date', Date, nullable=False),
    CheckConstraint('closed_date > incident_date'),
    CheckConstraint('severity BETWEEN 1 AND 5', name='ck_incident_logs_severity'),
    CheckConstraint('incident_hour BETWEEN 0 AND 23', name='ck_incident_logs_hour'),
    CheckConstraint('NOT hospitalized OR severity >= 4', name='ck_incident_logs_hospitalized_major'),
    CheckConstraint("incident_type IN (" + ", ".join(f"'{kind}'" for kind in INCIDENT_TYPES) + ")",
        name='ck_incident_logs_type'),
    Index('ix_incident_logs_date', 'incident_date', 'facility_id'),
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
    # Every day's closing census summed over the month -- an additive measure, so
    # months and facilities sum, and the average daily census divides it once by
    # the days. The month in progress counts only the days generated so far.
    Column('census_days', Integer, nullable=False),
    PrimaryKeyConstraint('month_start', 'facility_id', 'payer_type'),
    CheckConstraint('closing_census = opening_census + admissions + changes_in '
        '- discharges - changes_out'),
    CheckConstraint('opening_census >= 0 AND closing_census >= 0 AND admissions >= 0 '
        'AND discharges >= 0 AND changes_in >= 0 AND changes_out >= 0'),
    CheckConstraint("date_trunc('month', month_start) = month_start"),
    Index('ix_monthly_payer_census_facts_facility', 'facility_id', 'month_start'),
)

monthly_admission_facts = Table('monthly_admission_facts', metadata,
    # A calendar-month rollup of daily_admission_facts, for the monthly ADT
    # trending report's admissions view.
    #
    # It exists because monthly_payer_census_facts cannot answer this question.
    # That table serves the same report's net change view and already carries
    # monthly admissions, but it has no referral source and could not gain one:
    # its opening_census and closing_census are a level rather than a flow, and
    # a resident's presence in a bed does not divide by the place they arrived
    # from. Adding source there would multiply every census row six ways for a
    # number that does not decompose, and break the CHECK that keeps the
    # opening/flow/closing identity honest.
    #
    # 177,519 rows against the 429,722 daily rows it summarises -- 41%, which is
    # poor compression, so the case for it is the dimension rather than the size.
    # Measured at the report's 24-month default: monthly totals cost 44ms grouped
    # from the daily table and about 6ms here.
    #
    # Flows only. Every column sums over any set of rows, so a month is the sum
    # of its own days and needs no balance carried into it.
    Column('month_start', Date, nullable=False),
    Column('facility_id', Uuid, ForeignKey('facilities.facility_id'), nullable=False),
    # Payer TYPE, matching monthly_payer_census_facts and monthly_referral_facts.
    # The report filters by type and never shows a plan name; plan names stay in
    # daily_admission_facts and admission_logs.
    Column('payer_type', String, nullable=False),
    # Where the resident came from. This is the dimension the table exists for.
    # Kept at type rather than name: the referring hospital report reads names,
    # and it has monthly_referral_facts for exactly that.
    Column('source_type', String, nullable=False),
    Column('admissions', SmallInteger, nullable=False),
    Column('readmissions', SmallInteger, nullable=False),
    Column('readmissions_30_day', SmallInteger, nullable=False),
    PrimaryKeyConstraint('month_start', 'facility_id', 'payer_type', 'source_type'),
    CheckConstraint("source_type IN ('Hospital', 'Skilled Nursing', 'Home', "
        "'Rehab Facility', 'Assisted Living', 'Community')"),
    CheckConstraint('admissions > 0'),
    CheckConstraint('readmissions BETWEEN 0 AND admissions'),
    CheckConstraint('readmissions_30_day BETWEEN 0 AND readmissions'),
    CheckConstraint("date_trunc('month', month_start) = month_start"),
    Index('ix_monthly_admission_facts_facility', 'facility_id', 'month_start'),
)

monthly_discharge_facts = Table('monthly_discharge_facts', metadata,
    # The discharge counterpart to monthly_admission_facts, carrying the
    # dimension monthly_payer_census_facts cannot: where the resident went.
    #
    # 200,295 rows against the 405,579 daily rows it summarises, 49%. As with
    # admissions the case is the dimension rather than the compression.
    Column('month_start', Date, nullable=False),
    Column('facility_id', Uuid, ForeignKey('facilities.facility_id'), nullable=False),
    Column('payer_type', String, nullable=False),
    # Where the resident went. Type rather than name, matching the report's filter.
    Column('destination_type', String, nullable=False),
    Column('discharges', SmallInteger, nullable=False),
    Column('ama_discharges', SmallInteger, nullable=False),
    # Summed, never averaged: a stored mean makes every roll-up above facility
    # level silently wrong. Integer rather than SmallInteger because this is a
    # sum of stay lengths, bounded by nothing the way a bed count is -- the worst
    # monthly cell measures 2,362 today, which a larger dataset would outgrow.
    Column('length_of_stay_days', Integer, nullable=False),
    PrimaryKeyConstraint('month_start', 'facility_id', 'payer_type', 'destination_type'),
    CheckConstraint("destination_type IN ('Hospital', 'Skilled Nursing', 'Home', "
        "'Rehab Facility', 'Assisted Living', 'Community', 'Funeral Home')"),
    CheckConstraint('discharges > 0'),
    CheckConstraint('ama_discharges BETWEEN 0 AND discharges'),
    CheckConstraint('length_of_stay_days >= discharges'),
    CheckConstraint("date_trunc('month', month_start) = month_start"),
    Index('ix_monthly_discharge_facts_facility', 'facility_id', 'month_start'),
)

monthly_referral_facts = Table('monthly_referral_facts', metadata,
    # A calendar-month rollup of the hospital referrals inside
    # daily_admission_facts, for the referring hospital report. That report reads
    # 36 complete months for every hospital at once, which is the whole of the
    # daily table's hospital half on every load.
    #
    # This is not a row-count win and was not built for one: at 165,665 rows it is
    # 84% of the 198,014 daily rows it summarises, because a facility/payer/hospital
    # combination rarely recurs inside one month. It was built because it is narrow,
    # ordered for this report, and free of the per-row date_trunc and the payers
    # lookup. Measured against the same queries on daily_admission_facts:
    # the report list 32ms against 79ms, and one hospital's detail 0.6ms against
    # 13.7ms, or 2.8ms with a partial index on (source_name, summary_date) added to
    # the daily table instead. The index alone does nothing for the list query,
    # which reads every hospital, and that is the query the report always runs.
    #
    # Flows only. There is no census here, so every column sums over any set of
    # rows and a month can be rebuilt from its own days alone.
    Column('month_start', Date, nullable=False),
    Column('hospital', String, ForeignKey('referring_hospitals.hospital'), nullable=False),
    Column('facility_id', Uuid, ForeignKey('facilities.facility_id'), nullable=False),
    # Payer TYPE, not payer_id. At payer_id grain this rollup measured 378,357 rows
    # against 429,418 source rows -- a copy rather than a summary, the same trap
    # daily_payer_change_facts documents. The report filters by type and never
    # shows a plan name; plan names stay in admission_logs.
    Column('payer_type', String, nullable=False),
    # Referrals are bounded by monthly admission volume per hospital/facility pair,
    # which never approaches a smallint.
    Column('admissions', SmallInteger, nullable=False),
    Column('readmissions', SmallInteger, nullable=False),
    Column('readmissions_30_day', SmallInteger, nullable=False),
    PrimaryKeyConstraint('month_start', 'hospital', 'facility_id', 'payer_type'),
    CheckConstraint('admissions > 0'),
    CheckConstraint('readmissions BETWEEN 0 AND admissions'),
    CheckConstraint('readmissions_30_day BETWEEN 0 AND readmissions'),
    CheckConstraint("date_trunc('month', month_start) = month_start"),
    # The report's detail view reads one hospital across every month. Without this
    # it scans the table; with it the lookup is 0.6ms.
    Index('ix_monthly_referral_facts_hospital', 'hospital', 'month_start'),
)

monthly_pdpm_census_facts = Table('monthly_pdpm_census_facts', metadata,
    # A calendar-month rollup of pdpm_rate_logs for the PDPM residents Current
    # Medicare PDPM counts: Original Medicare and Managed Medicare PDPM on a PDPM
    # contract. Its Overview compares today with last month's, the last 6 and 12
    # months' and the all-time average, which from the rate steps alone read all
    # 924,406 Medicare steps on every load: 1.1 s. 24,613 rows here, 2.7% of them.
    #
    # Flows, not census: each column sums resident-days, so any set of months
    # adds up and an average divides once. The API reads whole months here and
    # only the partial edge days of a trailing period from the steps.
    #
    # Rebuilt whole after census_logs on every update, because census_logs and its
    # steps are: payer periods are edited after the fact, so any month may change.
    Column('month_start', Date, nullable=False),
    Column('facility_id', Uuid, ForeignKey('facilities.facility_id'), nullable=False),
    # medicare or managed_medicare_pdpm. Two values, so the type grain costs a
    # factor of two on a table this small and keeps the report's Federal / Managed
    # split available.
    Column('payer_type', String, nullable=False),
    # PDPM residents in a bed, summed over the month's days.
    Column('resident_days', Integer, nullable=False),
    # Each day's PDPM rate, summed over the same days.
    Column('actual_rates', Numeric(14, 2), nullable=False),
    # Each day's PDPM day factor, summed. The neutral rate is the national per
    # diem times it, applied at read time, so a change of per diem rebuilds
    # nothing.
    Column('factor_days', Numeric(12, 4), nullable=False),
    PrimaryKeyConstraint('month_start', 'facility_id', 'payer_type'),
    CheckConstraint('resident_days > 0'),
    CheckConstraint('actual_rates > 0 AND factor_days > 0'),
    CheckConstraint("payer_type IN ('medicare', 'managed_medicare_pdpm')"),
    CheckConstraint("date_trunc('month', month_start) = month_start"),
)

monthly_medicaid_census_facts = Table('monthly_medicaid_census_facts', metadata,
    # A calendar-month rollup of census_logs for the residents Historical and
    # Monthly Medicaid count: Medicaid in a state whose Medicaid pays on PDPM
    # case mix, Texas today. Monthly Medicaid Trending read from census_logs
    # took 1.3 s for 24 months and 3.6 s for every month since 2023, splitting
    # 161,419 census segments between the months they span on every load.
    #
    # Flows, not census: each column sums resident-days, so any set of months
    # adds up and an average divides once. A segment crossing a month boundary
    # is split between the two; the latest simulated day cuts an open one.
    #
    # Rebuilt whole after census_logs on every update, because census_logs is:
    # payer periods are edited after the fact, so any month may change.
    Column('month_start', Date, nullable=False),
    Column('facility_id', Uuid, ForeignKey('facilities.facility_id'), nullable=False),
    # Medicaid residents in a bed, summed over the month's days.
    Column('resident_days', Integer, nullable=False),
    # Each day's Medicaid rate, summed over the same days.
    Column('actual_rates', Numeric(14, 2), nullable=False),
    PrimaryKeyConstraint('month_start', 'facility_id'),
    CheckConstraint('resident_days > 0'),
    CheckConstraint('actual_rates >= 0'),
    CheckConstraint("date_trunc('month', month_start) = month_start"),
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
    'users': 'Accounts permitted to read the reports. Passwords are stored only as bcrypt digests; the plaintext exists nowhere in the database or the repository.',
    'referring_hospitals': 'The hospitals that refer residents in, and the region each one refers into. State and portfolio are joins through regions, never stored copies.',
    'res_stays': 'Admission-to-discharge episodes. A null discharge date means currently admitted.',
    'res_payer_stays': 'Payer periods inside an admission episode. The active period has no end date.',
    'admission_logs': 'One actual admission event per episode, including referring source and readmission flags.',
    'medicaid_applications': 'Admissions that started pending Medicaid. Preserves application/approval metrics after payer records are retroactively corrected.',
    'discharge_logs': 'One actual discharge event per closed episode. LOS measures the final payer period.',
    'incident_logs': 'One resident incident per row, on a day the resident was in a bed, with its type, the payer that day, whether it sent the resident to a hospital, its severity and hour, and the day its investigation closed.',
    'transfer_logs': 'One hospital transfer per row: each discharge to a hospital with its hospital, reason, payer, facility, days since admission and admission source, so clinical reports can cross any of them.',
    'payer_change_logs': 'One row per payer change, flattened with the period it moved from. Derived from res_payer_stays to spare every report the self-join on period_number - 1.',
    'daily_admission_facts': 'Additive daily admission measures at facility/payer/source grain. Reports group these rows; parent scopes are not stored.',
    'daily_discharge_facts': 'Additive daily discharge measures at facility/payer/destination/disposition grain. Length of stay is a sum beside its count so any grouping divides correctly.',
    'daily_payer_change_facts': 'Additive daily payer-change counts at facility/from-type/to-type grain. Residents affected is a distinct count and is read from res_payer_stays instead.',
    'daily_payer_census_facts': 'Daily census and movement by payer type: opening + admissions + changes in - discharges - changes out = closing. Sums back to adt_daily_census.',
    'monthly_payer_census_facts': 'Calendar-month rollup of daily_payer_census_facts for monthly trending. Flows are summed; census is taken from the first and last day of each month.',
    'monthly_admission_facts': 'Calendar-month rollup of daily_admission_facts at facility/payer-type/source-type grain, for monthly admissions trending by referral source. monthly_payer_census_facts carries monthly admissions too but has no source dimension and cannot gain one, because census is a level rather than a flow.',
    'monthly_discharge_facts': 'Calendar-month rollup of daily_discharge_facts at facility/payer-type/destination-type grain, for monthly discharge trending by destination. Length of stay is a sum beside its count so any grouping divides correctly.',
    'monthly_referral_facts': 'Calendar-month rollup of the hospital referrals in daily_admission_facts, at hospital/facility/payer-type grain. Flows only, so every column sums over any set of rows.',
    'adt_daily_census': 'Daily facility census: opening + admissions - discharges = closing.',
    'sandbox_schema_migrations': 'Preserved legacy SQL migration history; new migrations use Alembic.',
    'sandbox_generator_runs': 'Reference-generator completion records used to retain existing data.',
    'sandbox_generator_rules': 'Fingerprint of the generator code each table was last built with; update rebuilds a generator whose fingerprint changed.',
    'sandbox_daily_runs': 'Committed generator/day checkpoints; independent of schema and backfill versions.',
    'sandbox_adt_residents': 'Internal simulation state for readmissions, eligibility and cumulative skilled days.',
    'sandbox_adt_active_stays': 'Internal future simulation plans. These are not completed clinical events.',
    'database_migration_checksums': 'Checksums of applied Alembic revisions and their frozen artifacts.',
    'database_backfill_runs': 'Immutable job identity, durable batch checkpoint and cumulative progress per database.',
}
for _name, _description in _descriptions.items():
    metadata.tables[_name].info['description'] = _description

users.c.password_hash.info['description'] = 'bcrypt digest, salt and cost factor included. Never a plaintext password, and never reversible.'
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
referring_hospitals.c.region_id.info['description'] = 'The region this hospital refers into. Verified one region per hospital, so this is a fact about the hospital rather than a summary of its referrals.'
monthly_discharge_facts.c.destination_type.info['description'] = 'Destination category the residents were discharged to. The dimension this table exists to provide.'
monthly_discharge_facts.c.length_of_stay_days.info['description'] = 'Summed length of stay for the grouped discharges. Divide by discharges for an average; never store the average.'
monthly_admission_facts.c.source_type.info['description'] = 'Referral source category the admissions came from. The dimension this table exists to provide; monthly_payer_census_facts cannot carry it.'
monthly_admission_facts.c.admissions.info['description'] = 'Admissions into this facility on this payer type from this source category during the month.'
monthly_referral_facts.c.hospital.info['description'] = 'Referring hospital name, matching daily_admission_facts.source_name where source_type is Hospital.'
monthly_referral_facts.c.payer_type.info['description'] = 'Payer type of the admissions counted. Deliberately coarser than the daily table: at payer_id grain this rollup came to 88% of its source rows.'
monthly_referral_facts.c.admissions.info['description'] = 'Admissions referred by this hospital into this facility on this payer type during the month.'
res_payer_stays.c.end_date.info['description'] = 'Exclusive period end; null until payer change or discharge actually occurs.'
medicaid_applications.c.application_date.info['description'] = 'Admission date when Medicaid coverage was pending; a row permanently identifies a pending-at-admission case.'
medicaid_applications.c.approved_date.info['description'] = 'Actual approval date; null while unresolved. Approved coverage is retroactive to application_date.'
adt_active_stays.c.medicaid_approval.info['description'] = 'Private planned approval date and payer ID; not a completed approval event.'
backfill_runs.c.checkpoint.info['description'] = 'Job-owned JSON cursor/watermark committed atomically with each batch.'
