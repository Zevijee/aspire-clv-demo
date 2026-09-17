"""Synthetic coverage distributions, independent of reference definitions."""
# Demo distributions only; these are not clinical or reimbursement predictions.
DESTINATIONS = {
    "Medicare": {
        "Medicaid": 40,
        "Managed Medicaid": 20,
        "Private Pay": 25,
        "Hospice": 10,
        "Medicare Advantage": 5,
        "Medicare HMO": 5,
    },
    "Medicare HMO": {"Medicaid": 35, "Managed Medicaid": 30, "Private Pay": 20, "Medicare": 10, "Hospice": 5},
    "Medicare Advantage": {
        "Medicaid": 35,
        "Managed Medicaid": 30,
        "Private Pay": 20,
        "Medicare": 10,
        "Hospice": 5,
    },
    "Medicaid": {"Managed Medicaid": 65, "Hospice": 20, "Medicare": 10, "Private Pay": 5},
    "Managed Medicaid": {"Medicaid": 65, "Hospice": 20, "Medicare": 10, "Private Pay": 5},
    "Private Pay": {
        "Medicaid": 50,
        "Managed Medicaid": 25,
        "Medicare": 10,
        "Medicare Advantage": 5,
        "Medicare HMO": 5,
        "Hospice": 10,
    },
    "Hospice": {"Medicaid": 40, "Managed Medicaid": 30, "Private Pay": 20, "Medicare": 10},
}

