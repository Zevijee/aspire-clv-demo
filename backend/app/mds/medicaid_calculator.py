"""Medicaid Calculator: what a Texas Medicaid case-mix code pays at one facility,
a day and over a month, by component.

Priced by shared/medicaid_pdpm.py, the rule the Medicaid Worksheet prices its
projected and final codes with, so a code costs the same here as there. The
base is the facility's State Medicaid rate; each component is its share of
that base, the nursing and NTA ones scaled by the code's CMI against the
average resident, plus the cognitive impairment add-on.
"""
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.engine import Connection

from shared import medicaid_pdpm as pricing
from shared.database.schema import facilities, facility_payer_rates as contracts, payers, portfolios, regions
from ..common.errors import ApiError
from .medicaid import STATES

BASE_PLAN = 'State Medicaid'
COMPONENTS = (('nursing', 'Nursing'), ('cognitive', 'Cognitive impairment add-on'), ('nta', 'NTA'),
    ('non_case_mix', 'Non-case-mix'))
# The code character each component reads.
LETTER = dict(nursing=0, cognitive=1, nta=2)
CENTS = Decimal('0.01')


class CalculatorQuery(BaseModel):
    facility_id: UUID
    # A letter, a digit and a letter: nursing A-Y, cognitive 0-3, NTA A-F.
    code: str = Field(min_length=3, max_length=3)


def _facility_rows(connection: Connection, facility_id=None):
    query = (select(facilities.c.facility_id, facilities.c.facility.label('facility_name'), portfolios.c.state,
            portfolios.c.portfolio, regions.c.region, contracts.c.daily_rate.label('base_rate'))
        .select_from(facilities.join(regions).join(portfolios)
            .join(contracts, contracts.c.facility_id == facilities.c.facility_id)
            .join(payers, payers.c.payer_id == contracts.c.payer_id))
        .where(portfolios.c.state.in_(STATES), payers.c.payer_name == BASE_PLAN)
        .order_by(portfolios.c.state, facilities.c.facility))
    if facility_id is not None:
        query = query.where(facilities.c.facility_id == facility_id)
    return connection.execute(query).mappings().all()


def facility_list(connection: Connection):
    """Every Texas facility with its State Medicaid rate, the base a code scales."""
    return dict(items=[dict(row, facility_id=str(row['facility_id']), base_rate=float(row['base_rate']))
        for row in _facility_rows(connection)])


def _money(value: Decimal) -> float:
    return float(value.quantize(CENTS))


def calculate(connection: Connection, query: CalculatorQuery):
    code = query.code.strip().upper()
    parts = pricing.parts(code)
    if parts is None:
        raise ApiError('invalid_code', 'A Texas Medicaid code is a letter, a digit and a letter: nursing A-Y, '
            'cognitive impairment 0-3, NTA A-F.')
    found = _facility_rows(connection, query.facility_id)
    if not found:
        raise ApiError('not_found', 'No State Medicaid rate for that facility, or it is not in Texas.', 404)
    facility = found[0]
    base = Decimal(facility['base_rate'])

    def component(key: str) -> dict:
        if key == 'non_case_mix':
            return dict(base=base * pricing.SHARES[key], cmi=None, adjusted=base * pricing.SHARES[key])
        if key == 'cognitive':
            return dict(base=base, cmi=float(parts['cognitive']), adjusted=base * parts['cognitive'])
        share = base * pricing.SHARES[key]
        return dict(base=share, cmi=float(parts[key]), adjusted=share * parts[key] / pricing.AVERAGE_CMI[key])

    components = {key: component(key) for key, _ in COMPONENTS}
    rate = sum(item['adjusted'] for item in components.values())
    return dict(
        facility=dict(facility, facility_id=str(facility['facility_id']), base_rate=float(base)),
        code=code,
        components=[dict(id=key, label=label, letter=code[LETTER[key]] if key in LETTER else None,
            base=_money(components[key]['base']), cmi=components[key]['cmi'],
            adjusted=_money(components[key]['adjusted'])) for key, label in COMPONENTS],
        cognitive_level=pricing.COGNITIVE_LABELS[code[1]],
        daily_rate=_money(rate),
        neutral_rate=_money(base),
        stay_days=pricing.STAY_DAYS,
        total_revenue=_money(rate * pricing.STAY_DAYS),
    )
