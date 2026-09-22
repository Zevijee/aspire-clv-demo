"""The one definition of a census-changing payer movement.

Both the daily and the monthly census generators build the same balances at
different grains. They compute them independently -- the monthly table would
otherwise have to wait for the daily rebuild -- so the rules themselves live
here. Change them once and both tables change together.
"""

# Pairs each payer period with its neighbours in the same stay, then turns the
# start and end of every period into a movement. Feeds a CTE chain, so callers
# append their own SELECT over `moved`.
#
#   admissions   a period that opens the stay
#   discharges   a period that closes it
#   changes_in   a move from a different payer TYPE into this one
#   changes_out  a move out of this type into a different one
#
# A plan change inside one payer type is neither in nor out: the resident never
# left the type, so counting it would inflate both sides and cancel to nothing.
MOVEMENTS_CTE = """
period AS (
    SELECT ps.start_date, ps.end_date, ps.start_reason, ps.end_reason,
           s.facility_id, p.payer_type,
           lag(p.payer_type) OVER w AS previous_type,
           lead(p.payer_type) OVER w AS next_type
    FROM res_payer_stays ps
    JOIN res_stays s ON s.stay_id = ps.stay_id
    JOIN payers p ON p.payer_id = ps.payer_id
    WINDOW w AS (PARTITION BY ps.stay_id ORDER BY ps.period_number)
), moved AS (
    SELECT start_date AS day, facility_id, payer_type,
           CASE WHEN start_reason = 'admission' THEN 1 ELSE 0 END AS adm,
           0 AS dis,
           CASE WHEN start_reason = 'payer_change'
                     AND previous_type IS DISTINCT FROM payer_type THEN 1 ELSE 0 END AS cin,
           0 AS cout
    FROM period
    UNION ALL
    SELECT end_date, facility_id, payer_type, 0,
           CASE WHEN end_reason = 'discharge' THEN 1 ELSE 0 END,
           0,
           CASE WHEN end_reason = 'payer_change'
                     AND next_type IS DISTINCT FROM payer_type THEN 1 ELSE 0 END
    FROM period WHERE end_date IS NOT NULL
)"""

# Closing balance carried across a partition, and the opening it implies. Used
# with a window over whichever grain the caller grouped to.
RUNNING_CLOSING = """sum(coalesce(m.admissions, 0) + coalesce(m.changes_in, 0)
             - coalesce(m.discharges, 0) - coalesce(m.changes_out, 0))"""
OPENING_FROM_CLOSING = 'closing - admissions - changes_in + discharges + changes_out'
