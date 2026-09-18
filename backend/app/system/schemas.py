from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class Health(BaseModel):
    status: Literal['ok', 'ready']


class GeneratorCoverage(BaseModel):
    generator: str
    first_completed_date: date
    latest_completed_date: date
    completed_days: int
    contiguous: bool
    complete_through_today: bool
    last_completed_at: datetime


class DataStatus(BaseModel):
    as_of: date
    timezone: str
    generated_at: datetime
    generators: list[GeneratorCoverage]
