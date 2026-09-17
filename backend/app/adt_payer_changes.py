"""Compatibility imports; implementation lives in api routes/services/queries."""

from api.queries.adt_payer_changes import *  # noqa: F401,F403
from api.services.adt_payer_changes import *  # noqa: F401,F403
from api.routes.adt_payer_changes import log_selections, router
