const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')
const { test } = require('node:test')
const output = {}
vm.runInNewContext(ts.transpileModule(readFileSync(path.join(__dirname,
  '../src/features/adt/utils/netChangeDrilldown.ts'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText, { exports: output })
const { getNetChangeRows: group, getNetChangeTotal: total } = output
const rows = [
  ['Oak', 'Texas', 'One', 10, 3, 2],
  ['Bay', 'Texas', 'One', 20, 0, 0],
  ['Pine', 'Texas', 'Two', 30, 2, 4],
  ['Elm', 'Florida', 'One', 40, 8, 3],
].map(([facility_name, state, portfolio, opening_census, admissions, discharges]) => ({
  facility_name, state, portfolio, region: 'North', opening_census, admissions, discharges,
  closing_census: opening_census + admissions - discharges,
  net_change: admissions - discharges, prior_net_change: -2,
}))

test('all hierarchy levels balance and retain zero activity facilities', () => {
  function check(path) {
    for (const row of group(rows, path)) {
      assert.equal(row.closing_census - row.opening_census, row.net_change)
      assert.equal(row.admissions - row.discharges, row.net_change)
      if (row.path.length === 4) continue
      const children = group(rows, row.path)
      for (const key of ['opening_census', 'closing_census', 'admissions', 'discharges',
        'net_change', 'prior_net_change']) {
        assert.equal(children.reduce((sum, child) => sum + child[key], 0), row[key])
      }
      check(row.path)
    }
  }
  check([])
  assert.equal(total(group(rows, [])).opening_census, 100)
  assert.equal(group(rows, ['Texas', 'One', 'North']).length, 2)
  assert.equal(group(rows, ['Texas', 'One', 'North', 'Bay'])[0].admissions, 0)
})

test('incomplete prior history remains unavailable in parent and total rows', () => {
  const incomplete = rows.map(row => ({ ...row, prior_net_change: null }))
  assert.equal(total(group(incomplete, [])).prior_net_change, null)
  assert.equal(group(incomplete, ['Texas'])[0].prior_net_change, null)
})

 test('facility denominators include zero activity and weight totals by facilities', () => {
  const states = group(rows, [])
  const texas = states.find(row => row.name === 'Texas')
  assert.equal(texas.facilityCount, 3)
  assert.equal(texas.net_change / texas.facilityCount, -1 / 3)
  const combined = total(states)
  assert.equal(combined.facilityCount, 4)
  assert.equal(combined.net_change / combined.facilityCount, 1)
  assert.equal(combined.net_change / (combined.facilityCount * 30), 1 / 30)
  assert.equal(group(rows, ['Texas', 'One', 'North', 'Bay'])[0].facilityCount, 1)
})
