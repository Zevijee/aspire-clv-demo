"""Compatibility imports; implementation lives in api routes/services/queries."""

from api.queries.facilities import *  # noqa: F401,F403
from api.services.facilities import *  # noqa: F401,F403
from api.routes.facilities import router
