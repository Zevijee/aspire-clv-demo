"""Bounded response cache with coherent revisions and no HTTP dependency."""
import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from functools import wraps
from hashlib import sha256
from inspect import signature
from threading import RLock
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from common.time import business_date
from data.db import get_engine
from data.models.admissions_reporting import cache, state

_locks = [RLock() for _ in range(32)]
MAX_CACHE_ENTRIES = 256
CACHE_VERSION = 16


class ReportingUnavailableError(RuntimeError):
    """Transport-independent readiness failure; the API maps it to HTTP 503."""


def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(f"Unsupported reporting JSON value: {type(value).__name__}")


def _json(value):
    return json.loads(json.dumps(value, default=_json_default, allow_nan=False))


def _normalized(value):
    if isinstance(value, dict):
        return {key: _normalized(item) for key, item in value.items()}
    if isinstance(value, (list, set, frozenset)):
        # Multi-select order/duplicates do not change report meaning.
        unique = {json.dumps(_normalized(item), sort_keys=True, default=_json_default) for item in value}
        return [json.loads(item) for item in sorted(unique)]
    if isinstance(value, tuple):
        return [_normalized(item) for item in value]
    return value


def cached_report(function):
    """Cache successful results only, never missing data, errors, or mixed revisions.

    All request arguments participate in the key. Authorization must be resolved
    into explicit organization/facility/permission arguments before this boundary.
    Functions open their snapshot internally; callers do not pass DB connections.
    """
    function_signature = signature(function)

    @wraps(function)
    def wrapped(*args, **kwargs):
        arguments = function_signature.bind(*args, **kwargs)
        arguments.apply_defaults()
        payload = [CACHE_VERSION, function.__module__, function.__qualname__,
                   business_date(), _normalized(arguments.arguments)]
        key = sha256(json.dumps(payload, sort_keys=True, default=_json_default).encode()).hexdigest()
        # Release connections before computing misses or waiting on a process
        # lock, so concurrent misses do not hold the pool while requesting more.
        with _locks[int(key[:8], 16) % len(_locks)]:
            for _ in range(3):
                with get_engine().connect() as connection:
                    from reporting.publication.loads import require_no_pending_load
                    require_no_pending_load(connection)
                    snapshot = connection.execute(
                        select(state.c.revision, state.c.ready, cache.c.payload)
                        .select_from(state.outerjoin(cache, (cache.c.cache_key == key)
                                                     & (cache.c.revision == state.c.revision)))
                        .where(state.c.id == 1)
                    ).mappings().one_or_none()
                if snapshot is None or not snapshot["ready"]:
                    raise ReportingUnavailableError(
                        "Reporting data needs an explicit refresh. Use the reporting refresh command; "
                        "the API does not modify source data or apply migrations.")
                if snapshot["payload"] is not None:
                    return snapshot["payload"]
                result = function(*args, **kwargs)
                serialized = _json(result)
                with get_engine().begin() as connection:
                    require_no_pending_load(connection)
                    current = connection.execute(select(state.c.revision, state.c.ready)
                                                 .where(state.c.id == 1).with_for_update()).one()
                    if not current.ready or current.revision != snapshot["revision"]:
                        continue
                    connection.execute(insert(cache).values(cache_key=key, revision=current.revision,
                        payload=serialized).on_conflict_do_nothing(index_elements=[cache.c.cache_key]))
                    expired = select(cache.c.cache_key).order_by(cache.c.created_at.desc(), cache.c.cache_key).offset(MAX_CACHE_ENTRIES)
                    connection.execute(cache.delete().where(cache.c.cache_key.in_(expired)))
                    return result
        raise ReportingUnavailableError("Reporting data changed while the result was prepared. Please retry.")

    return wrapped
