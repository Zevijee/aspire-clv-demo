const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const path = require('node:path')
const { test } = require('node:test')
const vm = require('node:vm')
const ts = require('typescript')

const source = readFileSync(path.join(__dirname, '../src/features/adt/utils/admissionsLogNavigation.ts'), 'utf8')
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } })
const utility = { exports: {} }
const drilldown = { exports: {} }
const drilldownSource = readFileSync(path.join(__dirname, '../src/features/adt/utils/admissionsDrilldown.ts'), 'utf8')
vm.runInNewContext(ts.transpileModule(drilldownSource, {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText, { exports: drilldown.exports })
vm.runInNewContext(outputText, {
  exports: utility.exports, URLSearchParams,
  require: (name) => { assert.equal(name, './admissionsDrilldown'); return drilldown.exports },
})
const { getAdmissionLogsParams, getAdmissionLogsFilters, getHospitalAdmissionLogsParams } = utility.exports

const state = { state: 'Texas' }
const portfolio = { ...state, portfolio: 'Portfolio A' }
const region = { ...portfolio, region: 'North' }
const facility = { ...region, facility: 'Cedar & Elm' }

function navigate(row, scope) {
  return getAdmissionLogsParams(new URLSearchParams('view=testing&logs_facility=Old&logs_payer=Old'),
    row, scope, '2026-09-01', '2026-09-15', ['Medicare Advantage', 'Medicaid'], ['Hospital'])
}

test('each count opens Logs at its exact hierarchy with dates, payers, and sources', () => {
  for (const [scope, location] of [[null, state], [state, portfolio], [portfolio, region],
    [region, facility], [facility, facility]]) {
    const row = { name: location.facility ?? location.region ?? location.portfolio ?? location.state,
      state: location.state, portfolio: location.portfolio ?? '', region: location.region ?? null }
    const params = navigate(row, scope)
    assert.equal(params.get('view'), 'logs')
    assert.equal(params.get('start_date'), '2026-09-01')
    assert.equal(params.get('end_date'), '2026-09-15')
    for (const key of ['state', 'portfolio', 'region', 'facility']) {
      assert.equal(params.get(`logs_${key}`), location[key] ?? null)
    }
    assert.deepEqual(params.getAll('logs_payer'), ['Medicare Advantage', 'Medicaid'])
    const filters = getAdmissionLogsFilters(params)
    assert.equal(filters.payer.join(','), 'Managed Medicare,Medicaid')
    assert.equal(filters['source-type'].join(','), 'Hospital')
  }
})

test('total counts open the current parent scope, including all states', () => {
  for (const scope of [null, state, portfolio, region]) {
    const params = navigate({ isTotal: true, name: 'Total', state: '', portfolio: '', region: null }, scope)
    for (const key of ['state', 'portfolio', 'region', 'facility']) {
      assert.equal(params.get(`logs_${key}`), scope?.[key] ?? null)
    }
  }
})

test('ordinary Logs visits have no inherited drill-down filters', () => {
  assert.equal(Object.keys(getAdmissionLogsFilters(new URLSearchParams('view=logs'))).length, 0)
})

test('hospital admission links preserve scope and payer while selecting the exact hospital', () => {
  for (const scope of [null, state, portfolio, region, facility]) {
    const params = getHospitalAdmissionLogsParams(
      new URLSearchParams('logs_readmission=true&logs_admission-source=Old&logs_source-type=Home'),
      scope, '2026-09-01', '2026-09-15', ['Medicare Advantage'], 'Cedar & Elm Hospital',
    )
    assert.equal(params.get('view'), 'logs')
    assert.equal(params.get('start_date'), '2026-09-01')
    assert.equal(params.get('end_date'), '2026-09-15')
    for (const key of ['state', 'portfolio', 'region', 'facility']) {
      assert.equal(params.get(`logs_${key}`), scope?.[key] ?? null)
    }
    const filters = getAdmissionLogsFilters(params)
    assert.equal(filters['admission-source'].join(','), 'Cedar & Elm Hospital')
    assert.equal(filters['source-type'].join(','), 'Hospital')
    assert.equal(filters.payer.join(','), 'Managed Medicare')
    assert.equal(filters.readmission, undefined)
  }
})

test('readmission links retain the full scope and total-admission links clear readmission-only mode', () => {
  const row = { isTotal: true, name: 'Total' }
  for (const scope of [null, state, portfolio, region, facility]) {
    const params = getAdmissionLogsParams(new URLSearchParams(), row, scope,
      '2026-09-01', '2026-09-15', ['Medicare'], ['Hospital'], true)
    assert.equal(params.get('logs_readmission'), 'true')
    const filters = getAdmissionLogsFilters(params)
    assert.equal(filters.readmission.join(','), 'Yes')
    assert.equal(filters.payer.join(','), 'Medicare')
    assert.equal(filters['source-type'].join(','), 'Hospital')
    for (const key of ['state', 'portfolio', 'region', 'facility']) {
      assert.equal(params.get(`logs_${key}`), scope?.[key] ?? null)
    }
    const all = getAdmissionLogsParams(params, row, scope,
      '2026-09-01', '2026-09-15', [], [])
    assert.equal(all.has('logs_readmission'), false)
    assert.equal(getAdmissionLogsFilters(all).readmission, undefined)
  }
})


test('custom group totals, readmissions, and hospital links keep the exact selected facilities', () => {
  const facilities = ['Cedar', 'Elm', 'Bay']
  const row = { isTotal: true, facilityNames: facilities }
  const params = getAdmissionLogsParams(new URLSearchParams('logs_facility=Old'), row, null,
    '2026-09-01', '2026-09-15', ['Medicare'], ['Hospital'], true)
  assert.deepEqual(params.getAll('logs_facility'), facilities)
  assert.equal(params.get('logs_readmission'), 'true')
  const hospital = getHospitalAdmissionLogsParams(params, null, '2026-09-01', '2026-09-15',
    ['Medicare'], 'General Hospital', facilities)
  assert.deepEqual(hospital.getAll('logs_facility'), facilities)
  assert.equal(hospital.get('logs_admission-source'), 'General Hospital')
  assert.equal(hospital.has('logs_readmission'), false)
})

test('a facility row grouped across states opens its own facility, not its whole region', () => {
  const scope = { state: 'Texas', portfolio: 'Oak', region: 'North', facility: 'Cedar' }
  const row = { name: 'Cedar', scope, facilityNames: ['Cedar'] }
  const params = getAdmissionLogsParams(new URLSearchParams(), row, null,
    '2026-09-01', '2026-09-15', [], [])
  assert.equal(params.get('logs_state'), 'Texas')
  assert.deepEqual(params.getAll('logs_facility'), ['Cedar'])
})
