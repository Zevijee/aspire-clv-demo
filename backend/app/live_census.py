"""Compatibility imports; implementation lives in api routes/services/queries."""

from api.queries.live_census import *  # noqa: F401,F403
from api.services.live_census import *  # noqa: F401,F403
from api.routes.live_census import router
