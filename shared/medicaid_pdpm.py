"""What a Texas Medicaid case-mix code pays, shared by the Medicaid Worksheet
and the Medicaid Calculator so a code costs the same on both.

A Texas Medicaid code is a nursing letter (A-Y), a cognitive impairment digit
(0 intact to 3 severe) and an NTA letter (A-F). The base is the facility's
rate on the stay's Medicaid plan. A day's rate is the base split into shares,
the case-mix ones scaled by the code's CMI against the average resident, so a
resident at the average pays the base, plus a cognitive add-on:

    non-case-mix share            0.30
    nursing share  x nursing CMI  0.55 x CMI / 1.50
    NTA share      x NTA CMI      0.15 x CMI / 1.20
    cognitive add-on              0, 3, 6 or 10% of the base

The CMIs are the PDPM nursing and NTA ones (shared/pdpm.py). There are no day
factors: a Medicaid day is the same rate from the first to the last, so a
stay's revenue is the rate times its days. The shares, the averages and the
add-on are demo values: Texas's own rule is not modelled here, only its shape.
"""
from decimal import Decimal

from shared.pdpm import NTA_CMI, NURSING_CMI

SHARES = {'nursing': Decimal('0.55'), 'nta': Decimal('0.15'), 'non_case_mix': Decimal('0.30')}
# The average resident's CMIs, which the shares are set against.
AVERAGE_CMI = {'nursing': Decimal('1.50'), 'nta': Decimal('1.20')}
# The cognitive impairment add-on, as a share of the base, by the code's digit.
COGNITIVE_ADD_ON = {'0': Decimal('0'), '1': Decimal('0.03'), '2': Decimal('0.06'), '3': Decimal('0.10')}
COGNITIVE_LABELS = {'0': 'Intact', '1': 'Mild', '2': 'Moderate', '3': 'Severe'}
# The stay the worksheet and calculator price a code over: a month.
STAY_DAYS = 30
CENTS = Decimal('0.01')


def parts(code: str) -> dict | None:
    """The code's nursing CMI, cognitive add-on and NTA CMI, or None when it is
    not a Texas Medicaid code."""
    code = (code or '').strip().upper()
    if len(code) != 3 or code[0] not in NURSING_CMI or code[1] not in COGNITIVE_ADD_ON or code[2] not in NTA_CMI:
        return None
    return dict(nursing=Decimal(str(NURSING_CMI[code[0]])), cognitive=COGNITIVE_ADD_ON[code[1]],
        nta=Decimal(str(NTA_CMI[code[2]])))


def factor(code_parts: dict | None) -> Decimal:
    """A day's rate as a multiple of the base: 1.0 for the average resident with
    no cognitive add-on (None)."""
    if code_parts is None:
        return Decimal(1)
    return (SHARES['non_case_mix'] + SHARES['nursing'] * code_parts['nursing'] / AVERAGE_CMI['nursing']
        + SHARES['nta'] * code_parts['nta'] / AVERAGE_CMI['nta'] + code_parts['cognitive'])


def daily_rate(code: str, base: Decimal) -> Decimal | None:
    code_parts = parts(code)
    return None if code_parts is None else (base * factor(code_parts)).quantize(CENTS)


def stay(code: str, base: Decimal, days: int = STAY_DAYS) -> dict | None:
    """A code's rates over a stay of `days` days at `base`: the daily rate, the
    base as the neutral rate, and the revenue. None for an invalid code. The
    same shape as shared.pdpm.stay, which the Medicare worksheet shows."""
    rate = daily_rate(code, base)
    if rate is None:
        return None
    return dict(total_revenue=(rate * days).quantize(CENTS), average_rate=rate,
        neutral_rate=Decimal(base).quantize(CENTS), days=days)
