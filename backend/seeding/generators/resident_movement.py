"""Shared stays and daily census derived from the canonical admission events."""

from datetime import date, timedelta
from copy import deepcopy
from hashlib import sha256
from heapq import heappop, heappush
from math import pi, sin
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
    select,
    text,
)

from seeding.generators.admissions import (
    FIRST_NAMES,
    LAST_NAMES,
    MAX_ADMISSIONS_PER_FACILITY,
    MIN_ADMISSIONS_PER_FACILITY,
    PAYER_NAMES,
    admissions,
    build_daily_admissions,
)
from seeding.base import SeedContext, SeedResult, coverage, datasets
from seeding.generators.discharges import discharges
from seeding.generators.facilities import facilities

VERSION = "resident-movement-v2"
ANCHOR = date(2020, 1, 1)
from data.models.stays import metadata, stays, census, state
from data.writers.core import copy_rows, write_rows
from seeding.generators.residents import opening_resident

def discharge_from_admission(admission: dict, day: date, city: str) -> dict:
    """One deterministic discharge with the same resident and payer as its admission."""
    random = Random(f"{VERSION}:outcome:{admission['admission_id']}")
    outcome = random.choices(("Routine", "Transfer", "Deceased", "AMA"), (62, 27, 8, 3))[0]
    if outcome == "Deceased":
        destination, name = "Funeral Home", "Not applicable"
    elif outcome == "AMA":
        destination, name = "Home", "Private Residence"
    elif outcome == "Transfer":
        destination = random.choices(
            ("Hospital", "Skilled Nursing", "Rehab Facility"), (75, 18, 7)
        )[0]
        name = {
            "Hospital": f"{city} General Hospital",
            "Skilled Nursing": f"{city} Grandview Care",
            "Rehab Facility": f"{city} Rehabilitation Center",
        }[destination]
    else:
        destination = random.choices(("Home", "Assisted Living", "Hospice"), (82, 13, 5))[0]
        name = {
            "Home": "Private Residence",
            "Assisted Living": f"{city} Willow Terrace",
            "Hospice": f"{city} Harborlight Hospice",
        }[destination]
    return {
        "discharge_id": str(uuid5(NAMESPACE_URL, f"{VERSION}:{admission['admission_id']}")),
        "facility_code": admission["facility_code"],
        "resident_id": admission["resident_id"],
        "resident_name": admission["resident_name"],
        "start_date": admission["admission_date"],
        "discharge_date": day,
        "payer_type": admission["payer_type"],
        "payer_name": admission["payer_name"],
        "discharge_type": outcome,
        "destination_type": destination,
        "destination_name": name,
        "los_days": (day - admission["admission_date"]).days,
    }


def stay_row(admission, end):
    return {
        "stay_id": admission["admission_id"],
        "facility_code": admission["facility_code"],
        "resident_id": admission["resident_id"],
        "resident_name": admission["resident_name"],
        "start_date": admission["admission_date"],
        "end_date": end,
        "opening_resident": False,
        "initial_payer_type": admission["payer_type"],
        "initial_payer_name": admission["payer_name"],
    }


def simulate_movement(facility_rows, admission_rows, window, *, checkpoint=None, on_boundary=None, new_admission_ids=(), on_identity=None, opening_stays=()):
    """Fixed-anchor simulation: stable overlaps, no negative census or overfilled beds."""
    if window.start_date < ANCHOR:
        raise ValueError("Resident movement supports reporting windows beginning in 2020 or later.")
    by_day = {}
    for row in admission_rows:
        by_day.setdefault(row["admission_date"], []).append(row)
    facility_map = {row["facility_code"]: row for row in facility_rows}
    active = {code: [] for code in facility_map}
    baseline = {}
    mean_los = {}
    occupancy = {}
    stay_rows, discharge_rows, daily_rows = [], [], []
    identity_candidates = set(new_admission_ids)
    recently_departed = {code: [] for code in facility_map}
    for code, facility in facility_map.items():
        # Established long-term residents provide the opening cohort; they are not new admissions.
        retained_opening = [row for row in opening_stays if row["facility_code"] == code]
        baseline[code] = len(retained_opening) if retained_opening else round(facility["licensed_beds"] * 0.58)
        average = (
            Random(f"aspire-facility-volume:{code}").randint(
                MIN_ADMISSIONS_PER_FACILITY, MAX_ADMISSIONS_PER_FACILITY
            )
            / 1095.75
        )
        mean_los[code] = max(7, min(180, facility["licensed_beds"] * 0.25 / average))
        profile = Random(f'occupancy-profile:{code}')
        occupancy[code] = (profile.uniform(0.79, 0.89), profile.uniform(0, 2 * pi),
                           profile.randint(150, 300))
        if retained_opening:
            stay_rows.extend(dict(row) for row in retained_opening)
            continue
        for index in range(baseline[code]):
            identifier = str(uuid5(NAMESPACE_URL, f"{VERSION}:opening:{code}:{index}"))
            resident = opening_resident(identifier)
            stay_rows.append(
                {
                    "stay_id": identifier,
                    "facility_code": code,
                    "resident_id": resident['resident_id'],
                    "resident_name": resident['display_name'],
                    "start_date": ANCHOR - timedelta(days=90 + index * 7),
                    "end_date": None,
                    "opening_resident": True,
                    "initial_payer_type": "Medicaid",
                    "initial_payer_name": PAYER_NAMES["Medicaid"][0],
                }
            )

    def depart(admission, day):
        code = admission["facility_code"]
        recently_departed[code].append({"resident_id":admission["resident_id"], "resident_name":admission["resident_name"], "discharge_date":day.isoformat(), "known":day >= window.start_date})
        recently_departed[code] = recently_departed[code][-200:]
        if day >= window.start_date:
            discharge_rows.append(
                discharge_from_admission(
                    admission, day, facility_map[admission["facility_code"]]["city"]
                )
            )
            stay_rows.append(stay_row(admission, day))

    if checkpoint:
        recently_departed.update(checkpoint.get('recently_departed', {}))
        for code, entries in checkpoint['active'].items():
            for entry in entries:
                admission = dict(entry['admission'])
                admission['admission_date'] = date.fromisoformat(admission['admission_date'])
                heappush(active[code], (date.fromisoformat(entry['scheduled_end']), admission['admission_id'], admission))
        day = date.fromisoformat(checkpoint['through']) + timedelta(days=1)
    else:
        day = ANCHOR
    while day <= window.end_date:
        arrivals = (
            by_day.get(day, [])
            if day >= window.start_date
            else build_daily_admissions(day, facility_rows)
        )
        openings = {code: baseline[code] + len(queue) for code, queue in active.items()}
        admitted = dict.fromkeys(facility_map, 0)
        discharged = dict.fromkeys(facility_map, 0)
        arriving = dict.fromkeys(facility_map, 0)
        for admission in arrivals:
            arriving[admission['facility_code']] += 1
        for code, queue in active.items():
            base, phase, cycle = occupancy[code]
            elapsed = (day - ANCHOR).days
            # Small, differently phased facility changes avoid synchronized census swings.
            target_rate = (base + 0.018 * sin(2 * pi * elapsed / cycle + phase)
                           + 0.006 * sin(2 * pi * elapsed / 61 + phase * 2)
                           + 0.003 * sin(2 * pi * elapsed / 365.25))
            target = round(facility_map[code]['licensed_beds'] * target_rate)
            departures = max(0, openings[code] + arriving[code] - target)
            # Planned LOS ranks departures; occupancy determines demo movement volume.
            for _ in range(min(departures, len(queue))):
                _, _, admission = heappop(queue)
                depart(admission, day)
                discharged[code] += 1
        for admission in sorted(arrivals, key=lambda row: row["admission_id"]):
            code = admission["facility_code"]
            queue = active[code]
            if admission['admission_id'] in identity_candidates:
                active_residents = {entry[2]['resident_id'] for entry in queue}
                candidates = [row for row in recently_departed[code]
                    if row.get('known',True) and date.fromisoformat(row['discharge_date']) < day
                    and row['resident_id'] not in active_residents]
                chosen = None
                if admission.get('is_readmission') and candidates:
                    candidates.sort(key=lambda row: (row['discharge_date'],row['resident_id']))
                    candidates = list({row['resident_id']:row for row in candidates}.values())
                    chosen = Random(f"readmission-resident:{admission['admission_id']}").choice(candidates)
                    admission['resident_id'] = chosen['resident_id']
                    admission['resident_name'] = chosen['resident_name']
                    recently_departed[code] = [row for row in recently_departed[code] if row['resident_id'] != chosen['resident_id']]
                admission['is_readmission'] = chosen is not None
                admission['readmission_days_since_prior'] = (day-date.fromisoformat(chosen['discharge_date'])).days if chosen else None
                if on_identity:
                    on_identity(admission)
            # Earlier departures free beds without changing admission records.
            if baseline[code] + len(queue) >= facility_map[code]["licensed_beds"]:
                _, _, outgoing = heappop(queue)
                depart(outgoing, day)
                discharged[code] += 1
            random = Random(f"{VERSION}:length:{admission['admission_id']}")
            days = max(1, min(365, round(random.triangular(0.25, 1.75, 1) * mean_los[code])))
            heappush(queue, (day + timedelta(days=days), admission["admission_id"], admission))
            admitted[code] += 1
        if day >= window.start_date:
            for code, queue in active.items():
                daily_rows.append(
                    {
                        "facility_code": code,
                        "census_date": day,
                        "opening_census": openings[code],
                        "closing_census": baseline[code] + len(queue),
                        "admissions": admitted[code],
                        "discharges": discharged[code],
                    }
                )
        tomorrow = day + timedelta(days=1)
        if on_boundary and day >= window.start_date and (tomorrow.month != day.month or day == window.end_date):
            payload = {'through': day.isoformat(), 'recently_departed': recently_departed, 'active': {code: [
                {'scheduled_end': scheduled.isoformat(), 'admission': {key: value.isoformat() if isinstance(value, date) else value
                    for key, value in admission.items()}} for scheduled, _, admission in queue]
                for code, queue in active.items()}}
            on_boundary(day, payload)
        day = tomorrow
    for queue in active.values():
        for end, _, admission in queue:
            stay_rows.append(stay_row(admission, None))
    return stay_rows, discharge_rows, daily_rows


def plan_movement(context, admission_rows=None):
    """Continue one facility from durable boundary state; repairs replay only its affected suffix."""
    from seeding.base import SeedWindow
    from seeding.state.store import load_boundary, save_boundary, mark_coverage
    from data.models.seed_operations import boundaries
    connection, window = context.connection, context.window
    code = context.facility_codes[0]
    facility_rows = [dict(row) for row in connection.execute(select(facilities).where(facilities.c.facility_code == code)).mappings()]
    retained_opening = [dict(row) for row in connection.execute(select(stays).where(
        stays.c.facility_code == code,stays.c.opening_resident.is_(True))).mappings()]
    completed = set(connection.scalars(select(census.c.census_date).where(census.c.facility_code == code,
        census.c.census_date.between(window.start_date, window.end_date))))
    missing = [window.start_date + timedelta(days=i) for i in range(window.days)
        if window.start_date + timedelta(days=i) not in completed]
    repair_from = context.changed_from
    if context.rebuild:
        repair_from = min(repair_from or window.end_date, (context.replace_window or window).start_date)
    if not missing and repair_from is None:
        return None
    earliest = min(missing + ([repair_from] if repair_from else []))
    try:
        checkpoint = load_boundary(connection, 'discharges', code, earliest, VERSION, context.scenario_key)
    except ValueError:
        if not context.rebuild:
            raise
        checkpoint = None
    replay_start = date.fromisoformat(checkpoint['through']) + timedelta(days=1) if checkpoint else window.start_date
    # Legacy histories can supply a durable boundary without regenerating completed dates.
    if checkpoint is None:
        prior_day = earliest - timedelta(days=1)
        previous_census = connection.execute(select(census).where(census.c.facility_code == code,
            census.c.census_date == prior_day)).mappings().one_or_none()
        if previous_census:
            active_stays = connection.execute(select(stays).where(stays.c.facility_code == code,
                stays.c.start_date <= prior_day, (stays.c.end_date.is_(None) | (stays.c.end_date > prior_day)))).mappings().all()
            opening = [row for row in active_stays if row['opening_resident']]
            if len(active_stays) == previous_census['closing_census'] and len(opening) == len(retained_opening):
                average = Random(f'aspire-facility-volume:{code}').randint(MIN_ADMISSIONS_PER_FACILITY, MAX_ADMISSIONS_PER_FACILITY) / 1095.75
                mean_los = max(7, min(180, facility_rows[0]['licensed_beds'] * 0.25 / average))
                entries = []
                for stay in active_stays:
                    if stay['opening_resident']:
                        continue
                    admission = {'admission_id': stay['stay_id'], 'facility_code': code,
                        'resident_id': stay['resident_id'], 'resident_name': stay['resident_name'],
                        'admission_date': stay['start_date'].isoformat(), 'payer_type': stay['initial_payer_type'],
                        'payer_name': stay['initial_payer_name']}
                    days = max(1, min(365, round(Random(f"{VERSION}:length:{stay['stay_id']}").triangular(0.25, 1.75, 1) * mean_los)))
                    entries.append({'scheduled_end': (stay['start_date'] + timedelta(days=days)).isoformat(), 'admission': admission})
                departed = [dict(row) for row in connection.execute(select(discharges.c.resident_id,discharges.c.resident_name,discharges.c.discharge_date).where(discharges.c.facility_code == code, discharges.c.discharge_date <= prior_day).order_by(discharges.c.discharge_date.desc(),discharges.c.discharge_id).limit(200)).mappings()]
                for row in departed:
                    row['discharge_date'] = row['discharge_date'].isoformat()
                checkpoint = {'through': prior_day.isoformat(), 'active': {code: entries}, 'recently_departed': {code: departed}}
                replay_start = earliest
            elif not context.rebuild:
                raise ValueError(f'Existing stay boundary for {code} does not reconcile; request a scoped rebuild rather than replacing completed history implicitly.')
    rows = ([dict(row) for row in connection.execute(select(admissions).where(admissions.c.facility_code == code,
        admissions.c.admission_date.between(replay_start, window.end_date))).mappings()]
        if admission_rows is None else [dict(row) for row in admission_rows
            if replay_start <= row['admission_date'] <= window.end_date])
    output_window = SeedWindow(replay_start, window.end_date)
    identities = []
    def update_identity(row):
        identities.append({name: row[name] for name in ('admission_id', 'resident_id',
            'resident_name', 'is_readmission', 'readmission_days_since_prior')})
    checkpoints = []

    stay_rows, discharge_rows, daily_rows = simulate_movement(facility_rows, rows, output_window, checkpoint=checkpoint,
        on_boundary=lambda day, payload: checkpoints.append((day, deepcopy(payload))),
        opening_stays=retained_opening, new_admission_ids=context.new_admission_ids, on_identity=update_identity)
    return dict(stays=stay_rows, discharges=discharge_rows, census=daily_rows,
        identities=identities, checkpoints=checkpoints, replay_start=replay_start)


def persist_movement(context, planned):
    from seeding.base import SeedWindow
    from seeding.state.store import save_boundary, mark_coverage
    from data.models.seed_operations import boundaries
    connection, window = context.connection, context.window
    code = context.facility_codes[0]
    if planned is None:
        return SeedResult('discharges', connection.scalar(select(func.count()).select_from(discharges)
            .where(discharges.c.facility_code == code)), 0)
    replay_start = planned['replay_start']
    output_window = SeedWindow(replay_start, window.end_date)
    stay_rows, discharge_rows, daily_rows = planned['stays'], planned['discharges'], planned['census']
    identities = planned['identities']
    connection.execute(boundaries.delete().where(boundaries.c.dataset == 'discharges',
        boundaries.c.scope_key == code, boundaries.c.through_date >= replay_start))
    for day, payload in planned['checkpoints']:
        save_boundary(connection, 'discharges', code, day, VERSION, context.scenario_key, payload)
    write_rows(connection, admissions, identities, mode='update', batch_size=context.batch_size)
    # Keep unrelated facilities and retained history. Only replayed outputs are replaced.
    old_count = connection.execute(discharges.delete().where(discharges.c.facility_code == code,
        discharges.c.discharge_date.between(replay_start, window.end_date))).rowcount
    connection.execute(census.delete().where(census.c.facility_code == code,
        census.c.census_date.between(replay_start, window.end_date)))
    # Delete obsolete, generator-owned admission stays only after an explicit source rebuild.
    if context.rebuild:
        missing_stays = select(stays.c.stay_id).where(stays.c.facility_code == code,
            stays.c.opening_resident.is_(False), stays.c.start_date >= replay_start,
            ~stays.c.stay_id.in_(select(admissions.c.admission_id)))
        from data.models.payer_periods import periods
        connection.execute(periods.delete().where(periods.c.stay_id.in_(missing_stays)))
        connection.execute(stays.delete().where(stays.c.stay_id.in_(missing_stays)))
    write_rows(connection, stays, stay_rows, batch_size=context.batch_size)
    copy_rows(connection, discharges, discharge_rows, batch_size=context.batch_size)
    copy_rows(connection, census, daily_rows, batch_size=context.batch_size)
    counts = {}
    for row in discharge_rows:
        counts[row['discharge_date']] = counts.get(row['discharge_date'], 0) + 1
    mark_coverage(context, 'discharges', output_window, counts)
    return SeedResult('discharges', connection.scalar(select(func.count()).select_from(discharges)
        .where(discharges.c.facility_code == code)), old_count + len(discharge_rows) + len(daily_rows), replay_start)


def seed_movement(context):
    return persist_movement(context, plan_movement(context))


def validate_movement(context, result):
    code = context.facility_codes[0]
    invalid = context.connection.scalar(text("""
        SELECT count(*) FROM adt_census_daily c JOIN facilities f USING(facility_code)
        WHERE c.facility_code=:code AND c.census_date BETWEEN :start AND :end AND
          (c.closing_census <> c.opening_census+c.admissions-c.discharges
           OR c.closing_census > f.licensed_beds OR c.opening_census > f.licensed_beds
           OR c.admissions <> (SELECT count(*) FROM adt_admissions a WHERE a.facility_code=c.facility_code AND a.admission_date=c.census_date)
           OR c.discharges <> (SELECT count(*) FROM adt_discharges d WHERE d.facility_code=c.facility_code AND d.discharge_date=c.census_date))
    """), {'code': code, 'start': context.window.start_date, 'end': context.window.end_date})
    continuity = context.connection.scalar(text("""
        SELECT count(*) FROM adt_census_daily current
        JOIN adt_census_daily previous ON previous.facility_code=current.facility_code
          AND previous.census_date=current.census_date-1
        WHERE current.facility_code=:code AND current.census_date BETWEEN :start AND :end
          AND current.opening_census<>previous.closing_census
    """), {'code':code,'start':context.window.start_date,'end':context.window.end_date})
    count = context.connection.scalar(select(func.count()).select_from(census).where(census.c.facility_code == code,
        census.c.census_date.between(context.window.start_date, context.window.end_date)))
    if invalid or continuity or count != context.window.days:
        raise ValueError('Census must reconcile with events and capacity on every requested date.')
