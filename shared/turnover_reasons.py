"""Why employees leave: the roster's termination reasons, shared by the roster
generator that draws them, the schema that checks them and the API that names
them in Turnover and Retention.

Each reason is (code, label, voluntary, weight). The weights are each reason's
share of departures before tenure: retirement grows with the years worked
(RETIREMENT_PER_YEAR), so it is rare among new hires and common among the
longest-serving, and the other weights share the rest. Roughly two thirds of
leavers quit and a third are let go or walk out, the usual split in skilled
nursing.
"""

TERMINATION_REASONS = (
    ('better_pay', 'Resigned: better pay elsewhere', True, 0.24),
    ('schedule', 'Resigned: schedule or burnout', True, 0.16),
    ('personal', 'Resigned: personal or family', True, 0.12),
    ('relocated', 'Relocated', True, 0.07),
    ('school', 'Returned to school', True, 0.05),
    ('retired', 'Retired', True, 0.02),
    ('job_abandonment', 'Job abandonment (no call, no show)', False, 0.10),
    ('attendance', 'Terminated: attendance', False, 0.11),
    ('performance', 'Terminated: performance', False, 0.09),
    ('policy', 'Terminated: policy violation', False, 0.04),
)
REASON_CODES = tuple(code for code, *_ in TERMINATION_REASONS)
REASON_LABELS = {code: label for code, label, *_ in TERMINATION_REASONS}
VOLUNTARY = {code: voluntary for code, _label, voluntary, _weight in TERMINATION_REASONS}
# Retirement's added weight for each year worked, up to RETIREMENT_MAX.
RETIREMENT_PER_YEAR = 0.025
RETIREMENT_MAX = 0.6
