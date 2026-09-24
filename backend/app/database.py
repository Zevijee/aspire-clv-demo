"""One pool per worker; one read-only transaction per report request.

Sign-in is the one writer: it records and rotates refresh tokens.
"""
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from alembic.migration import MigrationContext
from alembic.util.exc import CommandError
from fastapi import Depends, Request
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from shared.database.lifecycle import ensure_compatible, postgres_url, scripts
from .common.errors import DatabaseNotReady
from .config import Settings


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.expected_heads = set(scripts().get_heads())
        self.engine = create_engine(
            postgres_url(settings.database_url.get_secret_value()),
            pool_size=settings.pool_size, max_overflow=settings.max_overflow,
            pool_timeout=settings.pool_timeout_seconds, pool_pre_ping=True,
            hide_parameters=True,
            connect_args={'connect_timeout': settings.connect_timeout_seconds},
            isolation_level='REPEATABLE READ',
        )

    @contextmanager
    def connection(self, *, check_head=True, write=False) -> Iterator[Connection]:
        with self.engine.connect() as connection:
            if write:
                # Read committed, so a token row locked FOR UPDATE by a concurrent
                # refresh is re-read once released rather than failing the
                # repeatable-read snapshot with a serialization error.
                connection = connection.execution_options(isolation_level='READ COMMITTED')
            # Acquire the lifecycle lock BEFORE taking the report's repeatable-read
            # snapshot. Otherwise an upgrade could commit between those two steps.
            available = connection.exec_driver_sql(
                'SELECT pg_try_advisory_lock_shared(1935766390, 1)').scalar_one()
            try:
                connection.commit()
                if not available:
                    raise DatabaseNotReady()
                with connection.begin():
                    if not write:
                        connection.exec_driver_sql('SET TRANSACTION READ ONLY')
                    connection.exec_driver_sql("SELECT set_config('statement_timeout', %s, true)",
                        (str(self.settings.statement_timeout_ms),))
                    if check_head:
                        actual = set(MigrationContext.configure(connection).get_current_heads())
                        if actual != self.expected_heads:
                            raise DatabaseNotReady()
                    yield connection
            finally:
                if available and not connection.invalidated:
                    try:
                        if connection.in_transaction():
                            connection.rollback()
                        connection.exec_driver_sql('SELECT pg_advisory_unlock_shared(1935766390, 1)')
                        connection.commit()
                    except SQLAlchemyError:
                        # Never return a connection holding a session lock to the pool.
                        connection.invalidate()
                        raise

    def check_ready(self):
        with self.connection(check_head=False) as connection:
            try:
                ensure_compatible(connection)
            except (ValueError, OSError, CommandError):
                raise DatabaseNotReady() from None

    def close(self):
        self.engine.dispose()


def get_connection(request: Request) -> Iterator[Connection]:
    with request.app.state.database.connection() as connection:
        yield connection


DbConnection = Annotated[Connection, Depends(get_connection)]


def get_write_connection(request: Request) -> Iterator[Connection]:
    """For the auth routes only. The transaction commits when the route returns."""
    with request.app.state.database.connection(write=True) as connection:
        yield connection


DbWriteConnection = Annotated[Connection, Depends(get_write_connection)]
