# How the data is generated

One day-by-day simulation produces the entire ADT domain. It lives in
`sandbox-data/source_data_generators/aspire-res-stays.py`, whose filename undersells
it: `DailyAdtGenerator` owns nine tables.

```text
residents  res_stays  res_payer_stays  admission_logs  discharge_logs
medicaid_applications  sandbox_adt_residents  sandbox_adt_active_stays
adt_daily_census
```

They are generated together because they are causally inseparable. One `_admit()`
call decides a resident, a payer, a planned length of stay and a referral source,
and writes a stay, its payer periods, an admission log, possibly a Medicaid
application, and resident state. A discharge log cannot be generated independently
of the stay it closes or the payer period that sets its length of stay.

`aspire-admission-logs.py` and `aspire-discharge-logs.py` hold the rules for
referral sources and discharge destinations. The simulation imports their constants;
they can also rebuild their own table from saved stays (see
[Regenerating one table](#regenerating-one-table)).

## Determinism

Everything is seeded from `SEED = 42` plus saved IDs, never from the command's date
range. Resident IDs derive from the facility and a sequence, stay IDs from the
resident and admission number, and every random draw is keyed by some combination of
facility, stay, resident and date.

The same `facilities.json` and the same seed reproduce the same data. Generating
1 January to 30 June in one command or six produces identical rows. This is what
makes `seed --reset-history` safe to drop every table rather than clearing rows.

## Commands

From `sandbox-data`:

| Command | Does |
| --- | --- |
| `python manage.py update` | Migrate, then generate missing days. Safe to repeat. |
| `python manage.py seed --reset-history` | Drop every table and rebuild from 2023-01-01. |
| `python manage.py status` | Applied migrations, backfills, staged drafts. |
| `python manage.py admissions_summary --regenerate` | Rebuild facts from saved ADT. |
| `python manage.py admission_logs --regenerate` | Rebuild admission logs from saved stays. |
| `python manage.py discharge_logs --regenerate` | Rebuild discharge logs from saved stays. |

`res_stays` as a standalone command deliberately fails: fixed-window stay generation
was replaced by the daily simulation, and the guard says so.

A full reset takes about nine and a half minutes at 253 facilities over four years.
Roughly 96% of that is the simulation; reference data, residents and the fact
rebuild account for about twenty seconds.

## What changing a rule costs

This is the question worth knowing before you edit anything.

| Change | Rebuild needed |
| --- | --- |
| A metric derivable from existing fact dimensions | **Nothing** — different `GROUP BY` |
| Referral source weights, hospital scores, discharge destinations | `admission_logs --regenerate` or `discharge_logs --regenerate`, seconds |
| A new additive measure on a fact table | Column, backfill, `admissions_summary --regenerate` |
| **Any payer rule, stay length, or census target** | **Full `seed --reset-history`** |

The last row is unavoidable, and the reason is worth understanding: the payer chosen
at admission decides the planned length of stay, which decides the discharge date,
which decides the census, which decides how many admissions the facility needs
tomorrow. Payer rules and the stay history are circular. You cannot hold `res_stays`
fixed and regenerate payer periods on top of it.

Referral sources and discharge destinations are different because nothing reads them
back — they are pure outputs, pure functions of the stay ID, and the standalone
generators use the identical seed, so regenerating reproduces the same values.

## Regenerating one table

`AdmissionLogGenerator` reads saved stays with window functions for the readmission
flags, takes the first payer period for the payer, and derives source type and name
from `Random(source_id('daily-admission-source', SEED, stay_id))` — byte-identical
to what the simulation wrote. `DischargeLogGenerator` does the same for
destinations and the deceased flag.

Use this after changing source weights or hospital scores, or after adding a column,
instead of replaying four years of history.

## The tuning knobs

All in `aspire-res-stays.py`. Every one of these needs a full reset to take effect.

### Facility operation profile

One draw per facility places it on a spectrum from long-term custodial care (0) to
short-stay rehab (1). Every payer target follows from that position, which is why
they can never contradict each other — independently drawn skilled and Medicaid
targets could sum past 100%.

```python
SKILLED_CENSUS_RANGE  = (0.05, 0.35)   # skilled share of occupied beds
MEDICAID_CENSUS_RANGE = (0.75, 0.42)   # falls as skilled rises
REGION_SHIFT          = 0.15           # neighbours share a payer landscape
TURNOVER_RANGE        = (1.15, 0.80)   # multiplies non-Medicaid stay length
SKILLED_PERIOD_MODE   = (14, 40)       # days on skilled coverage
```

| Position | Skilled | Medicaid | Turnover | Skilled period |
| --- | --- | --- | --- | --- |
| 0.00 custodial | 5% | 75% | 1.15× | 14 d |
| 0.50 | 20% | 58% | 0.97× | 27 d |
| 1.00 rehab | 35% | 42% | 0.80× | 40 d |

Turnover and skilled period length are not decoration. Skilled coverage is only ever
a stay's *first* payer period, so sustaining a high skilled census requires a
matching admission rate. Without faster turnover and longer skilled periods, a 35%
target is unreachable at any admission volume.

Measured result: skilled census ranges 7.2%–37.1% across facilities, mean 21.4%,
standard deviation 7.25.

### Census feedback

Both targets are *census* targets, steered rather than enforced. `_admission_payer`
compares the facility's current share against its target and scales the relevant
payer weights by `exp(16 × (target − share))`, clamped to 0.05–8.0.

Census and admission mix are different numbers, and the gap is large. Non-skilled
periods occupy 2.7× more days each, so a facility whose *stays* are 60% skilled
reads as roughly 36% skilled *census*. Expect the admissions chart to look far more
skilled than the bed mix, because that is how real facilities look too.

### Stay length

`STAY_LENGTH_BANDS`, chosen at admission from the initial payer type. Each entry is
`((low, high), weight)`; a band is picked, then a day within it.

| Payer | Mean planned stay |
| --- | --- |
| private | 284 d |
| medicaid | 174 d |
| va | 79 d |
| hospice | 53 d |
| medicare | 47 d |
| medicare_comm | 47 d |
| medicare_hmo | 32 d |

Managed Medicare discharges sooner than traditional Medicare because plans manage
length of stay down. Private pay is largely custodial. Hospice has a short median
and a long tail. A single non-Medicaid band previously gave all six payers the same
sixty-day stay, which a nursing operator spots immediately.

Medicaid length and Medicaid share of *admissions* are locked together by
arithmetic: admissions share × length of stay = census share. At 174 days and 58%
census, Medicaid is about 27% of admissions. Shorten the band to raise that; lengthen
it to lower it.

### Time

```python
WEEKDAY_ADMISSION_RATE = (1.0, 1.0, 1.0, 1.0, 0.9, 0.45, 0.35)   # Mon..Sun
SEASONAL_LIFT = {1: .025, 2: .025, 3: .015, 4: 0, 5: -.01, 6: -.025,
                 7: -.03, 8: -.025, 9: -.01, 10: .005, 11: .015, 12: .02}
DISRUPTION_CHANCE = 0.04          # per facility per month
DISRUPTION_DEPTH  = (0.04, 0.14)  # below target, 10-26 days, gradual recovery
```

Weekend admissions fall because hospital discharge planning is a weekday function.
Beds are not lost — the shortfall is still below target on Monday and fills then,
which produces the weekly sawtooth. Measured: Saturday −62%, Sunday −54%.

Seasonality sums to roughly zero across the year, so it moves the shape without
shifting the annual average. Measured group occupancy runs 87.1% in July to 92.5%
in January, against 90.4–90.7% before it existed.

Disruptions represent an outbreak, a survey or a staffing hold. At 4% per facility
per month, about ten of 253 facilities are affected in any month — enough that
outlier dashboards always have something to find without it becoming noise.

### Other rules

Skilled payers share a 100-day allowance per resident (`MAX_SKILLED_DAYS`), reset
only after 60 days out of the facility. Roughly half of Medicaid admissions begin
pending, with a 7–14 day approval delay; approval retroactively corrects the
original payer period and admission log rather than creating a payer change. Roughly
half of approved Medicaid selects State Medicaid.

## Performance

The simulation is fast; the writes were not.

`run_day` touches the database zero times — it is pure computation, leaving rows in
buffers that `flush_writes` writes once per batch. `batch_days = 30` was measured
against per-day writes: 330 rows per table per write spends nearly all its time on
fixed statement cost, and 30 days of batching reaches bulk COPY rates.
[scaling.md](scaling.md) has the numbers.

Raising `batch_days` further has diminishing returns — writes are no longer the
bottleneck after batching, the Python simulation is.

## Known simplifications

**A payer change can never move a stay into skilled coverage.** Verified against the
data: 142,157 skilled-to-non-skilled transitions, zero in the other direction. This
is correct for traditional Medicare, which requires a qualifying three-day hospital
stay — modelled here as discharge and readmission, which also sets the readmission
flags. It is wrong for Medicare Advantage, which often waives that rule, and
managed Medicare is a substantial share of skilled volume. Mid-stay skilled
conversions will exist in real data and do not exist here.

**Facilities have no explicit operation type.** The profile is derived
deterministically from the facility ID and its region. `facilities.json` carries only
state, portfolio, market, facility and beds. Add a real field there if the
distinction should be editable rather than implicit.
