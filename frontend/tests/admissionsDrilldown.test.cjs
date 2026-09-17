const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const path = require('node:path')
const { test } = require('node:test')
const vm = require('node:vm')
const ts = require('typescript')

const source = readFileSync(path.join(__dirname, '../src/features/adt/utils/admissionsDrilldown.ts'), 'utf8')
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, esModuleInterop: true },
})
const utility = { exports: {} }
vm.runInNewContext(outputText, { exports: utility.exports, require })
const { getDrilldownRows, getDrilldownSummary, getDrilldownTotal } = utility.exports

function metrics(current, prior, extra = {}) {
  return {
    admissions_change: current - prior,
    average_admissions_per_day: current / 10,
    facility_count: 1,
    medicare_admission_count: 0,
    medicare_admissions_change: 0,
    prior_period_admissions: prior,
    prior_period_medicare_admission_count: 0,
    readmission_count: current / 10,
    referring_hospitals: [],
    region_count: 1,
    total_admissions: current,
    ...extra,
  }
}

function facility(state, portfolio, region, name, current, prior) {
  const row = metrics(current, prior, { state, portfolio, region, facility_name: name })
  // The facility endpoint does not return these aggregate-level properties.
  delete row.facility_count
  delete row.region_count
  return row
}

const data = {
  portfolios: [
    metrics(20, 40, { state: 'Texas', region: 'Bravo', facility_count: 1, region_count: 1 }),
    metrics(100, 80, { state: 'Texas', region: 'Alpha', facility_count: 3, region_count: 2 }),
    metrics(15, 10, { state: 'Florida', region: 'Alpha', facility_count: 1, region_count: 1 }),
  ],
  regions: [
    metrics(40, 40, { state: 'Texas', portfolio: 'Alpha', region: 'North', facility_count: 2 }),
    metrics(60, 40, { state: 'Texas', portfolio: 'Alpha', region: 'South' }),
    metrics(20, 40, { state: 'Texas', portfolio: 'Bravo', region: 'North' }),
    metrics(15, 10, { state: 'Florida', portfolio: 'Alpha', region: 'North' }),
  ],
  facilities: [
    facility('Texas', 'Alpha', 'North', 'Cedar', 30, 20),
    facility('Texas', 'Alpha', 'North', 'Elm', 10, 20),
    facility('Texas', 'Alpha', 'South', 'Birch', 60, 40),
    facility('Texas', 'Bravo', 'North', 'Cedar', 20, 40),
    facility('Florida', 'Alpha', 'North', 'Cedar', 15, 10),
  ],
}

test('state layer groups portfolios and calculates growth from combined totals', () => {
  const rows = getDrilldownRows(data, null)
  assert.equal(rows.length, 2)
  const texas = rows.find(row => row.state === 'Texas')
  assert.equal(texas.name, 'Texas')
  assert.equal(texas.current, 120)
  assert.equal(texas.prior, 120)
  assert.equal(texas.growth, 0)
  assert.equal(texas.portfolioCount, 2)
  assert.equal(texas.facilityCount, 4)
  assert.equal(texas.regionCount, 3)
  assert.equal(texas.averagePerDay, 12)
  assert.equal(texas.readmissions, 12)
  for (const state of rows) {
    const children = getDrilldownRows(data, { state: state.state })
    assert.equal(children.length, state.portfolioCount)
    assert.equal(getDrilldownSummary(children).current, state.current)
    assert.equal(getDrilldownSummary(children).prior, state.prior)
  }
})

test('portfolio layer stays within its selected state and ranks relative performance', () => {
  const rows = getDrilldownRows(data, { state: 'Texas' })
  assert.equal(rows.length, 2)
  assert.ok(rows.every(row => row.state === 'Texas'))
  assert.equal(rows[0].name, 'Alpha')
  assert.equal(rows[0].growth, 25)
  assert.equal(rows[1].name, 'Bravo')
  assert.equal(rows[1].growth, -50)
  assert.equal(rows[0].facilityCount, 3)
  assert.equal(rows[0].regionCount, 2)
  assert.equal(rows[0].averagePerDay, 10)
  const florida = getDrilldownRows(data, { state: 'Florida' })
  assert.equal(florida.length, 1)
  assert.equal(florida[0].growth, 50)
  assert.notEqual(florida[0].key, rows[0].key)
  assert.equal(getDrilldownRows(data, { state: 'Unknown' }).length, 0)
})

test('regions and facilities stay inside the exact parent despite repeated names', () => {
  const regions = getDrilldownRows(data, { state: 'Texas', portfolio: 'Alpha' })
  assert.equal(regions.length, 2)
  assert.equal(regions[0].name, 'South')
  assert.equal(regions[1].name, 'North')
  assert.ok(regions.every((row) => row.state === 'Texas' && row.portfolio === 'Alpha'))

  const facilities = getDrilldownRows(data, { state: 'Texas', portfolio: 'Alpha', region: 'North' })
  assert.equal(facilities.length, 2)
  assert.equal(facilities[0].name, 'Cedar')
  assert.equal(facilities[0].current, 30)
  assert.equal(facilities[1].name, 'Elm')
  assert.ok(facilities.every((row) => row.facilityCount === 1 && row.regionCount === 0))

  const otherPortfolio = getDrilldownRows(data, { state: 'Texas', portfolio: 'Bravo', region: 'North' })
  const otherState = getDrilldownRows(data, { state: 'Florida', portfolio: 'Alpha', region: 'North' })
  assert.equal(otherPortfolio[0].current, 20)
  assert.equal(otherState[0].current, 15)
  assert.equal(new Set([facilities[0].key, otherPortfolio[0].key, otherState[0].key]).size, 3)
})

test('facility detail isolates its full hierarchy and returns to its siblings', () => {
  const parent = { state: 'Texas', portfolio: 'Alpha', region: 'North' }
  const before = JSON.stringify(data)
  const rows = getDrilldownRows(data, { ...parent, facility: 'Cedar' })
  assert.equal(rows.length, 1)
  assert.equal(rows[0].name, 'Cedar')
  assert.equal(rows[0].current, 30)
  assert.equal(rows[0].prior, 20)
  assert.equal(rows[0].facilityCount, 1)
  assert.equal(getDrilldownRows(data, { ...parent, facility: 'Unknown' }).length, 0)
  assert.equal(getDrilldownRows(data, parent).length, 2)
  assert.equal(JSON.stringify(data), before)
})

test('facility detail retains a selected facility with zero admissions', () => {
  const scope = { state: 'Texas', portfolio: 'Alpha', region: 'North', facility: 'Cedar' }
  const rows = getDrilldownRows({
    ...data,
    facilities: [facility('Texas', 'Alpha', 'North', 'Cedar', 0, 0)],
  }, scope)
  assert.equal(rows.length, 1)
  assert.equal(rows[0].current, 0)
  assert.equal(rows[0].growth, null)
})

test('every parent reconciles to its child admissions and readmissions', () => {
  for (const portfolio of getDrilldownRows(data, null).flatMap(state => getDrilldownRows(data, { state: state.state }))) {
    const regions = getDrilldownRows(data, { state: portfolio.state, portfolio: portfolio.name })
    const regionSummary = getDrilldownSummary(regions)
    assert.equal(regionSummary.current, portfolio.current)
    assert.equal(regionSummary.prior, portfolio.prior)
    assert.equal(regionSummary.change, portfolio.change)
    assert.equal(regions.reduce((sum, row) => sum + row.readmissions, 0), portfolio.readmissions)
    assert.equal(regions.reduce((sum, row) => sum + row.facilityCount, 0), portfolio.facilityCount)

    for (const region of regions) {
      const facilities = getDrilldownRows(data, {
        state: region.state,
        portfolio: region.portfolio,
        region: region.name,
      })
      const facilitySummary = getDrilldownSummary(facilities)
      assert.equal(facilitySummary.current, region.current)
      assert.equal(facilitySummary.prior, region.prior)
      assert.equal(facilitySummary.change, region.change)
      assert.equal(facilities.length, region.facilityCount)
      assert.equal(facilities.reduce((sum, row) => sum + row.readmissions, 0), region.readmissions)
    }
  }
})

test('zero-prior rows remain visible after ranked rows and never become best or worst', () => {
  const rows = getDrilldownRows({
    portfolios: [
      metrics(100, 0, { state: 'Texas', region: 'New admissions' }),
      metrics(0, 0, { state: 'Texas', region: 'No activity' }),
      metrics(0, 10, { state: 'Texas', region: 'Declined' }),
      metrics(10, 10, { state: 'Texas', region: 'Unchanged' }),
    ],
    regions: [],
    facilities: [],
  }, { state: 'Texas' })
  assert.equal(rows[0].name, 'Unchanged')
  assert.equal(rows[1].name, 'Declined')
  assert.equal(rows[1].growth, -100)
  assert.equal(rows[2].growth, null)
  assert.equal(rows[3].growth, null)
  const summary = getDrilldownSummary(rows)
  assert.equal(summary.best.name, 'Unchanged')
  assert.equal(summary.worst.name, 'Declined')
  assert.equal(summary.growing, 1)
  assert.equal(summary.current, 110)
  assert.equal(summary.prior, 20)
  assert.equal(summary.change, 90)
})

test('ties are deterministic and summary ranking does not depend on input order', () => {
  const rows = getDrilldownRows({
    portfolios: [
      metrics(20, 10, { state: 'Texas', region: 'Zebra' }),
      metrics(10, 5, { state: 'Texas', region: 'Alpha' }),
      metrics(10, 10, { state: 'Texas', region: 'Middle' }),
    ],
    regions: [],
    facilities: [],
  }, { state: 'Texas' })
  assert.equal(rows[0].name, 'Alpha')
  assert.equal(rows[1].name, 'Zebra')
  const reversed = [...rows].reverse()
  const summary = getDrilldownSummary(reversed)
  assert.equal(summary.best.name, 'Alpha')
  assert.equal(summary.worst.name, 'Middle')
  assert.equal(reversed[0].name, 'Middle')
})

test('empty or unknown scopes do not invent metrics or performers', () => {
  const rows = getDrilldownRows(data, { state: 'Texas', portfolio: 'Unknown' })
  assert.equal(rows.length, 0)
  const summary = getDrilldownSummary(rows)
  assert.equal(summary.current, 0)
  assert.equal(summary.prior, 0)
  assert.equal(summary.change, 0)
  assert.equal(summary.growing, 0)
  assert.equal(summary.best, undefined)
  assert.equal(summary.worst, undefined)

  const noPrior = getDrilldownRows({
    portfolios: [metrics(5, 0, { state: 'Texas', region: 'New' })],
    regions: [],
    facilities: [],
  }, { state: 'Texas' })
  assert.equal(getDrilldownSummary(noPrior).best, undefined)
  assert.equal(getDrilldownSummary(noPrior).worst, undefined)
})

test('drilling and returning preserve source data and restore the parent layer', () => {
  const before = JSON.stringify(data)
  const rootRows = getDrilldownRows(data, null)
  getDrilldownRows(data, { state: 'Texas', portfolio: 'Alpha' })
  getDrilldownRows(data, { state: 'Texas', portfolio: 'Alpha', region: 'North' })
  assert.equal(JSON.stringify(getDrilldownRows(data, null)), JSON.stringify(rootRows))
  assert.equal(JSON.stringify(data), before)
})

test('table totals aggregate each drill-down layer and calculate averages from combined counts', () => {
  const scopes = [null, { state: 'Texas' }, { state: 'Texas', portfolio: 'Alpha' },
    { state: 'Texas', portfolio: 'Alpha', region: 'North' }]
  for (const scope of scopes) {
    const rows = getDrilldownRows(data, scope)
    const before = JSON.stringify(rows)
    const total = getDrilldownTotal(rows, 10)
    assert.equal(total.name, 'Total')
    assert.equal(total.isTotal, true)
    for (const field of ['current', 'prior', 'readmissions', 'facilityCount', 'portfolioCount', 'regionCount']) {
      assert.equal(total[field], rows.reduce((sum, row) => sum + row[field], 0))
    }
    assert.equal(total.change, total.current - total.prior)
    assert.equal(total.averagePerDay, total.current / 10)
    assert.equal(JSON.stringify(rows), before)
  }
  const total = getDrilldownTotal(getDrilldownRows(data, { state: 'Texas' }), 10)
  assert.equal(total.current / total.facilityCount, 30)
  assert.equal(total.current / total.facilityCount / 10, 3)
})

test('table totals are hidden for empty and single-row views', () => {
  assert.equal(getDrilldownTotal([], 10), null)
  assert.equal(getDrilldownTotal(getDrilldownRows(data, { state: 'Florida' }), 10), null)
  const rows = getDrilldownRows(data, null)
  assert.equal(getDrilldownTotal(rows.slice(0, 1), 10), null)
})

test('referring hospitals are distinct across portfolios, states, and the total', () => {
  const hospitalData = {
    ...data,
    portfolios: data.portfolios.map((row, index) => ({
      ...row, referring_hospitals: ['Shared Hospital', `Hospital ${index}`],
    })),
    regions: data.regions.map(row => ({ ...row, referring_hospitals: ['Shared Hospital'] })),
    facilities: data.facilities.map(row => ({ ...row, referring_hospitals: ['Shared Hospital'] })),
  }
  const states = getDrilldownRows(hospitalData, null)
  assert.equal(states.find(row => row.state === 'Texas').referringHospitals.length, 3)
  assert.equal(getDrilldownTotal(states, 10).referringHospitals.length, 4)
  const portfolios = getDrilldownRows(hospitalData, { state: 'Texas' })
  assert.ok(portfolios.every(row => row.referringHospitals.length === 2))
  assert.equal(getDrilldownTotal(portfolios, 10).referringHospitals.length, 3)
  for (const scope of [{ state: 'Texas', portfolio: 'Alpha' },
    { state: 'Texas', portfolio: 'Alpha', region: 'North' }]) {
    const rows = getDrilldownRows(hospitalData, scope)
    assert.ok(rows.every(row => row.referringHospitals.length === 1))
    assert.equal(getDrilldownTotal(rows, 10).referringHospitals.length, 1)
  }
  assert.equal(getDrilldownTotal(getDrilldownRows(data, null), 10).referringHospitals.length, 0)
})
