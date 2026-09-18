"""Resolve selections by database ID, independently of report grouping."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.engine import Connection

from shared.database.schema import facilities, portfolios, regions

LocationLevel = Literal['state', 'portfolio', 'region', 'facility']


class LocationSelection(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    states: list[str] = Field(default_factory=list, max_length=100)
    portfolio_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    region_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    facility_ids: list[UUID] = Field(default_factory=list, max_length=1000)

    @field_validator('states')
    @classmethod
    def state_codes(cls, values):
        values = [value.strip().upper() for value in values]
        if any(len(value) != 2 or not value.isascii() or not value.isalpha() for value in values):
            raise ValueError('States must be two-letter codes.')
        return sorted(set(values))


def facility_locations(selection: LocationSelection):
    """OR within a level, AND across levels; empty selections mean unfiltered.

    A selection matching no locations remains empty. It must never become an
    unfiltered query. These filters are not an authorization mechanism.
    """
    statement = select(
        facilities.c.facility_id, facilities.c.facility.label('facility_name'), facilities.c.beds,
        regions.c.region_id, regions.c.region.label('region_name'),
        portfolios.c.portfolio_id, portfolios.c.portfolio.label('portfolio_name'), portfolios.c.state,
    ).select_from(facilities.join(regions).join(portfolios))
    for column, values in (
        (portfolios.c.state, selection.states),
        (portfolios.c.portfolio_id, selection.portfolio_ids),
        (regions.c.region_id, selection.region_ids),
        (facilities.c.facility_id, selection.facility_ids),
    ):
        if values:
            statement = statement.where(column.in_(values))
    return statement


def resolve_facility_ids(connection: Connection, selection: LocationSelection) -> tuple[UUID, ...]:
    statement = facility_locations(selection).with_only_columns(facilities.c.facility_id)
    return tuple(connection.scalars(statement.order_by(facilities.c.facility_id)))
