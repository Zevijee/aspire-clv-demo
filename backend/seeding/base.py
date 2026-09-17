"""Pure seed scope contracts; connections are supplied only during execution."""
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from sqlalchemy.engine import Connection
from data.models.seed_tracking import metadata, datasets, coverage

@dataclass(frozen=True)
class SeedWindow:
    start_date: date
    end_date: date

    def __post_init__(self):
        if self.end_date < self.start_date:
            raise ValueError("Seed window end must be on or after its start.")

    @classmethod
    def ending_on(cls, as_of=None, history_months=36):
        if history_months != 36:
            raise ValueError("Seed history is always 36 complete months plus the current month. Use --from for a scoped repair.")
        from common.time import business_date
        end = as_of or business_date()
        month = end.year * 12 + end.month - 1 - 36
        return cls(date(month // 12, month % 12 + 1, 1), end)

    @property
    def days(self):
        return (self.end_date - self.start_date).days + 1

@dataclass(frozen=True)
class SeedResult:
    name: str
    row_count: int
    changed_rows: int
    changed_from: date | None = None
    new_admission_ids: tuple[str, ...] = ()

@dataclass(frozen=True)
class SeedContext:
    connection: Connection
    window: SeedWindow
    rebuild: bool = False
    batch_size: int = 1000
    log: Callable[[str], None] = print
    replace_window: SeedWindow | None = None
    facility_codes: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    scenario_key: str = "aspire-demo"
    operation: str = "update"
    changed_from: date | None = None
    changed_fields: tuple[str, ...] = ()
    new_admission_ids: tuple[str, ...] = ()

    canonical_first: bool = False

    def dataset_key(self, dataset):
        if len(self.facility_codes) != 1:
            raise ValueError("Date-based generation requires exactly one facility per transactional batch.")
        return f"{dataset}:{self.facility_codes[0]}"

class BaseSeeder(ABC):
    """Generate scoped facts and validate them; the runner owns transactions.

    Bulk persistence lives in data.writers.core, shared with ingestion and
    projections. Do not implement a generator-specific COPY/upsert/update loop.
    Scope-specific deletes and checkpoint policy remain with their owners.
    """
    name: str
    dependencies: tuple[str, ...] = ()
    @abstractmethod
    def seed(self, context): ...
    @abstractmethod
    def validate(self, context, result): ...
