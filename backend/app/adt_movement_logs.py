"""Compatibility imports; implementation lives in api routes/services/queries."""

from api.queries.adt_movement_logs import *  # noqa: F401,F403
from api.services.adt_movement_logs import *  # noqa: F401,F403
from api.routes.adt_movement_logs import router
