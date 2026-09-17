const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')
const { test } = require('node:test')

function harness() {
  const slots = []
  const pending = []
  let cursor = 0
  let effects = []
  const hooks = {
    useState(initial) {
      const index = cursor++
      if (!(index in slots)) slots[index] = initial
      return [slots[index], (next) => { slots[index] = typeof next === 'function' ? next(slots[index]) : next }]
    },
    useEffect(effect, deps) {
      const index = cursor++
      if (!slots[index] || deps.some((value, i) => value !== slots[index].deps[i])) {
        effects.push(() => { slots[index]?.cleanup?.(); slots[index] = { deps, cleanup: effect() } })
      }
    },
  }
  const cache = new Map()
  function load(file) {
    if (cache.has(file)) return cache.get(file)
    const exports = {}
    const source = readFileSync(file, 'utf8').replace('import.meta.env.VITE_API_BASE_URL', "'http://test'")
    const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
    vm.runInNewContext(code, {
      exports, URLSearchParams, AbortController,
      fetch(url, options) { return new Promise((resolve) => pending.push({ url, ...options, resolve })) },
      require(name) {
        return name === 'react' ? hooks : load(path.resolve(path.dirname(file), name + '.ts'))
      },
    })
    cache.set(file, exports)
    return exports
  }
  const { useTableFilterOptions: renderHook } = load(path.join(__dirname, '../src/shared/hooks/useTableFilterOptions.ts'))
  return { pending, render(...args) {
    cursor = 0
    effects = []
    const result = renderHook(...args)
    effects.forEach((effect) => effect())
    return result
  } }
}
const flush = () => new Promise((resolve) => setImmediate(resolve))
const source = { id: 'discharges', startDate: '2026-09-01', endDate: '2026-09-15' }
const success = (options) => ({ ok: true, json: async () => ({ options }) })

test('LOS changes cancel obsolete cascading options and forward both numeric conditions', async () => {
  const h = harness()
  const payerSource = { ...source, id: 'payer-changes' }
  h.render(payerSource, 'new_payer_type', { previous_los_days: [JSON.stringify(['greater-than', '10'])] }, '')
  const filters = { previous_los_days: [JSON.stringify(['greater-than', '10'])],
    new_los_days: [JSON.stringify(['between', '0', '20'])] }
  h.render(payerSource, 'new_payer_type', filters, '')
  assert.equal(h.pending[0].signal.aborted, true)
  assert.deepEqual(JSON.parse(new URL(h.pending[1].url).searchParams.get('filters')), filters)
  h.pending[1].resolve(success(['Medicaid']))
  await flush()
  assert.deepEqual(Array.from(h.render(payerSource, 'new_payer_type', filters, '').options), ['Medicaid'])
})

test('shared Table cancels stale option requests and reloads after filters or dates change', async () => {
  const h = harness()
  const first = [source, 'portfolio', { state: ['Texas'], portfolio: ['Texas 1'] }, '']
  assert.equal(h.render(...first).loading, true)
  assert.deepEqual(JSON.parse(new URL(h.pending[0].url).searchParams.get('filters')), { state: ['Texas'] })
  const second = [source, 'portfolio', { state: ['Florida'] }, '']
  h.render(...second)
  assert.equal(h.pending[0].signal.aborted, true)
  h.pending[1].resolve(success(['Florida 1']))
  await flush()
  assert.deepEqual(Array.from(h.render(...second).options), ['Florida 1'])
  h.pending[0].resolve(success(['Texas 1']))
  await flush()
  assert.deepEqual(Array.from(h.render(...second).options), ['Florida 1'])
  const third = [{ ...source, endDate: '2026-09-16' }, ...second.slice(1)]
  const refreshed = h.render(...third)
  assert.equal(refreshed.loading, true)
  assert.equal(refreshed.options.length, 0)
  assert.equal(h.pending.length, 3)
  h.render(undefined, null, {}, '')
  assert.equal(h.pending[2].signal.aborted, true)
})

test('shared Table shows retryable errors and does not refetch for its own selection', async () => {
  const h = harness()
  const args = [source, 'state', { payer_type: ['Medicaid'] }, '']
  h.render(...args)
  h.pending[0].resolve({ ok: false })
  await flush()
  const failed = h.render(...args)
  assert.match(failed.error, /Could not load/)
  assert.equal(failed.loading, false)
  failed.onRetry()
  assert.equal(h.render(...args).loading, true)
  h.pending[1].resolve(success(['Texas', 'Florida']))
  await flush()
  assert.equal(h.render(...args).error, null)
  h.render(source, 'state', { payer_type: ['Medicaid'], state: ['Texas'] }, '')
  assert.equal(h.pending.length, 2)
})
