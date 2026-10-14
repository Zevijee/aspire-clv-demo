"""The staffing roles HPPD is measured for, shared by the generator and the API.

HPPD is hours worked per patient day: a role's hours over a period divided by
the census days in it, each day's closing census summed. Every role divides by
the same total census days, office roles included, so one rule holds for every
row and any set of roles adds up: Direct Care HPPD is its six positions' hours
over census days.

Targets are company-wide hours per patient day, one per role. They are demo
values, plausible for a skilled nursing building, not a regulatory minimum.
The generator stores each day's target hours (target x that day's census), so a
report reads targets as a sum like any other measure and never needs this file;
targets that differ by facility would change only the generator.

Base rates are the hourly wage before the state and facility adjustments the
generator applies, in dollars.
"""

# (code, label, department, role group, target HPPD, base hourly rate), in the
# order reports list them: department, then role group, then position, as the
# operator's daily labor report lays them out. A role group with one position
# shares its name (RN is the group and the position).
ROLES = (
    ('administrator', 'Administrator', 'Admin & General', 'Administrator', 0.07, 60.00),
    ('business_office_manager', 'Business Office Manager', 'Admin & General', 'BOM', 0.07, 30.00),
    ('hr_payroll', 'HR/Payroll', 'Admin & General', 'HR', 0.07, 26.00),
    ('rn', 'RN', 'Direct Care', 'RN', 0.60, 44.00),
    ('lpn', 'LPN', 'Direct Care', 'LPN', 0.75, 31.00),
    ('lpn_supervisor', 'LPN Supervisor', 'Direct Care', 'LPN', 0.15, 35.00),
    ('lpn_wound_nurse', 'LPN Wound Nurse', 'Direct Care', 'LPN', 0.07, 34.00),
    ('cna', 'CNA', 'Direct Care', 'CNA', 2.20, 19.50),
    # Non-certified nursing assistant: a nurse aide not yet certified, working under the CNAs.
    ('ncna', 'NCNA', 'Direct Care', 'CNA', 0.15, 16.50),
    ('cma', 'CMA', 'Direct Care', 'CMA', 0.25, 21.00),
    ('cook', 'Cook', 'Non-Nursing', 'Dietary', 0.30, 18.00),
    ('dietary_aide', 'Dietary Aide', 'Non-Nursing', 'Dietary', 0.45, 15.50),
    ('dietary_manager', 'Dietary Manager', 'Non-Nursing', 'Dietary', 0.07, 26.00),
    ('dietician', 'Dietician', 'Non-Nursing', 'Dietary', 0.03, 34.00),
    ('housekeeper', 'Housekeeper', 'Non-Nursing', 'Housekeeping & Laundry', 0.40, 15.50),
    ('housekeeping_director', 'Housekeeping Director', 'Non-Nursing', 'Housekeeping & Laundry', 0.07, 24.00),
    ('laundry_aide', 'Laundry Aide', 'Non-Nursing', 'Housekeeping & Laundry', 0.15, 15.00),
    ('maintenance_director', 'Maintenance Director', 'Non-Nursing', 'Maintenance', 0.07, 28.00),
    ('social_services_director', 'Social Services Director', 'Non-Nursing', 'Social Work', 0.07, 30.00),
    ('transportation_driver', 'Transportation/Driver', 'Non-Nursing', 'Transportation', 0.07, 17.00),
    ('adon_lpn', 'ADON LPN', 'Nursing Admin', 'ADON', 0.07, 38.00),
    ('mds_rn', 'MDS RN', 'Nursing Admin', 'MDS', 0.07, 45.00),
    ('staffing_coordinator', 'Certified Staffing Coordinator (CNA)', 'Nursing Admin', 'Staffing', 0.07, 23.00),
)
ROLE_CODES = tuple(code for code, *_ in ROLES)
DEPARTMENTS = ('Admin & General', 'Direct Care', 'Non-Nursing', 'Nursing Admin')
# Salaried office departments: they work weekdays and never use agency staff.
OFFICE_DEPARTMENTS = ('Admin & General', 'Nursing Admin')

# How a staff member is employed, and how often each kind works: the share of
# days a member of the roster is drawn to work. Full time comes to five days
# a week, part time three, PRN about one, and agency staff are called in rarely.
EMPLOYMENT_TYPES = (
    ('full_time', 'Full time', 0.71),
    ('part_time', 'Part time', 0.43),
    ('prn', 'PRN', 0.15),
    ('agency', 'Agency', 0.10),
)
EMPLOYMENT_CODES = tuple(code for code, *_ in EMPLOYMENT_TYPES)
# How many days of per-person hours daily_staff_hours keeps, ending on the
# latest staffing day. The generator drops older days; the API clamps to it.
STAFF_HOURS_DAYS = 120
# Hours in a week (Monday to Sunday) beyond which a person's hours are
# overtime. The generator stores each day's share of it on daily_staff_hours;
# the Employees tab and the Overtime report use the same line.
WEEKLY_HOURS = 40
