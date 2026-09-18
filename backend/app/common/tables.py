"""Bounded table queries; features explicitly own their permitted columns."""
from collections.abc import Mapping
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
        default_sort: str, unique_key: ColumnElement) -> Select:
    key = query.sort or default_sort
    if key not in columns:
        raise ApiError('invalid_sort', 'Unsupported sort column.')
    column = columns[key]
    order = column.desc() if query.direction == 'desc' else column.asc()
    # Stable ties keep residents/events from moving unpredictably between pages.
    return statement.order_by(None).order_by(order, unique_key.asc()).limit(query.limit).offset(query.offset)
