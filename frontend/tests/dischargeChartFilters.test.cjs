const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')
const { test } = require('node:test')

for (const kind of ['Destination', 'Payer']) {
  test(`${kind} chart supports multiple selections, toggling off, and clearing`, () => {
    const exported = {}
    const file = `DischargesBy${kind}`
    const code = ts.transpileModule(readFileSync(path.join(__dirname,
      `../src/features/adt/components/${file}.tsx`), 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
    vm.runInNewContext(code, { exports: exported, require(name) {
      if (name === 'react') return { useState: (initial) => [initial, () => {}], useEffect: () => {} }
      if (name.includes('/charts/')) return { BarChartRanking: 'chart', DonutChart: 'chart' }
      if (name === '../api/discharges') return {}
      return require(name)
    } })
    let selected = []
    const render = () => exported[file]({ startDate: '2026-09-01', endDate: '2026-09-15', path: [],
      selected, payers: [], destinations: [], onChange: (values) => { selected = Array.from(values) } })
    render().props.onSelect('First')
    assert.deepEqual(selected, ['First'])
    render().props.onSelect('Second')
    assert.deepEqual(selected, ['First', 'Second'])
    assert.deepEqual(render().props.selectedLabels, selected)
    render().props.onSelect('First')
    assert.deepEqual(selected, ['Second'])
    render().props.onClear()
    assert.deepEqual(selected, [])
  })
}
