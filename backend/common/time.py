"""One explicit reporting clock, independent of the machine or browser timezone."""
from datetime import datetime
from zoneinfo import ZoneInfo

from common.config import get_settings


def business_date(timezone: str | None = None):
    return datetime.now(ZoneInfo(timezone or get_settings().reporting_timezone)).date()
