const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')
const { test } = require('node:test')
const exportsObject = {}
vm.runInNewContext(ts.transpileModule(readFileSync(path.join(__dirname,
  '../src/shared/utils/tableChange.ts'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText, { exports: exportsObject })
const { tableChange } = exportsObject

test('payer change volumes retain signs without implying good or bad performance', () => {
  assert.equal(tableChange(12, 'neutral').text, '+12')
  assert.equal(tableChange(-12, 'neutral').text, '-12')
  for (const value of [12, -12, 0, null]) {
    assert.equal(tableChange(value, 'neutral').className, undefined)
  }
})

test('admissions and discharges use the same favorable and adverse styles with opposite directions', () => {
  assert.equal(tableChange(12, 'increase').className, tableChange(-12, 'decrease').className)
  assert.equal(tableChange(-12, 'increase').className, tableChange(12, 'decrease').className)
  assert.notEqual(tableChange(12, 'increase').className, tableChange(12, 'decrease').className)
  for (const favorable of ['increase', 'decrease']) {
    assert.equal(tableChange(1234, favorable).text, '+1,234')
    assert.equal(tableChange(-1234, favorable).text, '-1,234')
    for (const value of [0, -0]) {
      assert.equal(tableChange(value, favorable).text, '0')
      assert.equal(tableChange(value, favorable).className, undefined)
    }
  }
})

test('unavailable comparison values remain neutral instead of looking favorable', () => {
  for (const favorable of ['increase', 'decrease']) {
    for (const value of [null, 'N/A', '—', NaN, Infinity]) {
      assert.equal(tableChange(value, favorable).className, undefined)
    }
    assert.equal(tableChange('N/A', favorable).text, 'N/A')
    assert.equal(tableChange(null, favorable).text, '—')
  }
})
