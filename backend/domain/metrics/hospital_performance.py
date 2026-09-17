"""The referring-hospital report's monthly comparison contract.

The input contains 36 complete chronological months. Recent performance uses
the last three; the baseline uses the preceding 24. These periods belong to
this report and are not global defaults for other performance reports.
"""

from collections.abc import Sequence


def monthly_comparisons(
    complete_months: Sequence[int],
    current_month_admissions: int,
    current_month_days: int,
) -> dict[str, int | float | None]:
    recent = sum(complete_months[-3:]) / 3
    previous = sum(complete_months[-6:-3]) / 3
    historical = sum(complete_months) / 36
    usual = sum(complete_months[-27:-3]) / 24
    return {
        "usual_average": usual,
        "difference": recent - usual,
        "difference_percent": (recent - usual) / usual * 100 if usual else None,
        "current_month_average_per_day": current_month_admissions / current_month_days,
        "previous_month_admissions": complete_months[-1],
        "six_month_average": sum(complete_months[-6:]) / 6,
        "year_average": sum(complete_months[-12:]) / 12,
        "recent_average": recent,
        "previous_average": previous,
        "change_percent": (recent - previous) / previous * 100 if previous else None,
        "historical_average": historical,
        "change_vs_average": recent - historical,
    }
