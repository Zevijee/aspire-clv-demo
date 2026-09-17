"""Compatibility imports; implementation lives in api routes/services/queries."""

from api.queries.table_filters import *  # noqa: F401,F403
from api.services.table_filters import *  # noqa: F401,F403
from api.routes.table_filters import router
