"""Offline scope/dependency planning. Prerequisites are verified, never secretly seeded."""
from dataclasses import dataclass
from datetime import date
from seeding.base import SeedWindow

@dataclass(frozen=True)
class Plan:
    operation: str
    window: SeedWindow
    targets: tuple[str, ...]
    sources: tuple[str, ...]
    reports: tuple[str, ...]
    rebuilds: tuple[str, ...] = ()
    replacement: SeedWindow | None = None
    facility_codes: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    organization_id: str = 'aspire-demo'
    scenario_key: str = 'aspire-demo'
    versions: tuple[tuple[str, str], ...] = ()
    changed_fields: tuple[str, ...] = ()
    backfill: str | None = None
    batch_size: int = 1000

    def describe(self):
        from seeding.registry import source_stages
        return {'operation': self.operation, 'from': self.window.start_date.isoformat(),
            'through': self.window.end_date.isoformat(), 'requested': list(self.targets),
            'source_order': list(source_stages(self.sources)),
            'generator_order': list(self.sources), 'report_order': list(self.reports),
            'rebuild_sources': list(self.rebuilds), 'replace_from': self.replacement.start_date.isoformat() if self.replacement else None,
            'replace_through': self.replacement.end_date.isoformat() if self.replacement else None,
            'facility_codes': list(self.facility_codes), 'entity_ids': list(self.entity_ids),
            'organization_id': self.organization_id, 'scenario_key': self.scenario_key,
            'versions': dict(self.versions), 'changed_fields': list(self.changed_fields),
            'backfill': self.backfill, 'batch_size': self.batch_size,
            'prerequisites': 'Existing dependencies are verified. Only source_order is generated.',
            'retention': 'No rolling-window deletion. Rebuilds replace only requested facility/date source scopes.',
            'boundaries': 'Stateful repairs resume before the first changed day and replay that facility through retained as-of.',
            'pipeline_version': 3,
            'batches': 'Dataset-first source batches commit with checkpoints. After all sources complete, reporting groups affected facilities by interval and publishes separately.',
            'references': 'Payers are organization-wide; hospitals cover the selected facilities regional directory. Reference edits do not regenerate admissions.'}


def build_plan(operation='update', targets=None, through=None, history_months=36, replace_from=None, *,
               facility_codes=(), entity_ids=(), organization_id='aspire-demo', scenario_key='aspire-demo',
               versions=None, changed_fields=(), backfill=None, batch_size=1000, concurrency=1):
    from reporting.registry import REPORTS
    from reporting.planner import affected_reports, ordered_reports
    if operation not in ('update', 'populate', 'rebuild', 'refresh', 'backfill', 'full-reset'):
        raise ValueError('Unknown operation.')
    if not 1 <= batch_size <= 10000:
        raise ValueError('Batch size must be between 1 and 10000.')
    if concurrency != 1:
        raise ValueError('This runner currently supports one worker; source publication locks serialize writes. Use --concurrency 1.')
    if organization_id != 'aspire-demo' and operation != 'refresh':
        raise ValueError('This demo scenario owns organization aspire-demo; it cannot seed another organization.')
    if scenario_key != 'aspire-demo' and operation != 'refresh':
        raise ValueError('No generator is registered for that scenario key.')
    window = SeedWindow.ending_on(through, history_months)
    if replace_from and replace_from > window.end_date:
        raise ValueError('Scope start must not be after as-of.')
    replacement = SeedWindow(replace_from, window.end_date) if replace_from else None
    facilities = tuple(sorted(set(facility_codes)))
    entities = tuple(sorted(set(entity_ids)))
    fields = tuple(sorted(set(changed_fields)))
    if operation == 'refresh':
        if entities:
            raise ValueError('Reporting refresh requires facility/date scope, not unresolved entity IDs.')
        selected = tuple(targets or REPORTS)
        reports = ordered_reports(selected)
        return Plan(operation, replacement or window, selected, (), reports, facility_codes=facilities,
            organization_id=organization_id, batch_size=batch_size)
    from seeding.registry import SOURCES, SOURCE_DEPENDENTS, BACKFILLS
    if operation == 'backfill':
        if backfill not in BACKFILLS:
            raise ValueError('Choose a named backfill: ' + ', '.join(BACKFILLS))
        if targets:
            raise ValueError('A named backfill declares its datasets; do not also pass --dataset.')
        if entities and backfill != 'hospital_assignments':
            raise ValueError('Entity IDs are supported for hospital_assignments admission IDs only.')
        selected = BACKFILLS[backfill]
        return Plan(operation, window, selected, (), affected_reports(selected), replacement=replacement,
            facility_codes=facilities, entity_ids=entities, organization_id=organization_id, scenario_key=scenario_key,
            versions=((backfill, '1'),), backfill=backfill, batch_size=batch_size)
    if backfill:
        raise ValueError('--backfill-name requires the backfill operation.')
    if operation == 'rebuild' and not targets:
        raise ValueError('Rebuild requires an explicit --dataset. Use full-reset to replace the full demo population.')
    selected = tuple(targets or SOURCES)
    unknown = set(selected) - SOURCES.keys()
    if unknown:
        raise ValueError('Unknown source datasets: ' + ', '.join(sorted(unknown)) + '. Use refresh for report datasets.')
    if entities and set(selected) != {'payers'}:
        raise ValueError('Entity scope is supported for payer reference codes or named hospital backfill admission IDs. Use facility/date scope for stay simulation.')
    if replace_from and operation not in ('rebuild', 'full-reset'):
        raise ValueError('--from is for a scoped rebuild, backfill, or reporting refresh; update/populate find every missing day in retained history.')
    if operation == 'full-reset' and (facilities or entities or replace_from or targets):
        raise ValueError('Full reset has no narrow scope. For datasets/facilities/dates use rebuild.')
    if 'licensed_beds' in fields:
        raise ValueError('The registered movement scenario does not support populated-facility capacity corrections as a field update. No history will be rewritten automatically.')
    if 'type_name' in fields:
        raise ValueError('Payer type display-name changes are not supported by the current HTTP/UI vocabulary. Payer and plan name edits remain supported with --changed-field name.')
    if fields:
        if len(selected) != 1 or selected[0] not in ('facilities', 'payers', 'hospitals'):
            raise ValueError('Changed-field updates currently apply to a single reference dataset; use a named backfill for event fields.')
        allowed = {'facilities': {'name','city','state','portfolio','region','market','operating_group'},
                   'payers': {'name'}, 'hospitals': {'state','portfolio','region'}}[selected[0]]
        if set(fields) - allowed:
            raise ValueError('Unsupported changed fields for selected reference dataset.')
    affected = set(selected)
    # Label/definition updates have no population-generator descendants.
    for name in selected:
        affected.update(SOURCE_DEPENDENTS.get(name, ()))
    sources = tuple(name for name in SOURCES if name in affected)
    if any(SOURCES[name].date_based for name in sources) and window.start_date < date(2020,1,1):
        raise ValueError('This registered movement scenario starts in January 2020; the requested shared 36-month window begins before that anchor.')
    expected_versions = {name: SOURCES[name].version for name in sources}
    for name, value in (versions or {}).items():
        if name not in expected_versions or expected_versions[name] != value:
            raise ValueError(f'No compatible registered generator version {name}={value}.')
    reports = affected_reports(sources, {selected[0]: fields} if fields else None)
    return Plan(operation, window, selected, sources, reports,
        tuple(name for name in sources if SOURCES[name].date_based) if operation in ('rebuild','full-reset') else (),
        replacement, facilities, entities, organization_id, scenario_key, tuple(expected_versions.items()), fields,
        batch_size=batch_size)
