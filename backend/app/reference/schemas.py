"""API shapes; table definitions remain in shared.database.schema."""
from uuid import UUID

from pydantic import BaseModel, Field

from ..common.locations import LocationSelection
from ..common.tables import PageQuery


class LocationQuery(LocationSelection, PageQuery):
    pass


class FacilityLocation(BaseModel):
    facility_id: UUID
    facility_name: str
    beds: int
    region_id: UUID
    region_name: str
    portfolio_id: UUID
    portfolio_name: str
    state: str


class PayerQuery(PageQuery):
    payer_types: list[str] = Field(default_factory=list, max_length=100)
    is_skilled: bool | None = None
    search: str = Field(default='', max_length=200)


class Payer(BaseModel):
    payer_id: UUID
    payer_type: str
    payer_name: str
    is_skilled: bool
