"""Each use case owns one lazy, read-only, consistent database snapshot."""

from contextlib import contextmanager
from collections.abc import Iterator

from sqlalchemy import text
from sqlalchemy.engine import Connection

from data.db import get_engine


@contextmanager
def report_connection() -> Iterator[Connection]:
    """Pass the same connection through nested reads and release it on every exit."""
    with get_engine().connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        with connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            from reporting.publication.loads import require_no_pending_load
            require_no_pending_load(connection)
            yield connection
