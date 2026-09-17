const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const path = require('node:path')
const { test } = require('node:test')
const vm = require('node:vm')
const ts = require('typescript')

const source = readFileSync(path.join(__dirname, '../src/shared/utils/reportDateRange.ts'), 'utf8')
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, esModuleInterop: true },
})
const utility = { exports: {} }
vm.runInNewContext(outputText, { exports: utility.exports, require })

const cases = [
  ['Eastern evening after UTC midnight', 'America/New_York', '2026-09-11T01:00:00Z', '2026-08-12', '2026-09-10'],
  ['Eastern local midnight', 'America/New_York', '2026-09-11T04:00:00Z', '2026-08-13', '2026-09-11'],
  ['Ahead of UTC', 'Asia/Tokyo', '2026-09-10T16:00:00Z', '2026-08-13', '2026-09-11'],
  ['Spring daylight-saving transition', 'America/New_York', '2026-03-09T01:00:00Z', '2026-02-07', '2026-03-08'],
  ['Fall daylight-saving transition', 'America/New_York', '2026-11-02T02:00:00Z', '2026-10-03', '2026-11-01'],
  ['Year boundary', 'America/New_York', '2027-01-01T02:00:00Z', '2026-12-02', '2026-12-31'],
]

for (const [name, timezone, instant, startDate, endDate] of cases) {
  test(name, () => {
    const originalTimezone = process.env.TZ
    try {
      process.env.TZ = timezone
      const now = new Date(instant)
      const result = utility.exports.getDefaultReportDateRange(now)
      assert.equal(result.startDate, startDate)
      assert.equal(result.endDate, endDate)
      assert.equal(now.toISOString(), instant.replace('Z', '.000Z'))
    } finally {
      if (originalTimezone === undefined) delete process.env.TZ
      else process.env.TZ = originalTimezone
    }
  })
}
