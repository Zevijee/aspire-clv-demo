"""Versioned synthetic arrival parameters; never imported by the API."""
GENERATOR_VERSION = "admissions-independent-v5"
RANDOM_VERSION = "admissions-daily-v1"
MIN_ADMISSIONS_PER_FACILITY = 220
MAX_ADMISSIONS_PER_FACILITY = 3_300
READMISSION_RATE = 0.12

PAYER_NAMES = {
    "Medicare": ("Traditional Medicare",),
    "Medicare Advantage": ("Apex Commercial Medicare", "Northstar Senior Health", "Summit Medicare"),
    "Medicare HMO": ("Harbor Medicare HMO", "Summit Medicare HMO"),
    "Managed Medicaid": ("Evergreen Health Plan", "Cedar State Health", "Horizon Community Care"),
    "Medicaid": ("State Medicaid Program",),
    "Hospice": ("Harborlight Hospice", "Willow Path Hospice"),
    "Private Pay": ("Private Pay",),
}

PAYER_TYPE_WEIGHTS = (
    ("Medicare", 22),
    ("Medicare Advantage", 18),
    ("Medicare HMO", 10),
    ("Managed Medicaid", 25),
    ("Medicaid", 14),
    ("Hospice", 4),
    ("Private Pay", 7),
)

FIRST_NAMES = (
    "Avery",
    "Blair",
    "Cameron",
    "Drew",
    "Elliot",
    "Francis",
    "Gray",
    "Harper",
    "Jordan",
    "Kendall",
    "Lane",
    "Morgan",
    "Parker",
    "Quinn",
    "Reese",
    "Rowan",
    "Shawn",
    "Taylor",
    "Valerie",
    "Wesley",
)

LAST_NAMES = (
    "Bennett",
    "Carlisle",
    "Dalton",
    "Ellison",
    "Foster",
    "Granger",
    "Hollis",
    "Ingram",
    "Jamison",
    "Keller",
    "Langley",
    "Monroe",
    "Nolan",
    "Prescott",
    "Ramsey",
    "Sawyer",
    "Tolland",
    "Vaughn",
    "Whitaker",
    "York",
)

