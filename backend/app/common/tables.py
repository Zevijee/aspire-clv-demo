"""Bounded table queries; features explicitly own their permitted columns."""
from collections.abc import Mapping, Sequence
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.sql import ColumnElement, Select

from .errors import ApiError

Row = TypeVar('Row')


class PageQuery(BaseModel):
    model_config = ConfigDict(extra='forbid')
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
    sort: str | None = Field(default=None, max_length=100)
    direction: Literal['asc', 'desc'] = 'asc'


class Page(BaseModel, Generic[Row]):
    items: list[Row]
    total: int
    limit: int
    offset: int


def paginate(statement: Select, query: PageQuery, *, columns: Mapping[str, ColumnElement],
        default_sort: str, unique_key: ColumnElement | Sequence[ColumnElement]) -> Select:
    key = query.sort or default_sort
    if key not in columns:
        raise ApiError('invalid_sort', 'Unsupported sort column.')
    column = columns[key]
    descending = query.direction == 'desc'
    order = column.desc() if descending else column.asc()
    # Stable ties keep residents/events from moving unpredictably between pages.
    # A single key breaks ties ascending, as every table always has. Several
    # keys -- a row keyed by (date, person), say -- break them in the sort's own
    # direction, so a sort on the first of them reads an index on those columns
    # in order and stops at the page, instead of sorting every matching row.
    if isinstance(unique_key, Sequence):
        ties = [part.desc() if descending else part.asc() for part in unique_key]
    else:
        ties = [unique_key.asc()]
    return statement.order_by(None).order_by(order, *ties).limit(query.limit).offset(query.offset)
