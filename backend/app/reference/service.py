"""Queries reusable by routes and other services without internal HTTP calls."""
from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from shared.database.schema import facilities, payers, portfolios, regions
from ..common.locations import facility_locations
from ..common.tables import paginate
from .schemas import LocationQuery, PayerQuery


def locations(connection: Connection, query: LocationQuery):
    statement = facility_locations(query)
    total = connection.scalar(select(func.count()).select_from(statement.subquery()))
    statement = paginate(statement, query, columns={
        'state': portfolios.c.state, 'portfolio_name': portfolios.c.portfolio,
        'region_name': regions.c.region, 'facility_name': facilities.c.facility, 'beds': facilities.c.beds,
    }, default_sort='facility_name', unique_key=facilities.c.facility_id)
    return dict(items=connection.execute(statement).mappings().all(),
        total=total, limit=query.limit, offset=query.offset)


def payer_catalog(connection: Connection, query: PayerQuery):
    statement = select(payers)
    if query.payer_types:
        statement = statement.where(payers.c.payer_type.in_(query.payer_types))
    if query.is_skilled is not None:
        statement = statement.where(payers.c.is_skilled == query.is_skilled)
    if query.search.strip():
        statement = statement.where(payers.c.payer_name.icontains(query.search.strip(), autoescape=True))
    total = connection.scalar(select(func.count()).select_from(statement.subquery()))
    statement = paginate(statement, query, columns={
        'payer_name': payers.c.payer_name, 'payer_type': payers.c.payer_type,
        'is_skilled': payers.c.is_skilled,
    }, default_sort='payer_name', unique_key=payers.c.payer_id)
    return dict(items=connection.execute(statement).mappings().all(),
        total=total, limit=query.limit, offset=query.offset)
