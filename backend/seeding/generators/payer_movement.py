"""Continue coverage for changed stays without regenerating completed histories."""
from datetime import timedelta
from random import Random
from uuid import NAMESPACE_URL, uuid5
from sqlalchemy import select, func, text
from data.writers.core import write_rows
from data.models.payer_periods import periods
from data.models.payer_changes import payer_changes
from data.models.stays import stays
from seeding.scenarios.admissions import PAYER_NAMES
from seeding.scenarios.coverage import DESTINATIONS
from seeding.base import SeedResult
from seeding.state.store import mark_coverage

VERSION = 'coverage-incremental-v1'


def seed_payers(context):
    connection, window = context.connection, context.window
    code = context.facility_codes[0]
    from data.models.canonical import payer_plans
    from seeding.reference_data.payers import PAYER_REFERENCES
    plan_labels = dict(connection.execute(select(payer_plans.c.code,payer_plans.c.name).where(payer_plans.c.organization_id == 'aspire-demo')).all())
    source_names,display_names = {},{}
    for definition in PAYER_REFERENCES:
        source_key = (definition['source_type'],definition['source_name'])
        label = plan_labels.get(definition['code'],definition['name'])
        source_names[(definition['source_type'],label)] = definition['source_name']
        source_names[source_key] = definition['source_name']
        display_names[source_key] = label
    canonical_plans = {}
    if context.canonical_first:
        from data.models.canonical import payer_plan_source_keys, payer_stays
        from data.writers.sources import write_payer_stays, replace_payer_stays
        canonical_plans = dict(connection.execute(select(payer_plan_source_keys.c.external_key,
            payer_plan_source_keys.c.payer_plan_id).where(
                payer_plan_source_keys.c.organization_id == 'aspire-demo',
                payer_plan_source_keys.c.source_system == 'legacy-adt')).all())

    def persist_periods(rows):
        if context.canonical_first:
            records = []
            for row in rows:
                kind = row['payer_type']
                original_name = source_names.get((kind, row['payer_name']), row['payer_name'])
                plan_id = canonical_plans.get(f'{len(kind)}:{kind}{original_name}')
                if plan_id is None:
                    raise ValueError('Payer reference is missing. Update payer references before coverage.')
                records.append(dict(payer_stay_id=row['period_id'], stay_id=row['stay_id'],
                    payer_plan_id=plan_id, started_on=row['start_date'], ended_on=row['end_date'],
                    time_precision='date', source_sequence=0))
            # pending_periods contains whole stay histories, including retained
            # intervals before a scoped repair. Clear old unique date keys first.
            writer = replace_payer_stays if context.rebuild or context.operation == 'full-reset' else write_payer_stays
            writer(connection, records, organization_id='aspire-demo',
                source_system='legacy-adt', batch_size=context.batch_size)
        return write_rows(connection, periods, rows, batch_size=context.batch_size).changed

    from data.models.seed_tracking import coverage
    known = set(connection.scalars(select(coverage.c.seed_date).where(
        coverage.c.dataset == context.dataset_key('payer_changes'))))
    missing = [window.start_date + timedelta(days=i) for i in range(window.days)
        if window.start_date + timedelta(days=i) not in known]
    if not missing and context.changed_from is None and not context.rebuild:
        return SeedResult('payer_changes', connection.scalar(select(func.count()).select_from(payer_changes)
            .where(payer_changes.c.facility_code == code)), 0)
    cutoff = min(missing + ([context.changed_from] if context.changed_from else []) +
        ([(context.replace_window or window).start_date] if context.rebuild else []))
    source = connection.execute(select(stays).where(stays.c.facility_code == code,
        stays.c.start_date <= window.end_date,
        stays.c.end_date.is_(None) | (stays.c.end_date >= cutoff))).mappings().all()
    if context.canonical_first:
        from data.models.canonical import census_stays
        known_stays = set(connection.scalars(select(census_stays.c.stay_id).where(
            census_stays.c.organization_id == 'aspire-demo', census_stays.c.facility_code == code)))
        if any(row['stay_id'] not in known_stays for row in source):
            raise ValueError('Shared census stays are missing. Run the scoped canonical_sources backfill before a payer-only update.')
    legacy_last = connection.scalar(select(func.max(coverage.c.seed_date)).where(coverage.c.dataset == 'payer_changes'))
    published_through = max(known | ({legacy_last} if legacy_last else set()), default=None)
    old_periods = {}
    for row in connection.execute(select(periods).where(periods.c.facility_code == code)
            .order_by(periods.c.stay_id, periods.c.start_date, periods.c.period_id)).mappings():
        old_periods.setdefault(row['stay_id'], []).append(dict(row))
    changed = 0
    pending_periods, pending_changes = [], []
    if context.rebuild:
        changed += connection.execute(payer_changes.delete().where(payer_changes.c.facility_code == code,
            payer_changes.c.effective_date.between(cutoff,window.end_date))).rowcount
    for stay in source:
        if not stay['initial_payer_type']:
            raise ValueError('A stay is missing its admission payer; use a named initial-payer backfill first.')
        history = old_periods.get(stay['stay_id'], [])
        end = stay['end_date'] if stay['end_date'] and stay['end_date'] <= window.end_date else None
        if context.rebuild:
            history = [row for row in history if row['start_date'] < cutoff]
        history = [row for row in history if end is None or row['start_date'] < end]
        if not history:
            history = [dict(period_id=str(uuid5(NAMESPACE_URL, f"payer-period:{stay['stay_id']}:0")),
                stay_id=stay['stay_id'], facility_code=code, start_date=stay['start_date'], end_date=end,
                payer_type=stay['initial_payer_type'], payer_name=stay['initial_payer_name'])]
        current = history[-1]
        while True:
            index = len(history) - 1
            duration = Random(f"coverage-timing:{stay['stay_id']}:{index}").randint(25, 180) if index == 0 else Random(
                f"coverage-timing:{stay['stay_id']}:{index}").randint(90, 365)
            next_date = current['start_date'] + timedelta(days=duration)
            if context.rebuild and current['start_date'] < cutoff:
                next_date = max(next_date,cutoff)
            if not context.rebuild and published_through and current['period_id'] in {row['period_id'] for row in old_periods.get(stay['stay_id'], [])}:
                next_date = max(next_date, published_through + timedelta(days=1))
            if next_date > window.end_date or (end is not None and next_date >= end):
                current['end_date'] = end
                break
            # A retained interval's next transition is generated only after its last publication.
            # Existing rows are preserved; no reference-label update enters this operation.
            current['end_date'] = next_date
            random = Random(f"coverage-choice:{stay['stay_id']}:{index + 1}")
            payer, name = current['payer_type'], current['payer_name']
            alternatives = [item for item in PAYER_NAMES.get(payer, ()) if item != source_names.get((payer,name),name)]
            if alternatives and random.random() < 0.2:
                name = random.choice(alternatives)
            else:
                destinations = DESTINATIONS.get(payer)
                if not destinations:
                    raise ValueError(f'No demo coverage scenario for payer type {payer}.')
                payer = random.choices(list(destinations), weights=list(destinations.values()))[0]
                name = random.choice(PAYER_NAMES[payer])
            name = display_names.get((payer,name),name)
            current = dict(period_id=str(uuid5(NAMESPACE_URL, f"payer-period:{stay['stay_id']}:{index + 1}")),
                stay_id=stay['stay_id'], facility_code=code, start_date=next_date, end_date=end,
                payer_type=payer, payer_name=name)
            history.append(current)
        old_ids = {row['period_id'] for row in old_periods.get(stay['stay_id'], [])}
        new_ids = {row['period_id'] for row in history}
        if old_ids - new_ids:
            if context.canonical_first:
                connection.execute(payer_stays.delete().where(payer_stays.c.organization_id == 'aspire-demo',
                    payer_stays.c.source_system == 'legacy-adt', payer_stays.c.payer_stay_id.in_(old_ids - new_ids)))
            changed += connection.execute(periods.delete().where(periods.c.period_id.in_(old_ids - new_ids))).rowcount
        pending_periods.extend(history)
        if len(pending_periods) >= context.batch_size:
            changed += persist_periods(pending_periods)
            pending_periods.clear()
        # Changes are uniquely keyed by stay + sequence, even for a resident's readmission.
        changes = []
        for index, row in enumerate(history):
            if index == 0 or not window.start_date <= row['start_date'] <= window.end_date:
                continue
            previous = history[index - 1]
            changes.append(dict(change_id=str(uuid5(NAMESPACE_URL, f"payer-change:{stay['stay_id']}:{index}")),
                facility_code=code, resident_id=stay['resident_id'], resident_name=stay['resident_name'],
                effective_date=row['start_date'], previous_payer_start_date=previous['start_date'],
                new_payer_end_date=row['end_date'], previous_payer_type=previous['payer_type'],
                previous_payer_name=previous['payer_name'], new_payer_type=row['payer_type'],
                new_payer_name=row['payer_name'], change_category='Plan only' if previous['payer_type'] == row['payer_type'] else 'Payer type'))
        old_change_ids = {str(uuid5(NAMESPACE_URL, f"payer-change:{stay['stay_id']}:{index}"))
            for index in range(1, len(old_periods.get(stay['stay_id'], [])))}
        obsolete = old_change_ids - {row['change_id'] for row in changes}
        if obsolete:
            changed += connection.execute(payer_changes.delete().where(payer_changes.c.change_id.in_(obsolete),
                payer_changes.c.effective_date.between(window.start_date, window.end_date))).rowcount
        pending_changes.extend(changes)
        if len(pending_changes) >= context.batch_size:
            changed += write_rows(connection, payer_changes, pending_changes, batch_size=context.batch_size).changed
            pending_changes.clear()
    changed += persist_periods(pending_periods)
    changed += write_rows(connection, payer_changes, pending_changes, batch_size=context.batch_size).changed
    changed += connection.execute(text("""
        UPDATE adt_discharges d SET payer_type=p.payer_type, payer_name=p.payer_name
        FROM adt_resident_stays s JOIN adt_payer_periods p ON p.stay_id=s.stay_id AND p.end_date=s.end_date
        WHERE d.facility_code=:code AND d.resident_id=s.resident_id AND d.facility_code=s.facility_code
          AND d.start_date=s.start_date AND d.discharge_date=s.end_date
          AND (d.payer_type IS DISTINCT FROM p.payer_type OR d.payer_name IS DISTINCT FROM p.payer_name)
    """), {'code': code}).rowcount
    counts = dict(connection.execute(select(payer_changes.c.effective_date, func.count())
        .where(payer_changes.c.facility_code == code).group_by(payer_changes.c.effective_date)).all())
    mark_coverage(context, 'payer_changes', window, counts)
    return SeedResult('payer_changes', sum(counts.values()), changed, cutoff)
