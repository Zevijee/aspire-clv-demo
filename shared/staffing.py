"""The staffing roles PPD is measured for, shared by the generator and the API.

PPD is hours worked per patient day: a role's hours over a period divided by the
census days in it, each day's closing census summed. Every role divides by the
same total census days, therapy included, so one rule holds for every row and
any set of roles adds up: nursing PPD is RN + LPN + CNA hours over census days.

Targets are company-wide hours per patient day, one per role. They are demo
values, plausible for a skilled nursing building, not a regulatory minimum.
The generator stores each day's target hours (target x that day's census), so a
report reads targets as a sum like any other measure and never needs this file;
targets that differ by facility would change only the generator.

Base rates are the hourly wage before the state and facility adjustments the
generator applies, in dollars.
"""

# (code, label, group, target PPD, base hourly rate), in the order reports list them.
ROLES = (
    ('rn', 'RN', 'Nursing', 0.75, 44.00),
    ('lpn', 'LPN', 'Nursing', 0.85, 31.00),
    ('cna', 'CNA', 'Nursing', 2.30, 19.50),
    ('pt', 'PT', 'Therapy', 0.20, 52.00),
    ('pta', 'PTA', 'Therapy', 0.18, 35.00),
    ('ot', 'OT', 'Therapy', 0.18, 50.00),
    ('cota', 'COTA', 'Therapy', 0.15, 34.00),
    ('slp', 'SLP', 'Therapy', 0.06, 51.00),
    ('dietary_aide', 'Dietary Aide', 'Support', 0.55, 15.50),
    ('cook', 'Cook', 'Support', 0.30, 18.00),
    ('evs', 'EVS', 'Support', 0.45, 15.75),
)
ROLE_CODES = tuple(code for code, *_ in ROLES)
GROUPS = ('Nursing', 'Therapy', 'Support')
