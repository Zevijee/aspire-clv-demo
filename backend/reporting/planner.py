"""Pure dependency planning; safe for offline preview and production ingestion."""
from dataclasses import dataclass, replace
from calendar import monthrange
from datetime import date
from typing import Iterable, Mapping

from reporting.registry import REPORTS, SOURCE_ALIASES


@dataclass(frozen=True)
class ReportScope:
    start_date: date
    end_date: date
    facility_codes: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    organization_id: str | None = None

    def __post_init__(self):
        if self.start_date > self.end_date:
            raise ValueError("Reporting start date must be on or before end date.")
        object.__setattr__(self, "facility_codes", tuple(sorted(set(self.facility_codes))))
        object.__setattr__(self, "entity_ids", tuple(sorted(set(self.entity_ids))))

    def monthly(self):
        """Refresh the whole affected month from retained daily/source facts."""
        return replace(self, start_date=self.start_date.replace(day=1),
                       end_date=self.end_date.replace(day=monthrange(self.end_date.year, self.end_date.month)[1]))


@dataclass(frozen=True)
class RefreshTask:
    dataset: str
    scope: ReportScope
    reason: str
    read_scope: ReportScope | None = None


def ordered_reports(names: Iterable[str], *, include_dependencies: bool = True) -> tuple[str, ...]:
    names = (names,) if isinstance(names, str) else tuple(names)
    unknown = set(names) - REPORTS.keys()
    if unknown:
        raise ValueError("Unknown reporting datasets: " + ", ".join(sorted(unknown)))
    selected = set(names)
    result, visiting = [], set()

    def visit(name):
        if name in result:
            return
        if name in visiting:
            raise ValueError("Reporting dependency cycle at " + name)
        visiting.add(name)
        for dependency in REPORTS[name].dependencies:
            if dependency in REPORTS and (include_dependencies or dependency in selected):
                visit(dependency)
        visiting.remove(name)
        result.append(name)

    for name in REPORTS:
        if name in selected:
            visit(name)
    return tuple(result)


def affected_reports(changed_datasets: Iterable[str], changed_fields=None) -> tuple[str, ...]:
    """Include changes/deletions, without requesting regeneration of source ancestors.

    Omit fields, or include '*', '__insert__', or '__delete__', for structural changes.
    A field mapping can narrow each changed source independently.
    """
    changed_datasets = (changed_datasets,) if isinstance(changed_datasets, str) else changed_datasets
    changed = {SOURCE_ALIASES.get(name, name) for name in changed_datasets}
    if isinstance(changed_fields, Mapping):
        fields = {SOURCE_ALIASES.get(name, name): {value} if isinstance(value, str) else set(value)
                  for name, value in changed_fields.items()}
    elif changed_fields is not None:
        value = {changed_fields} if isinstance(changed_fields, str) else set(changed_fields)
        fields = {name: value for name in changed}
    else:
        fields = {}
    affected = set()
    for name in ordered_reports(REPORTS, include_dependencies=False):
        spec = REPORTS[name]
        for dependency in spec.dependencies:
            if dependency not in changed:
                continue
            actual, relevant = fields.get(dependency), spec.fields.get(dependency)
            if actual is not None and relevant is not None and not (
                actual & relevant or actual & {"*", "__insert__", "__delete__"}
            ):
                continue
            affected.add(name)
            changed.add(name)
            break
    return ordered_reports(affected, include_dependencies=False)


def plan_changes(changed_datasets, scope: ReportScope, changed_fields=None, *, retained_through=None):
    """Propagate an explicit correction scope without regenerating source ancestors.

    Callers know their retained source watermark. For a historical movement/stay
    correction pass it as retained_through: census balances downstream of that
    correction may change until the retained end, even outside the changed day.
    This function is pure; it never silently discovers or widens a scope via I/O.
    """
    names = affected_reports(changed_datasets, changed_fields)
    if retained_through is not None and retained_through < scope.end_date:
        raise ValueError("Retained through date cannot precede the requested correction scope.")
    tasks = []
    for name in names:
        current, reason = scope, "Changed source fields affect this reporting dataset."
        if retained_through and name in {"daily_census", "monthly_activity", "payer_census"}:
            current = replace(current, end_date=retained_through)
            reason = "Movement/interval corrections propagate through retained census history."
        read_scope = current
        if name in {"monthly_activity", "referring_hospitals"}:
            read_scope = current.monthly()
            reason += " Read and replace the complete affected calendar months."
        tasks.append(RefreshTask(name, current, reason, read_scope))
    return tuple(tasks)
