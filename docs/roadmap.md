# Roadmap and known gaps

What is next, and what is deliberately unfinished. Nothing here is a bug report
against work already done; it is the list of things consciously left.

## Where things stand

The backend was rebuilt from per-report SQL into feature packages over a fact table.
Admissions is complete end to end. The other reports have frontend components but no
backend, because the endpoints they call were removed in that rebuild and have not
been reimplemented.

## Next: discharges

The natural second module, for three reasons: it reconnects a dead report, it is the
other half of net change and monthly trending, and it gives the **second** real
example needed to factor out the shared report shape (below).

`DischargeLogGenerator` already rebuilds `discharge_logs` from saved stays with the
same seed the simulation uses, so the source data needs no work. What is needed is a
`daily_discharge_facts` table, a generator, a service and a client.

Store `sum_los` and a discharge count as **separate additive columns**, never a
pre-computed average. A stored mean makes every roll-up above facility level
silently wrong. The same applies to any ratio: sum the numerators, divide once.

See [backend-structure.md](backend-structure.md#adding-a-report-module) for the
step-by-step.

## Dead frontend reports

Two reports render but do not load. The components, filters and drilldowns are
written; they call endpoints that no longer exist.

| Report | Path | Calls |
| --- | --- | --- |
| Referring Hospital | `/adt/referring-hospital` | `/adt/admissions/by-referring-hospital`, `/referring-hospital-performance`, `/referring-hospital-location-performance` |
| Live Census | `/census/daily-census` | `/census/live` |

Discharges, Payer Changes, Net Change and Monthly ADT Trending were rebuilt and now
work end to end. Each follows the same shape: an overview on a fact table, a logs
tab reading source rows, server-side filter options and a streamed CSV export.

The frontend also still calls fourteen removed `/adt/admissions/*` endpoints from
the legacy `api/admissions.ts` client (`/kpis`, `/by-region`, `/by-payer`,
`/daily-trend`, `/historical-comparisons` and others). Only
`api/admissionsOverview.ts` targets the current API.

Read the components before designing each response. They already encode a shape, and
matching it is cheaper than rewriting both ends.

**Referring Hospital needs no new fact table.** `daily_admission_facts` keeps
`source_name` at the grain, so it is a different `GROUP BY` over data that already
exists.

## Factoring out the shared report shape

`service.py` is about 180 lines for one fact table, and roughly 70% of it is not
about admissions: the coverage guard, location hierarchy and paths, minimal-join
selection, date and facility filtering, `GROUPING SETS`, zero-filling, facets that
omit their own filter, and the response envelope. Only the measures, the chart
dimensions and the hospital handling are specific.

Copied across fifteen fact tables that is ~2,700 lines that drift apart, and a bug
fixed in one report stays broken in fourteen.

The intended fix is a descriptor, not an engine:

```python
ADMISSIONS = FactReport(
    table=daily_admission_facts,
    measures={'admissions': sum_('admissions'), ...},
    dimensions={'payer': payers.c.payer_type, 'source': facts.c.source_type},
    facets=('payer', 'source'),
)
```

**Do this after discharges exists, not before.** An abstraction guessed from one
example is the kind that fights you later, and staffing and AR/AP look nothing like
ADT. The existing note in `backend-structure.md` — that a module need not expose the
same layouts or endpoints as another — is the constraint any shared shape must
respect.

## Cleanup

**Duplicate log-writing.** `aspire-res-stays.py` writes admission and discharge logs
inline, and `aspire-admission-logs.py` / `aspire-discharge-logs.py` can rebuild the
same rows standalone. Two implementations that agree only because they share a seed.
Now that the standalone path is reachable, verify the regenerated rows match
byte-for-byte and then delete the inline copy.

**Dead reset path.** `run_days` still TRUNCATEs the ADT tables when `reset_history`
is set, but `seed --reset-history` now drops and recreates the schema first, so it
truncates empty tables. Harmless, redundant.

**Empty staged draft.** `shared/database/staged/` holds a draft identical to the
active schema, left from a schema experiment. It is gitignored, but `update` will
try to publish it each run.

## Data tuning

Neither is wrong, both are noticeable. Each needs a full re-seed (~9.5 min).

**Monday is too spiky: +87% against the weekly mean.** The entire weekend backlog
lands in one day; real facilities spread catch-up across Monday to Wednesday.
Lowering Monday's entry in `WEEKDAY_ADMISSION_RATE` from 1.0 to about 0.70 rolls the
remainder into Tuesday and Wednesday.

**Medicaid is 26.7% of admissions.** Up from 23%, short of the ~33% wanted. The
cause is visible in the census: Medicaid sits at 58%, because `MEDICAID_CENSUS_RANGE`
averages 58% where the old flat range averaged 65%. Hitting 33% needs both a higher
census range and a shorter Medicaid stay band. 26.7% is defensible on its own —
industry runs 20–35% — so this is a judgement call, not a defect.

## Known simplifications

**No mid-stay skilled conversion.** Verified: 142,157 skilled-to-non-skilled payer
transitions, zero the other way. Correct for traditional Medicare, which needs a
qualifying three-day hospital stay — modelled as discharge and readmission. Wrong for
Medicare Advantage, which often waives it. Real data will contain these; the demo
will not. Worth knowing before designing a Payer Changes report against it.

**Definitional metrics that read oddly.** 30-day readmission is ~10% against an
industry ~20%, and "readmission" means any resident with a prior stay, which climbs
with history toward 60%. Explain these before a demo, not during one.

**No dump in the repository.** `docker/initdb/aspire.sql.gz` is 129 MB and
gitignored. A teammate cloning the repo gets the stack but an empty database.
Distribute it as a release asset. See [docker.md](docker.md).

**Empty directories.** `frontend/src/api/` and `frontend/src/components/layout/` are
leftovers from the refactor.

**Frontend tests are untouched.** `frontend/tests/` holds fifteen `.cjs` files, most
covering the dead reports. Left alone per the no-tests rule in
[AGENTS.md](../AGENTS.md).

## Longer term

Nothing below is needed now. Recorded because the analysis exists; see
[scaling.md](scaling.md).

**Facility sharding.** At ~50× source data the simulation needs ~15 GB of RAM and
will not run. The only cross-facility coupling is the global unique constraint on
resident names; partition the name pool and it shards cleanly, fixing memory and
runtime together.

**Matching the real pipeline.** When the ETL takes shape, the question worth
revisiting is whether it emits these fact shapes. If it will use dbt, converging the
demo's generators on dbt models is worth doing before writing many more of them.
Under full refresh the per-date checkpoint machinery for derived tables is also
unnecessary, and dropping it would make the demo behave more like production, not
less.
