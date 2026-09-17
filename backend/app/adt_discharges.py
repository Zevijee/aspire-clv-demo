"""Compatibility imports; implementation lives in api routes/services/queries."""

from api.queries.adt_discharges import *  # noqa: F401,F403
from api.services.adt_discharges import *  # noqa: F401,F403
from api.routes.adt_discharges import router
