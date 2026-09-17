const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')
const { test } = require('node:test')
const exportsObject = {}
vm.runInNewContext(ts.transpileModule(readFileSync(path.join(__dirname,
  '../src/features/adt/utils/payerChangesDrilldown.ts'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText, { exports: exportsObject, URLSearchParams })
const { getPayerChangeRows: group, getPayerChangeTotal: total,
  payerChangeLogsParams: logs, getPayerChangeLogsFilters: filters } = exportsObject
const rows = [
  { facility_name: 'Oak', state: 'Texas', portfolio: 'Texas 1', region: 'North', total: 12, residents: 8, prior: 14 },
  { facility_name: 'Bay', state: 'Texas', portfolio: 'Texas 1', region: 'North', total: 0, residents: 0, prior: 1 },
  { facility_name: 'Pine', state: 'Texas', portfolio: 'Texas 2', region: 'North', total: 7, residents: 5, prior: 0 },
  { facility_name: 'Elm', state: 'Florida', portfolio: 'Florida 1', region: 'North', total: 3, residents: 2, prior: 9 },
]

test('hierarchy totals reconcile at all levels, retain zeros and isolate identical region names', () => {
  function check(path) {
    for (const parent of group(rows, path)) {
      if (parent.path.length === 4) continue
      const children = group(rows, parent.path)
      for (const key of ['total', 'residents', 'prior', 'change']) {
        assert.equal(children.reduce((sum, row) => sum + row[key], 0), parent[key])
      }
      check(parent.path)
    }
  }
  check([])
  const all = total(group(rows, []))
  assert.equal(all.total, 22)
  assert.equal(all.residents, 15)
  assert.equal(all.prior, 24)
  assert.equal(all.change, -2)
  assert.equal(all.facilityNames.length, 4)
  assert.equal(group(rows, ['Texas', 'Texas 1', 'North']).length, 2)
  assert.equal(group(rows, ['Texas', 'Texas 1', 'North', 'Bay'])[0].total, 0)
  assert.equal(total(group(rows, ['Florida'])), null)
})

test('slice links preserve dates and overview location while replacing previous log filters', () => {
  const initial = new URLSearchParams('start_date=2026-08-17&end_date=2026-09-15&payer_scope=Texas&logs_new_payer_type=Hospice')
  const next = logs(initial, { state: ['Texas'], previous_payer_type: ['Medicare'], new_payer_type: ['Medicaid'] })
  assert.equal(next.get('view'), 'logs')
  assert.equal(next.get('start_date'), '2026-08-17')
  assert.equal(next.get('payer_scope'), 'Texas')
  assert.deepEqual(JSON.parse(JSON.stringify(filters(next))), {
    state: ['Texas'], previous_payer_type: ['Medicare'], new_payer_type: ['Medicaid'], change_category: ['Payer type'],
  })
  const table = logs(next, { facility_name: ['Oak', 'Bay'] })
  assert.equal(table.has('logs_previous_payer_type'), false)
  assert.deepEqual(Array.from(table.getAll('logs_facility_name')), ['Oak', 'Bay'])
  assert.equal(initial.get('logs_new_payer_type'), 'Hospice')
})
