# Performance and scaling

Everything here was measured on the actual database at 253 facilities, 30,202 beds
and roughly four years of daily history (2023-01-01 onward). Numbers are recorded so
future decisions can argue with evidence instead of intuition.

## Current shape

| | |
| --- | --- |
| Facilities / beds | 253 / 30,202 |
| Residents | 333,680 |
| Admissions, all history | ~435,000 |
| `daily_admission_facts` | 429,971 rows, 89 MB |
| Whole database | ~806 MB |
| Full rebuild | ~9.5 min |
| Compressed snapshot | 129 MB |

## The reporting store decision

The original design stored one JSONB document per scope per day across group,
state, portfolio, region and facility — 288 scopes × 1,447 days = **416,736
documents**, of which 54% described a facility-day with no admissions at all.

| | Documents | Facts | |
| --- | --- | --- | --- |
| Storage | 1,101 MB | 89 MB | **12× smaller** |
| Full rebuild | ~180 s | ~21 s | **8.5× faster** |
| One-year, group by facility | 1,040 ms | 150–250 ms | **4–7× faster** |

Both produced identical answers — 89,938 admissions and 384 distinct referring
hospitals for the same query — which is how the replacement was validated.

**Where the read time went.** The document design fetched 92,345 payloads and summed
them in Python. The fetch was 1,000 ms; the Python loop was 40 ms. It was not
Python that was slow, it was moving 91 MB of JSONB. Pre-aggregation at the wrong
grain — per scope *per day* — meant a one-year report still had to sum 365 days ×
253 facilities at request time.

**Where the write time went.** 349,458 rows inserted into an indexed table with two
foreign keys took ~20 s. Dropping the keys, inserting, and rebuilding them once took
2.6 s. The aggregate query itself was always under a second.

## Query cost inside the service

Measured per query on a one-year, all-facility request:

| | |
| --- | --- |
| Bare `GROUP BY facility_id` on facts | **14 ms** |
| Same, with the full hierarchy plus `payers` joined | **124 ms** |
| `GROUPING SETS` with `COUNT(DISTINCT ...)` | **183 ms** |
| Same without the distinct count | **24 ms** |
| `COUNT(DISTINCT x)` grouped by date | **83 ms** |
| Deduplicate first, then count rows | **17 ms** |

Three lessons, all now applied in `service.py`: join only what the grouping key
needs, keep `COUNT(DISTINCT)` out of multi-grouping-set queries, and deduplicate
before counting rather than counting distinct per group.

## Seed cost

**90% of a seed is database writes; 10% is the simulation.** Measured per simulated
day before batching: 95 ms of Python against 889 ms of writes for ~2,950 rows.

Per-table write cost showed the shape clearly:

```
232.9 ms   859 rows   res_payer_stays     destination 819k rows
111.9 ms   508 rows   res_stays           destination 353k rows
 48.1 ms   508 rows   sandbox_adt_residents
 ... six more
545.8 ms   nine tables, ~332 rows each
```

The cost tracks the size of the table being written *into*, not the rows being
written. Each write anti-joins the staged rows against the destination to find
changes, so it gets slower as history accumulates.

**Batching fixes it** because total anti-join work is roughly
`number_of_batches × average_destination_size`:

| Batch | Throughput |
| --- | --- |
| 1 day (2,950 rows) | 59.4 ms/1k |
| 10 days | 24.5 ms/1k |
| 30 days (88,500 rows) | **12.1 ms/1k** |

Thirty times the rows for 6.1× the time. `batch_days = 30` came from this table.

Two further wins, both measured: skipping the anti-join and `ON CONFLICT` entirely
when the destination is empty (a fresh build), and computing month-keyed random
values once per month instead of once per day — each seeded `Random` costs 9.1 µs,
and there were 1.83 million of them.

## What breaks at scale

### More reporting tables

The product is expected to grow toward many reports. The critical insight is that
**reports are not tables**: the six ADT reports in the frontend all derive from four
event sources, and net change is literally admissions minus discharges. Roughly
10–20 fact tables should cover 200+ reports — one per event type, not one per
screen.

Projected storage at current data volume:

| | 50 reporting tables | 250 |
| --- | --- | --- |
| As documents | ~55 GB | ~275 GB |
| As facts | ~4.5 GB | ~22 GB |
| As facts, ~15 event-type tables | ~1.3 GB | ~1.3 GB |

### More source data

At 5× source data (more modules rather than more facilities), nothing structural
breaks. Memory stays near 1.5 GB, the seed lands around 45 minutes, and the whole
database is roughly 8 GB — a dump still fits a release asset.

At 50×, three things break, and they were measured rather than guessed:

**Memory is the hard blocker.** `prepare_daily` holds every open stay, every
resident state and every resident name in RAM: 298 MB today, ~15 GB at 50×. That
does not fit on a laptop, and no amount of query tuning helps.

**The simulation is single-process.** Tracing every piece of cross-facility state
found exactly one coupling: the global unique constraint on resident
`(first_name, last_name)`. Everything else — census, Medicaid and skilled counts,
resident pools, hospital lists, every RNG seed — is already keyed by facility.
Partition the name pool and the simulation shards cleanly by facility, which fixes
memory and runtime together. The name pool has 99.7 million combinations and is 19%
used at 50×, so capacity is not the issue.

**Generation time.** ~5.4 hours as-is; ~2.6 with write batching; roughly 20–40
minutes with eight-way facility sharding.

None of this is worth building before it is needed. It is recorded because the
analysis was done and the conclusions are not obvious.

## Data plausibility

Checked against skilled-nursing norms, since a demo whose numbers are wrong is
worse than no demo.

| Metric | Generated | Industry |
| --- | --- | --- |
| Payer mix, bed-days | Medicaid 58%, Medicare family 21%, private 19% | ~60 / ~13 / ~25 |
| Occupancy | 87–92% seasonal | 77–85% |
| Median stay | ~31 d final payer period | 20–30 d |
| Skilled census per facility | 7.2–37.1% | 5–40% |
| Facility variation | CV 23% | 30–50% |

Two things a reviewer will question. The **30-day readmission rate** is about 10%
against an industry ~20%. And **"readmission"** counts any resident with a prior
stay, which climbs with history and reads near 60% — a clinician will interpret that
as rehospitalisation and think it is broken. Both are definitional choices rather
than bugs, but they are the ones to explain before a demo rather than during.

Facility variation at CV 23% is better than the 12% before the operation-profile
change, but still tighter than reality. Pushing it further means widening
`SKILLED_CENSUS_RANGE` and `TURNOVER_RANGE` in
[generators.md](generators.md#the-tuning-knobs).
