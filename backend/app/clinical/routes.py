from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from ..common.errors import ApiError, ErrorResponse
from ..common.tables import Page
from ..database import DbConnection
from . import hospital_transfers, incident_log, incidents, logs

router = APIRouter(prefix='/clinical', tags=['Clinical'])


@router.get('/hospital-transfers', response_model=hospital_transfers.HospitalTransfers,
    responses={409: {'model': ErrorResponse}})
def hospital_transfers_report(connection: DbConnection,
        query: Annotated[hospital_transfers.TransfersQuery, Query()]):
    """Every facility's hospital transfers in the range: how many, how many within
    30 days of admission, their summed days since admission, the rehospitalizations
    among them, the resident days the rate per 1,000 divides by, the prior period's
    count, and the counts by payer and reason. payer_types and reasons filter it."""
    return hospital_transfers.hospital_transfers(connection, query)


@router.get('/hospital-transfers/daily', response_model=hospital_transfers.DailyTransfers,
    responses={409: {'model': ErrorResponse}})
def hospital_transfers_daily(connection: DbConnection,
        query: Annotated[hospital_transfers.DailyTransfersQuery, Query()]):
    """Each day's hospital transfers, with the report's filters, over the given
    facilities or all of them, for the daily trend."""
    return hospital_transfers.daily(connection, query)


@router.get('/hospital-transfers/logs', response_model=Page[logs.Transfer])
def hospital_transfer_logs(connection: DbConnection, query: Annotated[logs.LogsQuery, Query()]):
    """One row per hospital transfer in the range: the Logs tab."""
    return logs.page(connection, query)


@router.get('/hospital-transfers/logs/filter-options')
def hospital_transfer_log_options(connection: DbConnection, query: Annotated[logs.FilterQuery, Query()]):
    return logs.options(connection, query)


@router.get('/hospital-transfers/logs/export')
def hospital_transfer_log_export(request: Request, query: Annotated[logs.LogsQuery, Query()]):
    # Validate the sort before response headers are sent; the stream owns its DB
    # connection so dependency cleanup cannot close it mid-download.
    if query.sort is not None and query.sort not in logs.columns:
        raise ApiError('invalid_sort', 'Unsupported sort column.')
    return StreamingResponse(logs.csv_chunks(request.app.state.database, query), media_type='text/csv',
        headers={'Content-Disposition':
            f'attachment; filename="hospital-transfers-{query.start_date}-to-{query.end_date}.csv"'})


@router.get('/incidents', response_model=incidents.IncidentsReport, responses={409: {'model': ErrorResponse}})
def incidents_report(connection: DbConnection, query: Annotated[incidents.IncidentsQuery, Query()]):
    """Every facility's incidents in the range: how many, how many resulted in a
    hospitalization, those still open, by time of day, the resident days the rate
    per 1,000 divides by, and the counts by type and severity. payer_types,
    incident_types and severities filter it."""
    return incidents.incidents_report(connection, query)


@router.get('/incidents/daily', response_model=incidents.DailyIncidents, responses={409: {'model': ErrorResponse}})
def incidents_daily(connection: DbConnection, query: Annotated[incidents.DailyIncidentsQuery, Query()]):
    """Each day's incidents, with the report's filters, over the given facilities
    or all of them, for the daily trend."""
    return incidents.daily(connection, query)


@router.get('/incidents/logs', response_model=Page[incident_log.Incident])
def incident_logs_page(connection: DbConnection, query: Annotated[incident_log.LogsQuery, Query()]):
    """One row per incident in the range: the Logs tab."""
    return incident_log.page(connection, query)


@router.get('/incidents/logs/filter-options')
def incident_log_options(connection: DbConnection, query: Annotated[incident_log.FilterQuery, Query()]):
    return incident_log.options(connection, query)


@router.get('/incidents/logs/export')
def incident_log_export(request: Request, query: Annotated[incident_log.LogsQuery, Query()]):
    # Validate the sort before response headers are sent; the stream owns its DB
    # connection so dependency cleanup cannot close it mid-download.
    if query.sort is not None and query.sort not in incident_log.COLUMN_NAMES:
        raise ApiError('invalid_sort', 'Unsupported sort column.')
    return StreamingResponse(incident_log.csv_chunks(request.app.state.database, query), media_type='text/csv',
        headers={'Content-Disposition': f'attachment; filename="incidents-{query.start_date}-to-{query.end_date}.csv"'})
