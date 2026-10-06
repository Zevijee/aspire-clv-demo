"""The PDPM per diem from a PDPM code, shared by the generator and the API.

The generator prices every PDPM-paid day with it and the PDPM Worksheet prices
projected and final HIPPS codes with it, so a code's rate is the same wherever
it is shown.

A day's PDPM per diem is the sum of five case-mix components and one that is
not case-mix adjusted:

    PT  + OT   base share x the code's PT/OT-letter CMI x therapy day factor
    SLP        base share x the SLP-letter CMI
    Nursing    base share x the nursing-letter CMI
    NTA        base share x the NTA-letter CMI x NTA day factor
    Non-case-mix base share

The therapy day factor (the variable per diem adjustment) is 1.0 for days 1-20
and falls 2% each week from day 21; the NTA factor is 3.0 on days 1-3 and 1.0
after. With every CMI at 1.0 the per diem is the case-mix-neutral rate.

Base: the shares split the $720 national per diem in the proportions of the
CMS urban unadjusted component rates, and a facility's PDPM contract rate
replaces the $720 for its own residents. The CMIs are CMS PDPM values as
recalled for the demo, not read from a CMS table; check them against the
current CMS release before relying on any figure.
"""
from decimal import Decimal

NATIONAL_PER_DIEM = Decimal(720)
# Each component's share of the per diem, from the CMS urban unadjusted rates
# (PT 70.52, OT 65.66, SLP 26.35, nursing 122.92, NTA 92.74, non-case-mix 109.64).
SHARES = {'pt': Decimal('0.1446'), 'ot': Decimal('0.1346'), 'slp': Decimal('0.0540'),
    'nursing': Decimal('0.2520'), 'nta': Decimal('0.1901'), 'non_case_mix': Decimal('0.2247')}
# Case-mix index by HIPPS letter: PT/OT A-P, SLP A-L, nursing A-Y, NTA A-F.
PT_CMI = dict(zip('ABCDEFGHIJKLMNOP', (1.53, 1.69, 1.88, 1.92, 1.42, 1.61, 1.67, 1.16,
    1.13, 1.42, 1.52, 1.09, 1.27, 1.48, 1.55, 1.08)))
OT_CMI = dict(zip('ABCDEFGHIJKLMNOP', (1.49, 1.63, 1.68, 1.53, 1.47, 1.64, 1.60, 1.20,
    1.16, 1.40, 1.45, 1.09, 1.30, 1.53, 1.51, 1.10)))
SLP_CMI = dict(zip('ABCDEFGHIJKL', (0.68, 1.82, 2.66, 1.46, 2.33, 2.97, 2.04, 2.85, 3.51, 2.98, 3.69, 4.19)))
NURSING_CMI = dict(zip('ABCDEFGHIJKLMNOPQRSTUVWXY', (4.04, 3.06, 2.91, 2.39, 1.99, 2.23, 1.85, 2.07,
    1.72, 1.71, 1.43, 1.86, 1.62, 1.54, 1.08, 1.34, 0.94, 1.04, 0.99, 1.57, 1.47, 1.21, 0.70, 1.13, 0.66)))
NTA_CMI = dict(zip('ABCDEF', (3.24, 2.53, 1.84, 1.33, 0.96, 0.72)))
# The variable per diem adjustment.
THERAPY_FULL_THROUGH, THERAPY_STEP_DAYS, THERAPY_STEP = 20, 7, Decimal('0.02')
NTA_BOOST_THROUGH, NTA_BOOST = 3, Decimal(3)
# The Medicare SNF benefit: the stay a 100-day total covers.
BENEFIT_DAYS = 100


def therapy_factor(day: int) -> Decimal:
    if day <= THERAPY_FULL_THROUGH:
        return Decimal(1)
    return 1 - THERAPY_STEP * ((day - THERAPY_FULL_THROUGH - 1) // THERAPY_STEP_DAYS + 1)


def nta_factor(day: int) -> Decimal:
    return NTA_BOOST if day <= NTA_BOOST_THROUGH else Decimal(1)


def cmis(code: str) -> dict[str, Decimal] | None:
    """Each component's CMI for a PDPM code (its first four letters), or None
    if the code is not a valid one."""
    code = (code or '').upper()
    if len(code) < 4:
        return None
    try:
        return dict(pt=Decimal(str(PT_CMI[code[0]])), ot=Decimal(str(OT_CMI[code[0]])),
            slp=Decimal(str(SLP_CMI[code[1]])), nursing=Decimal(str(NURSING_CMI[code[2]])),
            nta=Decimal(str(NTA_CMI[code[3]])))
    except KeyError:
        return None


def factor(code_cmis: dict[str, Decimal] | None, day: int) -> Decimal:
    """The day's per diem as a multiple of the base: the code's CMIs, or all
    1.0 for the case-mix-neutral factor (None)."""
    c = code_cmis or dict(pt=1, ot=1, slp=1, nursing=1, nta=1)
    return (SHARES['non_case_mix'] + SHARES['slp'] * c['slp'] + SHARES['nursing'] * c['nursing']
        + (SHARES['pt'] * c['pt'] + SHARES['ot'] * c['ot']) * therapy_factor(day)
        + SHARES['nta'] * c['nta'] * nta_factor(day))


def stay(code: str, base: Decimal, days: int = BENEFIT_DAYS) -> dict | None:
    """A code's rates over a stay of `days` days: total revenue at `base`, the
    average daily rate, and the case-mix-neutral average at the national $720.
    None for an invalid code."""
    code_cmis = cmis(code)
    if code_cmis is None:
        return None
    total = sum(base * factor(code_cmis, day) for day in range(1, days + 1))
    neutral = sum(NATIONAL_PER_DIEM * factor(None, day) for day in range(1, days + 1)) / days
    return dict(total_revenue=round(total, 2), average_rate=round(total / days, 2), neutral_rate=round(neutral, 2))


def factor_sql(code: str, day: str) -> str:
    """factor() as a SQL expression over a code column and a day expression,
    for the generator's set-based pricing."""
    def lookup(letter, table):
        return 'CASE ' + letter + ' ' + ' '.join(f"WHEN '{key}' THEN {value}" for key, value in table.items()) + ' END'
    pt, slp, nur, nta = (f'substr({code}, {position}, 1)' for position in (1, 2, 3, 4))
    therapy = (f'(CASE WHEN {day} <= {THERAPY_FULL_THROUGH} THEN 1 ELSE 1 - {THERAPY_STEP} * '
        f'(({day} - {THERAPY_FULL_THROUGH} - 1) / {THERAPY_STEP_DAYS} + 1) END)')
    boost = f'(CASE WHEN {day} <= {NTA_BOOST_THROUGH} THEN {NTA_BOOST} ELSE 1 END)'
    return (f"({SHARES['non_case_mix']} + {SHARES['slp']} * {lookup(slp, SLP_CMI)}"
        f" + {SHARES['nursing']} * {lookup(nur, NURSING_CMI)}"
        f" + ({SHARES['pt']} * {lookup(pt, PT_CMI)} + {SHARES['ot']} * {lookup(pt, OT_CMI)}) * {therapy}"
        f" + {SHARES['nta']} * {lookup(nta, NTA_CMI)} * {boost})")


def neutral_factor_sql(day: str) -> str:
    """The case-mix-neutral factor as SQL: every CMI at 1.0."""
    therapy = (f'(CASE WHEN {day} <= {THERAPY_FULL_THROUGH} THEN 1 ELSE 1 - {THERAPY_STEP} * '
        f'(({day} - {THERAPY_FULL_THROUGH} - 1) / {THERAPY_STEP_DAYS} + 1) END)')
    boost = f'(CASE WHEN {day} <= {NTA_BOOST_THROUGH} THEN {NTA_BOOST} ELSE 1 END)'
    return (f"({SHARES['non_case_mix'] + SHARES['slp'] + SHARES['nursing']}"
        f" + {SHARES['pt'] + SHARES['ot']} * {therapy} + {SHARES['nta']} * {boost})")
