const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')
const { test } = require('node:test')
const source = readFileSync(path.join(__dirname, '../src/shared/utils/tableFilters.ts'), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
const exported = {}
vm.runInNewContext(compiled, { exports: exported })
const { matchesTableFilters, matchesTableSearch, otherTableFilters, tableFilterRequestKey } = exported
const plain = (value) => JSON.parse(JSON.stringify(value))
const rows = [
  { state: 'Texas', portfolio: 'Texas 1', payer: 'Medicare', resident: 'Alex' },
  { state: 'Texas', portfolio: 'Texas 2', payer: 'Medicaid', resident: 'Casey' },
  { state: 'Florida', portfolio: 'Florida 1', payer: 'Medicaid', resident: 'Alex' },
]
const columns = Object.keys(rows[0]).map((id) => ({ id, value: (row) => row[id] }))

test('shared local options respect every other column and search, with OR within a column', () => {
  const filters = { state: ['Texas', 'Florida'], payer: ['Medicaid'], portfolio: ['Texas 2'] }
  const choices = rows.filter((row) => matchesTableFilters(row, columns, filters, 'portfolio'))
  assert.deepEqual(choices.map((row) => row.portfolio), ['Texas 2', 'Florida 1'])
  assert.deepEqual(choices.filter((row) => matchesTableSearch(row, columns, ' aLeX '))
    .map((row) => row.portfolio), ['Florida 1'])
  assert.deepEqual(rows.filter((row) => matchesTableFilters(row, columns, filters))
    .map((row) => row.portfolio), ['Texas 2'])
})

test('shared server requests exclude only their own column, retain hidden filters, and do not mutate selections', () => {
  const filters = { state: ['Texas'], payer: ['Medicaid'], facility: ['B', 'A', 'A'], empty: [] }
  assert.deepEqual(plain(otherTableFilters(filters, 'state')), { facility: ['A', 'B'], payer: ['Medicaid'] })
  assert.deepEqual(filters.facility, ['B', 'A', 'A'])
  const source = { id: 'admissions', startDate: '2026-09-01', endDate: '2026-09-15' }
  const key = tableFilterRequestKey(source, 'state', filters, 'Alex')
  assert.equal(key, tableFilterRequestKey(source, 'state', { ...filters, state: ['Florida'] }, 'Alex'))
  for (const [nextSource, column, nextFilters, search] of [
    [{ ...source, id: 'discharges' }, 'state', filters, 'Alex'],
    [{ ...source, endDate: '2026-09-16' }, 'state', filters, 'Alex'],
    [source, 'payer', filters, 'Alex'],
    [source, 'state', { ...filters, payer: ['Medicare'] }, 'Alex'],
    [source, 'state', filters, 'Casey'],
  ]) assert.notEqual(key, tableFilterRequestKey(nextSource, column, nextFilters, search))
})
