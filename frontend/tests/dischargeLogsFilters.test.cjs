const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')
const { test } = require('node:test')
const exportsObject = {}
vm.runInNewContext(ts.transpileModule(readFileSync(path.join(__dirname,
  '../src/features/adt/utils/dischargeLogsFilters.ts'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText, { exports: exportsObject, URLSearchParams })
const { dischargeLogsParams, getDischargeLogsFilters } = exportsObject

test('count links preserve dates and chart selections and replace stale log filters', () => {
  const current = new URLSearchParams('start_date=2026-09-01&end_date=2026-09-15&logs_discharge_type=AMA')
  for (const count of ['total', 'ama', 'hospitalTransfers']) {
    const params = dischargeLogsParams(current, ['Oak', 'Bay'],
      { payers: ['Medicare', 'Managed Medicare'], destinations: ['Home', 'Hospital'] }, count)
    const filters = JSON.parse(JSON.stringify(getDischargeLogsFilters(params)))
    assert.equal(params.get('view'), 'logs')
    assert.equal(params.get('start_date'), '2026-09-01')
    assert.equal(params.get('end_date'), '2026-09-15')
    assert.deepEqual(filters.facility_name, ['Oak', 'Bay'])
    assert.deepEqual(filters.payer_type, ['Medicare', 'Managed Medicare'])
    assert.deepEqual(filters.destination_type, count === 'hospitalTransfers' ? ['Hospital'] : ['Home', 'Hospital'])
    assert.deepEqual(filters.discharge_type, count === 'total' ? undefined : count === 'ama' ? ['AMA'] : ['Transfer'])
  }
  assert.equal(current.get('logs_discharge_type'), 'AMA')
})

test('clearing drilldown parameters produces an unfiltered logs query', () => {
  assert.deepEqual(JSON.parse(JSON.stringify(getDischargeLogsFilters(
    new URLSearchParams('view=logs&start_date=2026-09-01')))), {})
})
