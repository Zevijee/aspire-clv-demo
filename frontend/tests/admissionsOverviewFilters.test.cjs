const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const path = require('node:path')
const { test } = require('node:test')
const vm = require('node:vm')
const ts = require('typescript')

const source = readFileSync(path.join(__dirname, '../src/features/adt/utils/admissionsOverviewFilters.ts'), 'utf8')
const utility = { exports: {} }
vm.runInNewContext(ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText, { exports: utility.exports })
const { overviewFilterSettings, overviewFilterValues, overviewSelection, getLocationOptions, getLocationLevel,
  matchesLocation, selectedOverviewFacilities, groupOverviewFacilities } = utility.exports
const plain = (value) => JSON.parse(JSON.stringify(value))
const locations = Array.from({ length: 20 }, (_, i) => ({
  state: i % 2 ? 'Texas' : 'Florida', portfolio: `Portfolio ${i % 4}`,
  region: 'North', facility: `Facility ${i}`,
}))
const locationPath = (row) => [row.state, row.portfolio, row.region, row.facility]
const facilities = locations.map((row, i) => ({
  ...row, facility_name: row.facility, total_admissions: i, prior_period_admissions: i * 2,
  readmission_count: i % 3, referring_hospitals: ['Shared hospital', `Hospital ${i % 4}`],
}))

test('ten unrelated facilities persist as a custom selection and only those facilities match', () => {
  const chosen = locations.filter((_, i) => [0, 1, 4, 5, 7, 10, 11, 13, 17, 19].includes(i))
  const values = { location: chosen.map((row) => JSON.stringify(locationPath(row))), payer: ['Medicare'], source: ['Hospital'] }
  const selection = overviewSelection(values)
  assert.deepEqual(plain(overviewFilterValues(selection)), values)
  assert.equal(getLocationLevel(values.location), 'facility')
  assert.deepEqual(locations.filter((row) => matchesLocation(row, values.location)), chosen)
  assert.equal(selectedOverviewFacilities(facilities, values.location, null).length, 10)
})

test('same-named regions remain distinct and selected regions form a union without cross-matching parents', () => {
  const options = getLocationOptions(locations, 'region')
  assert.equal(options.length, 4)
  assert.equal(new Set(options.map((option) => option.value)).size, 4)
  const selected = [options[0].value, options[3].value]
  const filtered = selectedOverviewFacilities(facilities, selected, null)
  assert.equal(filtered.length, 10)
  assert.ok(filtered.every((row) => selected.includes(JSON.stringify(locationPath(row).slice(0, 3)))))
  assert.equal(groupOverviewFacilities(filtered, 'region', 10).length, 2)
})

test('custom totals, averages, hospital unions, and zero-admission facilities reconcile at every grouping level', () => {
  const chosen = locations.slice(0, 10).map((row) => JSON.stringify(locationPath(row)))
  const filtered = selectedOverviewFacilities(facilities, chosen, null)
  for (const level of ['state', 'portfolio', 'region', 'facility']) {
    const grouped = groupOverviewFacilities(filtered, level, 10)
    assert.equal(grouped.reduce((sum, row) => sum + row.current, 0), 45)
    assert.equal(grouped.reduce((sum, row) => sum + row.prior, 0), 90)
    assert.equal(grouped.reduce((sum, row) => sum + row.averagePerDay, 0), 4.5)
    assert.equal(grouped.reduce((sum, row) => sum + row.facilityCount, 0), 10)
    assert.equal(grouped.flatMap((row) => row.facilityNames).length, 10)
    for (const row of grouped) {
      assert.equal(row.referringHospitals.filter((name) => name === 'Shared hospital').length, 1)
      assert.equal(row.change, row.current - row.prior)
    }
  }
  assert.equal(groupOverviewFacilities(filtered, 'facility', 10).find((row) => row.name === 'Facility 0').current, 0)
})

test('drilling into a custom group intersects the selection and returning restores all selected facilities', () => {
  const chosen = locations.slice(0, 10).map((row) => JSON.stringify(locationPath(row)))
  assert.equal(selectedOverviewFacilities(facilities, chosen, { state: 'Texas' }).length, 5)
  assert.equal(selectedOverviewFacilities(facilities, chosen, { state: 'Texas', portfolio: 'Portfolio 1', region: 'North', facility: 'Facility 1' }).length, 1)
  assert.equal(selectedOverviewFacilities(facilities, chosen, { state: 'Texas', facility: 'Facility 19' }).length, 0)
  assert.equal(selectedOverviewFacilities(facilities, chosen, null).length, 10)
})

test('drawer describes drill-down separately and preserves it until explicitly cleared', () => {
  const selection = { scope: locations[0], payers: ['Medicare'], sources: ['Hospital'] }
  const values = overviewFilterValues(selection)
  const settings = overviewFilterSettings(selection)
  assert.deepEqual(plain(values.location), [])
  assert.deepEqual(plain(overviewSelection({ ...values, ...settings }).scope), locations[0])
  const reset = overviewSelection({ ...values, ...settings, scope: [] })
  assert.equal(reset.scope, null)
  assert.deepEqual(plain(reset.payers), ['Medicare'])
  assert.equal(selectedOverviewFacilities(facilities, [], null).length, 20)
})

test('grouping applies independently when no locations are selected and clear returns to state', () => {
  const selection = overviewSelection({ level: ['facility'], location: [], payer: [], source: [] })
  assert.equal(selection.groupBy, 'facility')
  assert.equal(groupOverviewFacilities(selectedOverviewFacilities(facilities, selection.locations, selection.scope), selection.groupBy, 10).length, 20)
  assert.equal(overviewSelection({ level: [], location: [], scope: [] }).groupBy, 'state')
})

test('facility list narrows by state, portfolio, or an exact region without changing selected facilities', () => {
  const selected = [JSON.stringify(locationPath(locations[0])), JSON.stringify(locationPath(locations[1]))]
  const stateOptions = getLocationOptions(locations, 'facility', ['Texas'])
  assert.equal(stateOptions.length, 10)
  assert.ok(stateOptions.every((option) => JSON.parse(option.value)[0] === 'Texas'))
  const portfolioOptions = getLocationOptions(locations, 'portfolio', ['Texas'])
  assert.equal(portfolioOptions.length, 2)
  const regionOptions = getLocationOptions(locations, 'region', ['Texas', 'Portfolio 1'])
  assert.equal(regionOptions.length, 1)
  const narrowed = getLocationOptions(locations, 'facility', JSON.parse(regionOptions[0].value))
  assert.equal(narrowed.length, 5)
  assert.ok(narrowed.every((option) => JSON.parse(option.value)[1] === 'Portfolio 1'))
  const combined = [...new Set([...selected, ...narrowed.map((option) => option.value)])]
  assert.equal(combined.length, 6)
  assert.ok(combined.includes(selected[0]))
  assert.equal(getLocationOptions(locations, 'facility', []).length, 20)
  assert.equal(getLocationOptions(locations, 'facility', ['Missing state']).length, 0)
})
