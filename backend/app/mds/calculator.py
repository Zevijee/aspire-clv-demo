"""PDPM Calculator: what a Medicare PDPM code pays at one facility over a full
100-day stay, day by day and by component.

Priced by shared/pdpm.py, the formula the data is generated with and the PDPM
Worksheet prices its HIPPS codes with, so a code costs the same here as
anywhere else in the app. The base is the facility's Original Medicare PDPM
contract rate, which stands in for the $720 national per diem for its own
residents; each component is its share of that base times the code's CMI, PT
and OT tapered 2% a week from day 21 and NTA tripled on days 1-3.
"""
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.engine import Connection

from shared import pdpm
from shared.database.schema import facilities, facility_payer_rates as contracts, payers, portfolios, regions
from ..common.errors import ApiError

COMPONENTS = (('pt', 'PT'), ('ot', 'OT'), ('slp', 'SLP'), ('nursing', 'Nursing'), ('nta', 'NTA'),
    ('non_case_mix', 'Non-case-mix'))
# The code letter each component's CMI comes from.
LETTER = dict(pt=0, ot=0, slp=1, nursing=2, nta=3)
CENTS = Decimal('0.01')


class CalculatorQuery(BaseModel):
    facility_id: UUID
    # Four letters, PT/OT SLP nursing NTA; a five-character HIPPS code is
    # accepted and its assessment indicator ignored.
    code: str = Field(min_length=4, max_length=5)


def _facility_rows(connection: Connection, facility_id=None):
    query = (select(facilities.c.facility_id, facilities.c.facility.label('facility_name'), portfolios.c.state,
            portfolios.c.portfolio, regions.c.region, contracts.c.daily_rate.label('base_rate'))
        .select_from(facilities.join(regions).join(portfolios)
            .join(contracts, contracts.c.facility_id == facilities.c.facility_id)
            .join(payers, payers.c.payer_id == contracts.c.payer_id))
        .where(payers.c.payer_type == 'medicare', contracts.c.payment_method == 'pdpm')
        .order_by(portfolios.c.state, facilities.c.facility))
    if facility_id is not None:
        query = query.where(facilities.c.facility_id == facility_id)
    return connection.execute(query).mappings().all()


def facility_list(connection: Connection):
    """Every facility with its Original Medicare PDPM contract rate."""
    return dict(items=[dict(row, facility_id=str(row['facility_id']), base_rate=float(row['base_rate']))
        for row in _facility_rows(connection)])


def _money(value: Decimal) -> float:
    return float(value.quantize(CENTS))


def calculate(connection: Connection, query: CalculatorQuery):
    code = query.code.strip().upper()[:4]
    cmis = pdpm.cmis(code)
    if cmis is None:
        raise ApiError('invalid_code', 'A PDPM code is four letters: PT/OT A-P, SLP A-L, nursing A-Y, NTA A-F.')
    found = _facility_rows(connection, query.facility_id)
    if not found:
        raise ApiError('not_found', 'No Original Medicare PDPM contract for that facility.', 404)
    facility = found[0]
    base = Decimal(facility['base_rate'])

    def component(key: str, day: int) -> Decimal:
        """One component's pay on a day: its share of the base, times its CMI
        and its day factor -- the terms of pdpm.factor, kept apart."""
        share = base * pdpm.SHARES[key]
        if key == 'non_case_mix':
            return share
        value = share * cmis[key]
        if key in ('pt', 'ot'):
            value *= pdpm.therapy_factor(day)
        if key == 'nta':
            value *= pdpm.nta_factor(day)
        return value

    days, totals = [], {key: Decimal(0) for key, _ in COMPONENTS}
    for day in range(1, pdpm.BENEFIT_DAYS + 1):
        parts = {key: component(key, day) for key, _ in COMPONENTS}
        for key, value in parts.items():
            totals[key] += value
        days.append(dict(day=day, rate=sum(parts.values()), therapy_factor=pdpm.therapy_factor(day),
            nta_factor=pdpm.nta_factor(day)))
    total = sum(totals.values())

    # Runs of days at one rate: the NTA boost, the full-therapy baseline, then
    # each week of the taper.
    phases, cumulative = [], Decimal(0)
    for entry in days:
        key = (entry['therapy_factor'], entry['nta_factor'])
        if not phases or phases[-1]['key'] != key:
            if entry['nta_factor'] > 1:
                label = f'NTA premium ({pdpm.NTA_BOOST}×)'
            elif entry['therapy_factor'] == 1:
                label = 'Baseline'
            else:
                label = f'PT/OT taper {int((1 - entry["therapy_factor"]) * 100)}%'
            phases.append(dict(key=key, label=label, start=entry['day'], end=entry['day'], rate=entry['rate'],
                total=Decimal(0)))
        phase = phases[-1]
        phase['end'] = entry['day']
        phase['total'] += entry['rate']
    for phase in phases:
        cumulative += phase['total']
        phase['cumulative'] = cumulative

    # The NTA boost's extra over three ordinary NTA days.
    nta_day = base * pdpm.SHARES['nta'] * cmis['nta']
    premium = nta_day * (pdpm.NTA_BOOST - 1) * pdpm.NTA_BOOST_THROUGH
    return dict(
        facility=dict(facility, facility_id=str(facility['facility_id']), base_rate=float(base)),
        code=code,
        components=[dict(id=key, label=label, letter=code[LETTER[key]] if key in LETTER else None,
            base=_money(base * pdpm.SHARES[key]), cmi=float(cmis[key]) if key in cmis else None,
            # Base times CMI, before the day factors.
            adjusted=_money(base * pdpm.SHARES[key] * cmis.get(key, Decimal(1))),
            total=_money(totals[key])) for key, label in COMPONENTS],
        days=[dict(day=entry['day'], rate=_money(entry['rate']), therapy_factor=float(entry['therapy_factor']),
            nta_factor=float(entry['nta_factor'])) for entry in days],
        phases=[dict(start=phase['start'], end=phase['end'], label=phase['label'],
            days=phase['end'] - phase['start'] + 1, rate=_money(phase['rate']), total=_money(phase['total']),
            cumulative=_money(phase['cumulative'])) for phase in phases],
        total_revenue=_money(total),
        average_rate=_money(total / pdpm.BENEFIT_DAYS),
        day_one_rate=_money(days[0]['rate']),
        last_day_rate=_money(days[-1]['rate']),
        last_therapy_factor=float(days[-1]['therapy_factor']),
        nta_premium=_money(premium),
        benefit_days=pdpm.BENEFIT_DAYS,
    )
