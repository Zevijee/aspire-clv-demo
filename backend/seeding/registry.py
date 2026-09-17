"""Generator declarations only; reporting dependencies belong to reporting."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Dataset:
    name: str
    dependencies: tuple[str, ...] = ()
    version: str = '1'
    date_based: bool = False
    owned_fields: tuple[str, ...] = ()
    compatibility: str = 'future-only'

SOURCES = {
    'states': Dataset('states', version='state-reference-v1', owned_fields=('labels',)),
    'portfolios': Dataset('portfolios', version='portfolio-reference-v1', owned_fields=('labels',)),
    'regions': Dataset('regions', ('portfolios',), 'region-reference-v1', owned_fields=('labels',)),
    'facilities': Dataset('facilities', ('states', 'portfolios', 'regions'), version='facility-reference-v1', owned_fields=('labels', 'hierarchy', 'licensed_beds')),
    'hospitals': Dataset('hospitals', ('facilities',), 'hospital-reference-v1', owned_fields=('labels', 'hierarchy')),
    'payers': Dataset('payers', version='payer-reference-v1', owned_fields=('labels',)),
    'admissions': Dataset('admissions', ('facilities', 'hospitals', 'payers'), 'admissions-independent-v5', True, ('admission_events',)),
    'discharges': Dataset('discharges', ('admissions',), 'resident-movement-v2', True, ('stays', 'discharge_events', 'census')),
    'payer_changes': Dataset('payer_changes', ('discharges',), 'coverage-incremental-v1', True, ('coverage', 'payer_events')),
    'bed_holds': Dataset('bed_holds', ('discharges',), 'bed-holds-v1', True, ('bed_holds',)),
}
SOURCE_DEPENDENTS = {
    'admissions': ('discharges', 'payer_changes', 'bed_holds'),
    'discharges': ('payer_changes', 'bed_holds'),
}
BACKFILLS = {
    'canonical_sources': ('admissions', 'discharges', 'payer_changes', 'facilities', 'hospitals'),
    'hospital_assignments': ('admissions',),
    'initial_payer': ('discharges',),
}


def source_stages(names):
    """One dependency order for previews and execution.

    Resident/stay persistence is mandatory when loading movement, but selecting
    coverage alone verifies existing parents instead of regenerating them.
    """
    selected = set(names)
    if selected & {'admissions', 'discharges'}:
        selected.update(('residents', 'census_stays'))
    dependencies = {name: spec.dependencies for name, spec in SOURCES.items()}
    dependencies.update(residents=('facilities', 'hospitals', 'payers'),
        census_stays=('residents',),
        admissions=(*SOURCES['admissions'].dependencies, 'census_stays'),
        discharges=('admissions', 'census_stays'))
    ordered, visiting = [], set()

    def visit(name):
        if name in ordered:
            return
        if name in visiting:
            raise ValueError('Source dependency cycle: ' + name)
        visiting.add(name)
        for parent in dependencies[name]:
            if parent in selected:
                visit(parent)
        visiting.remove(name)
        ordered.append(name)

    for name in names:
        visit(name)
    return tuple(ordered)


def default_registry():
    from seeding.generators.hierarchy import StatesSeeder, PortfoliosSeeder, RegionsSeeder
    from seeding.generators.facilities import FacilitiesSeeder
    from seeding.generators.hospitals import HospitalsSeeder
    from seeding.generators.payers import PayersSeeder
    from seeding.generators.admissions import AdmissionsSeeder
    from seeding.generators.discharges import DischargesSeeder
    from seeding.generators.payer_changes import PayerChangesSeeder
    from seeding.generators.bed_holds import BedHoldsSeeder
    return (StatesSeeder(), PortfoliosSeeder(), RegionsSeeder(), FacilitiesSeeder(), HospitalsSeeder(), PayersSeeder(), AdmissionsSeeder(),
        DischargesSeeder(), PayerChangesSeeder(), BedHoldsSeeder())
