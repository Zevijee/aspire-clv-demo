import json
from datetime import date, timedelta
from hashlib import sha256
from math import exp, pi, sin
from random import Random
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    func,
    or_,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from data.writers.core import write_rows

from seeding.base import BaseSeeder, SeedContext, SeedResult, coverage, datasets
from seeding.generators.facilities import facilities

from seeding.scenarios.admissions import (GENERATOR_VERSION, RANDOM_VERSION, MIN_ADMISSIONS_PER_FACILITY,
    MAX_ADMISSIONS_PER_FACILITY, READMISSION_RATE, PAYER_NAMES, PAYER_TYPE_WEIGHTS, FIRST_NAMES, LAST_NAMES)

from data.models.admissions import metadata, admissions
from seeding.generators.residents import arrival_resident

def choose_weighted_payer_type(random: Random) -> str:
    selected = random.randrange(sum(weight for _, weight in PAYER_TYPE_WEIGHTS))
    cumulative_weight = 0

    for payer_type, weight in PAYER_TYPE_WEIGHTS:
        cumulative_weight += weight
        if selected < cumulative_weight:
            return payer_type

    raise RuntimeError("Unable to select an admission payer type.")


def get_admission_source(random: Random, facility: dict) -> tuple[str, str]:
    from seeding.reference_data.hospital_directory import hospital_names_for_facility
    source_type = random.choices(
        (
            "Skilled Nursing",
            "Hospital",
            "Home",
            "Rehab Facility",
            "Assisted Living",
            "Community",
        ),
        weights=(150, 340, 75, 51, 48, 16),
        k=1,
    )[0]

    sources = {
        "Skilled Nursing": ("Riverside Skilled Nursing", "Grandview Care Center"),
        "Hospital": hospital_names_for_facility(facility)[:3],
        "Home": ("Private Residence",),
        "Rehab Facility": ("Riverside Rehabilitation", "Grandview Rehabilitation Center"),
        "Assisted Living": ("Cedar Lane Assisted Living", "Willow Terrace Assisted Living"),
        "Community": ("Community Referral",),
    }
    return source_type, random.choice(sources[source_type])


def build_daily_admissions(day: date, facility_rows: list[dict]) -> list[dict]:
    """Generate one immutable calendar-day partition, independently of the requested window."""
    rows = []
    seasonality = 1 + 0.12 * sin(2 * pi * day.toordinal() / 90)
    variation = 0.88 + Random(f"aspire-volume:{day.isoformat()}").random() * 0.24
    weekday = (1.06, 1.04, 1.02, 1.0, 0.98, 0.93, 0.9)[day.weekday()]
    for facility in sorted(facility_rows, key=lambda row: row["facility_code"]):
        code = facility["facility_code"]
        average = (
            Random(f"aspire-facility-volume:{code}").randint(
                MIN_ADMISSIONS_PER_FACILITY, MAX_ADMISSIONS_PER_FACILITY
            )
            / 1095.75
        )
        random = Random(f"{RANDOM_VERSION}:{code}:{day.isoformat()}")
        # Poisson arrivals allow quiet days as well as normal spikes.
        threshold = exp(-average * seasonality * variation * weekday)
        product, count = 1.0, -1
        while product > threshold:
            product *= random.random()
            count += 1
        for index in range(count):
            admission_id = str(
                uuid5(NAMESPACE_URL, f"aspire:{RANDOM_VERSION}:{code}:{day.isoformat()}:{index}")
            )
            payer_random = Random(f"admission-payer:{admission_id}")
            resident = arrival_resident(admission_id)
            source_random = Random(f"admission-source:{admission_id}")
            readmission_random = Random(f"admission-readmission:{admission_id}")
            payer_type = choose_weighted_payer_type(payer_random)
            source_type, source_name = get_admission_source(source_random, facility)
            if source_type == "Hospital":
                from seeding.reference_data.hospital_directory import choose_referring_hospital
                source_name = choose_referring_hospital(facility, admission_id, day)
            readmission = readmission_random.random() < READMISSION_RATE
            rows.append(
                {
                    "admission_id": admission_id,
                    "facility_code": code,
                    "resident_id": resident['resident_id'],
                    "resident_name": resident['display_name'],
                    "admission_date": day,
                    "payer_type": payer_type,
                    "payer_name": payer_random.choice(PAYER_NAMES[payer_type]),
                    "admission_source_type": source_type,
                    "admission_source_name": source_name,
                    "is_readmission": readmission,
                    "readmission_days_since_prior": readmission_random.randint(1, 60) if readmission else None,
                }
            )
    return rows


def plan_admissions(context):
    connection, window = context.connection, context.window
    key = context.dataset_key('admissions')
    scope = admissions.c.facility_code.in_(context.facility_codes)
    facility_rows = [dict(row) for row in connection.execute(select(facilities).where(
        facilities.c.facility_code.in_(context.facility_codes))).mappings()]
    if len(facility_rows) != len(context.facility_codes):
        raise ValueError("A requested facility does not exist. Populate its reference first.")
    stored = dict(connection.execute(select(admissions.c.admission_date, func.count())
        .where(scope).group_by(admissions.c.admission_date)).all())
    completed = dict(connection.execute(select(coverage.c.seed_date, coverage.c.row_count)
        .where(coverage.c.dataset == key)).all())
    legacy_days = set(connection.scalars(select(coverage.c.seed_date).where(
        coverage.c.dataset == 'admissions')))
    if not stored:
        legacy_days = set()
    first_changed = None
    marks = []
    pending = []
    recount_days = []

    replacing_days = []
    for index in range(window.days):
        day = window.start_date + timedelta(days=index)
        replacing = context.rebuild and (context.replace_window is None or
            context.replace_window.start_date <= day <= context.replace_window.end_date)
        actual = stored.get(day, 0)
        if not replacing and day not in completed and day in legacy_days:
            # Adopt verified legacy completion without changing existing identities.
            marks.append(dict(dataset=key, seed_date=day, row_count=actual))
            continue
        if not replacing and completed.get(day) == actual:
            continue
        if not replacing and day in completed and completed[day] != actual:
            raise ValueError(f"Admission coverage differs on {day} for {context.facility_codes[0]}. Use an explicit scoped rebuild to repair it.")
        if replacing:
            replacing_days.append(day)
        rows = build_daily_admissions(day, facility_rows)
        if context.scenario_key != "aspire-demo":
            raise ValueError("No generator is registered for this scenario key.")
        pending.extend(rows)
        marks.append(dict(dataset=key, seed_date=day, row_count=len(rows)))
        if not replacing and actual:
            recount_days.append(day)
        first_changed = min(first_changed or day, day)
    return dict(rows=pending, marks=marks, replacing_days=replacing_days,
        recount_days=recount_days, first_changed=first_changed)


def persist_admissions(context, planned):
    connection = context.connection
    scope = admissions.c.facility_code.in_(context.facility_codes)
    changed = 0
    if planned['replacing_days']:
        changed += connection.execute(admissions.delete().where(scope,
            admissions.c.admission_date.in_(planned['replacing_days']))).rowcount
    result = write_rows(connection, admissions, planned['rows'], mode='ignore',
        batch_size=context.batch_size, returning=('admission_id',))
    changed += result.changed
    marks = planned['marks']
    if planned['recount_days']:
        counts = dict(connection.execute(select(admissions.c.admission_date, func.count())
            .where(scope, admissions.c.admission_date.in_(planned['recount_days']))
            .group_by(admissions.c.admission_date)).all())
        for mark in marks:
            if mark['seed_date'] in counts:
                mark['row_count'] = counts[mark['seed_date']]
    write_rows(connection, coverage, marks, batch_size=context.batch_size)
    fingerprint = sha256(json.dumps(context.facility_codes).encode()).hexdigest()
    stmt = postgresql_insert(datasets).values(name=context.dataset_key('admissions'),
        version=GENERATOR_VERSION, input_fingerprint=fingerprint)
    connection.execute(stmt.on_conflict_do_update(index_elements=[datasets.c.name],
        set_={'version':stmt.excluded.version, 'input_fingerprint':stmt.excluded.input_fingerprint}))
    count = connection.scalar(select(func.count()).select_from(admissions).where(scope))
    return SeedResult('admissions', count, changed, planned['first_changed'],
        tuple(row[0] for row in result.returned))


class AdmissionsSeeder(BaseSeeder):
    name = "admissions"
    dependencies = ("facilities", "hospitals", "payers")

    def seed(self, context):
        return persist_admissions(context, plan_admissions(context))

    def validate(self, context, result):
        scope = admissions.c.facility_code.in_(context.facility_codes)
        actual = dict(context.connection.execute(select(admissions.c.admission_date, func.count())
            .where(scope).group_by(admissions.c.admission_date)).all())
        completed = dict(context.connection.execute(select(coverage.c.seed_date, coverage.c.row_count)
            .where(coverage.c.dataset == context.dataset_key(self.name),
                coverage.c.seed_date.between(context.window.start_date, context.window.end_date))).all())
        if len(completed) != context.window.days or any(actual.get(day, 0) != n for day, n in completed.items()):
            raise ValueError("Admission completion includes each requested day and must reconcile with its rows.")
