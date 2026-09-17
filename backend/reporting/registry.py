"""Reporting ownership and dependencies, independent of source generators."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Dataset:
    name: str
    dependencies: tuple[str, ...] = ()
    # An absent dependency entry means every changed field can affect this node.
    fields: dict[str, frozenset[str]] = field(default_factory=dict)


REPORTS = {
    "daily_activity": Dataset("daily_activity", ("admissions", "coverage", "stays"), {
        "admissions": frozenset({"admission_date", "facility_code", "payer_type",
            "admission_source_type", "admission_source_name", "is_readmission",
            "readmission_days_since_prior"}),
    }),
    "daily_census": Dataset("daily_census", ("admissions", "discharges", "stays", "facilities"), {
        "admissions": frozenset({"admission_date", "facility_code"}),
        "discharges": frozenset({"start_date", "discharge_date", "facility_code"}),
        "stays": frozenset({"start_date", "end_date", "facility_code"}),
        "facilities": frozenset({"facility_code"}),
    }),
    "monthly_activity": Dataset("monthly_activity", ("daily_census",)),
    "payer_census": Dataset("payer_census", ("daily_census", "admissions", "discharges", "payer_changes", "coverage", "stays"), {
        "admissions": frozenset({"admission_date", "facility_code", "payer_type"}),
        "discharges": frozenset({"start_date", "discharge_date", "facility_code", "payer_type"}),
    }),
    "referring_hospitals": Dataset("referring_hospitals", ("admissions", "hospitals", "coverage", "stays"), {
        "admissions": frozenset({"admission_date", "facility_code", "payer_type",
            "admission_source_type", "admission_source_name", "is_readmission",
            "readmission_days_since_prior"}),
        "hospitals": frozenset({"hospital"}),
    }),
    "report_results": Dataset("report_results", (
        "daily_activity", "daily_census", "monthly_activity", "payer_census", "referring_hospitals",
        "admissions", "discharges", "payer_changes", "bed_holds", "facilities",
        "hospitals", "residents", "payers", "payer_types", "coverage", "stays",
    )),
}

SOURCE_ALIASES = {
    "census_stays": "stays", "resident_stays": "stays",
    "payer_stays": "coverage", "payer_intervals": "coverage",
    "bed_assignments": "bed_holds", "bed_reservations": "bed_holds",
    "referring_hospital_identities": "hospitals",
}
