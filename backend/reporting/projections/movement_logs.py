"""One sortable stream of admission, discharge, and payer-change events."""

from sqlalchemy import Integer, case, cast, func, literal, select, union_all

from data.models.admissions import admissions
from data.models.discharges import discharges
from data.models.payer_changes import payer_changes


def payer_name(column):
    return case((column == 'Medicare Advantage', 'Commercial Medicare'), else_=column)


movement_logs = union_all(
    select(
        func.concat('admission:', admissions.c.admission_id).label('move_id'),
        admissions.c.facility_code, admissions.c.resident_name,
        literal('Admission').label('move_type'), admissions.c.admission_date.label('move_date'),
        func.concat('From ', admissions.c.admission_source_name, ' (',
                    admissions.c.admission_source_type, ') · ', payer_name(admissions.c.payer_type),
                    ' — ', admissions.c.payer_name).label('description'),
        cast(literal(None), Integer).label('los_days'),
    ),
    select(
        func.concat('discharge:', discharges.c.discharge_id),
        discharges.c.facility_code, discharges.c.resident_name,
        literal('Discharge'), discharges.c.discharge_date,
        func.concat(discharges.c.discharge_type, ' · To ', discharges.c.destination_name,
                    ' (', discharges.c.destination_type, ') · ', payer_name(discharges.c.payer_type),
                    ' — ', discharges.c.payer_name),
        discharges.c.los_days,
    ),
    select(
        func.concat('payer-change:', payer_changes.c.change_id),
        payer_changes.c.facility_code, payer_changes.c.resident_name,
        literal('Payer change'), payer_changes.c.effective_date,
        func.concat('Changed from ', payer_name(payer_changes.c.previous_payer_type),
                    ' (', payer_changes.c.previous_payer_name, ') to ',
                    payer_name(payer_changes.c.new_payer_type), ' (', payer_changes.c.new_payer_name,
                    ')', case((payer_changes.c.change_category == 'Plan only', ' · Plan only'), else_='')),
        payer_changes.c.effective_date - payer_changes.c.previous_payer_start_date,
    ),
).subquery('movement_logs')
