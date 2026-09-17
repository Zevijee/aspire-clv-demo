"""Public system endpoint contracts."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    service: str
