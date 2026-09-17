const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')
const { test } = require('node:test')
const exportsObject = {}
const code = ts.transpileModule(readFileSync(path.join(__dirname,
  '../src/features/adt/utils/dischargesDrilldown.ts'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText
vm.runInNewContext(code, { exports: exportsObject })
const { getDischargeDrilldownRows: group, getDischargeTotal: total } = exportsObject
const rows = [
  { facility_code: '1', facility_name: 'Oak', state: 'Texas', portfolio: 'Texas 1', region: 'North', total_discharges: 30, prior_period_discharges: 20, ama_discharges: 2, hospital_transfers: 5 },
  { facility_code: '2', facility_name: 'Bay', state: 'Texas', portfolio: 'Texas 1', region: 'North', total_discharges: 0, prior_period_discharges: 5, ama_discharges: 0, hospital_transfers: 0 },
  { facility_code: '3', facility_name: 'Pine', state: 'Texas', portfolio: 'Texas 2', region: 'North', total_discharges: 90, prior_period_discharges: 100, ama_discharges: 4, hospital_transfers: 12 },
  { facility_code: '4', facility_name: 'Elm', state: 'Florida', portfolio: 'Florida 1', region: 'North', total_discharges: 20, prior_period_discharges: 10, ama_discharges: 1, hospital_transfers: 3 },
]

test('state averages include zero-activity facilities and totals use weighted denominators', () => {
  const states = group(rows, [], 10)
  const texas = states.find((row) => row.name === 'Texas')
  assert.equal(texas.total, 120)
  assert.equal(texas.ama, 6)
  assert.equal(texas.hospitalTransfers, 17)
  assert.deepEqual(Array.from(texas.facilityNames).sort(), ['Bay', 'Oak', 'Pine'])
  assert.equal(texas.prior, 125)
  assert.equal(texas.change, -5)
  assert.equal(texas.facilityCount, 3)
  assert.equal(texas.averagePerDay, 12)
  assert.equal(texas.averagePerFacility, 40)
  assert.equal(texas.averagePerFacilityPerDay, 4)
  const footer = total(states, 10)
  assert.equal(footer.total, 140)
  assert.equal(footer.ama, 7)
  assert.equal(footer.hospitalTransfers, 20)
  assert.deepEqual(Array.from(footer.facilityNames).sort(), ['Bay', 'Elm', 'Oak', 'Pine'])
  assert.equal(footer.prior, 135)
  assert.equal(footer.averagePerFacility, 35)
  assert.equal(footer.averagePerFacilityPerDay, 3.5)
})

test('every child reconciles with its parent and repeated region names stay isolated', () => {
  function check(path) {
    for (const parent of group(rows, path, 10)) {
      if (parent.path.length === 4) continue
      const children = group(rows, parent.path, 10)
      for (const key of ['total', 'prior', 'facilityCount', 'ama', 'hospitalTransfers']) {
        assert.equal(children.reduce((sum, row) => sum + row[key], 0), parent[key])
      }
      check(parent.path)
    }
  }
  check([])
  const facilities = group(rows, ['Texas', 'Texas 1', 'North'], 10)
  assert.deepEqual(Array.from(facilities, (row) => row.name), ['Bay', 'Oak'])
  assert.equal(facilities[0].total, 0)
  assert.equal(group(rows, ['Florida', 'Florida 1', 'North'], 10)[0].total, 20)
})

test('returning to root restores states and totals hide for single or empty results', () => {
  assert.equal(group(rows, ['Texas'], 10).length, 2)
  assert.equal(group(rows, [], 10).length, 2)
  assert.equal(group(rows, ['Missing'], 10).length, 0)
  assert.equal(total([], 10), null)
  assert.equal(total(group(rows, ['Florida'], 10), 10), null)
})

test('LOS uses discharge-weighted totals at every grouping and in the footer', () => {
  const fixtures = rows.map((row, index) => ({ ...row, total_los_days: row.total_discharges * [10, 0, 30, 50][index] }))
  const states = group(fixtures, [], 10)
  const tx = states.find(row => row.name === 'Texas')
  assert.equal(tx.totalLosDays / tx.total, 25)
  const footer = total(states, 10)
  assert.equal(footer.totalLosDays, 4000)
  assert.equal(footer.totalLosDays / footer.total, 4000 / 140)
  const facilities = group(fixtures, ['Texas', 'Texas 1', 'North'], 10)
  assert.equal(facilities.find(row => row.name === 'Oak').totalLosDays, 300)
  assert.equal(facilities.find(row => row.name === 'Bay').totalLosDays, 0)
})
