"""Bounded canonical writes. Caller owns the transaction and reporting refresh."""
from collections.abc import Iterable, Mapping

from dataclasses import dataclass, field
from uuid import uuid4
from sqlalchemy import JSON, Table, cast, func, or_, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert


@dataclass
class WriteResult:
    submitted: int = 0
    changed: int = 0
    returned: list[tuple] = field(default_factory=list)


def _distinct(column, incoming):
    # PostgreSQL JSON has no equality operator. Compare its JSONB representation
    # without changing the stored type or treating object key order as a change.
    if isinstance(column.type, JSON) and not isinstance(column.type, JSONB):
        return cast(column, JSONB).is_distinct_from(cast(incoming, JSONB))
    return column.is_distinct_from(incoming)


def _sql_distinct(table, name, left, right):
    if isinstance(table.c[name].type, JSON) and not isinstance(table.c[name].type, JSONB):
        left, right = f'CAST({left} AS jsonb)', f'CAST({right} AS jsonb)'
    return f'{left} IS DISTINCT FROM {right}'


def _batches(table, rows, batch_size, *, require_keys=True):
    if batch_size < 1:
        raise ValueError('Batch size must be positive.')
    keys = {column.name for column in table.primary_key}
    pending = []
    limit = batch_size
    for supplied in rows:
        row = dict(supplied)
        if not row or set(row) - set(table.c.keys()):
            raise ValueError(f'{table.name}: empty row or unknown columns.')
        if require_keys and not keys <= row.keys():
            raise ValueError(f'{table.name} requires stable keys: {", ".join(sorted(keys))}')
        if pending and (set(row) != set(pending[0]) or len(pending) >= limit):
            yield pending
            pending = []
        limit = min(batch_size, max(1, 60000 // len(row)))
        pending.append(row)
    if pending:
        yield pending


def _copy(connection, table, target, columns, rows):
    from psycopg.types.json import Json, Jsonb
    quote = connection.dialect.identifier_preparer.quote
    adapters = {name: Jsonb if isinstance(table.c[name].type, JSONB) else Json
                for name in columns if isinstance(table.c[name].type, JSON)}
    with connection.connection.driver_connection.cursor() as cursor:
        with cursor.copy(f'COPY {target} ({", ".join(map(quote, columns))}) FROM STDIN') as stream:
            for row in rows:
                stream.write_row(tuple(adapters[name](row[name]) if name in adapters and row[name] is not None
                                       else row[name] for name in columns))


def write_rows(connection, table: Table, rows: Iterable[Mapping], *, mode='upsert',
               batch_size=1000, returning=()) -> WriteResult:
    """Shared insert, conflict-ignore, changed-only upsert and update-only writes.

    Large merges COPY into transaction-local staging then use set-based SQL.
    Scope checks, delete policy, validation and commits belong to the caller.
    Returning contains inserted/changed rows only, never unchanged conflicts.
    """
    if not connection.in_transaction():
        raise ValueError('Bulk writes require a caller-owned transaction.')
    if mode not in ('insert', 'ignore', 'upsert', 'update'):
        raise ValueError(f'Unsupported write mode: {mode}')
    if set(returning) - set(table.c.keys()):
        raise ValueError('Unknown returning columns.')
    keys = [column.name for column in table.primary_key]
    if not keys and mode != 'insert':
        raise ValueError('Merge/update requires a primary key.')
    quote = connection.dialect.identifier_preparer.quote
    target = connection.dialect.identifier_preparer.format_table(table)
    result = WriteResult()
    for batch in _batches(table, rows, batch_size, require_keys=mode != 'insert'):
        columns = list(batch[0])
        fields = [name for name in columns if name not in keys and name not in ('created_at', 'updated_at')]
        needs_client_defaults = mode != 'update' and any(
            column.default is not None and column.name not in columns for column in table.c)
        if mode in ('upsert', 'update'):
            identities = [tuple(row[name] for name in keys) for row in batch]
            if len(set(identities)) != len(identities):
                raise ValueError(f'{table.name}: duplicate keys in a write batch.')
        if mode == 'insert' and not returning and not needs_client_defaults:
            _copy(connection, table, target, columns, batch)
            result.submitted += len(batch)
            result.changed += len(batch)
            continue
        if mode == 'update' and not fields:
            result.submitted += len(batch)
            continue
        if (len(batch) < 100 or needs_client_defaults) and mode != 'update':
            statement = insert(table).values(batch)
            if mode == 'ignore' or (mode == 'upsert' and not fields):
                statement = statement.on_conflict_do_nothing(index_elements=keys)
            elif mode == 'upsert':
                updates = {name: statement.excluded[name] for name in fields}
                if 'updated_at' in table.c:
                    updates['updated_at'] = func.now()
                statement = statement.on_conflict_do_update(index_elements=keys, set_=updates,
                    where=or_(*(_distinct(table.c[name], statement.excluded[name]) for name in fields)))
            if returning:
                statement = statement.returning(*(table.c[name] for name in returning))
            executed = connection.execute(statement)
        else:
            stage = quote('_bulk_' + uuid4().hex)
            names = ', '.join(map(quote, columns))
            connection.execute(text(f'CREATE TEMP TABLE {stage} ON COMMIT DROP AS SELECT {names} FROM {target} WITH NO DATA'))
            _copy(connection, table, stage, columns, batch)
            if mode == 'update':
                assignments = ', '.join(f'{quote(name)}=src.{quote(name)}' for name in fields)
                if 'updated_at' in table.c:
                    assignments += ', updated_at=CURRENT_TIMESTAMP'
                matches = ' AND '.join(f'dst.{quote(name)}=src.{quote(name)}' for name in keys)
                differences = ' OR '.join(_sql_distinct(table, name,
                    f'dst.{quote(name)}', f'src.{quote(name)}') for name in fields)
                sql = f'UPDATE {target} AS dst SET {assignments} FROM {stage} src WHERE {matches} AND ({differences})'
            else:
                sql = f'INSERT INTO {target} AS dst ({names}) SELECT {names} FROM {stage} WHERE true'
                if mode in ('ignore', 'upsert'):
                    sql += f' ON CONFLICT ({", ".join(map(quote, keys))})'
                    if mode == 'ignore' or not fields:
                        sql += ' DO NOTHING'
                    else:
                        assignments = ', '.join(f'{quote(name)}=EXCLUDED.{quote(name)}' for name in fields)
                        if 'updated_at' in table.c:
                            assignments += ', updated_at=CURRENT_TIMESTAMP'
                        differences = ' OR '.join(_sql_distinct(table, name,
                            f'dst.{quote(name)}', f'EXCLUDED.{quote(name)}') for name in fields)
                        sql += f' DO UPDATE SET {assignments} WHERE {differences}'
            if returning:
                sql += ' RETURNING ' + ', '.join(f'dst.{quote(name)}' for name in returning)
            executed = connection.execute(text(sql))
            if returning:
                returned = [tuple(row) for row in executed]
                result.returned.extend(returned)
                result.changed += len(returned)
            else:
                result.changed += executed.rowcount
            result.submitted += len(batch)
            connection.execute(text(f'DROP TABLE {stage}'))
            continue
        if returning:
            returned = [tuple(row) for row in executed]
            result.returned.extend(returned)
            result.changed += len(returned)
        else:
            result.changed += executed.rowcount
        result.submitted += len(batch)
    return result


def upsert_rows(connection, table: Table, rows: Iterable[Mapping], *, batch_size=1000) -> int:
    """Preserve the existing submitted-count contract for canonical writers."""
    return write_rows(connection, table, rows, batch_size=batch_size).submitted


def copy_rows(connection, table: Table, rows: Iterable[Mapping], *, batch_size=1000) -> int:
    return write_rows(connection, table, rows, mode='insert', batch_size=batch_size).changed
