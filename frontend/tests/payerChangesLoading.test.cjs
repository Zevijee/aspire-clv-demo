const assert = require('node:assert/strict')
const { readFileSync, existsSync } = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')
const { test } = require('node:test')

// Exercise real component effects and API requests, with controlled response timing.
// Shared visual components are boundaries here; this does not assert browser layout.
function harness(componentName) {
  const instances = new Map()
  const pending = []
  let params = new URLSearchParams('start_date=2026-08-17&end_date=2026-09-15')
  let slots, cursor, effects
  const hooks = {
    useState(initial) {
      const state = slots, index = cursor++
      if (!(index in state)) state[index] = typeof initial === 'function' ? initial() : initial
      return [state[index], (next) => { state[index] = typeof next === 'function' ? next(state[index]) : next }]
    },
    useMemo(factory, deps) {
      const index = cursor++
      if (!slots[index] || deps.some((value, i) => value !== slots[index].deps[i])) {
        slots[index] = { deps, value: factory() }
      }
      return slots[index].value
    },
    useCallback(fn, deps) { return hooks.useMemo(() => fn, deps) },
    useEffect(effect, deps) {
      const state = slots, index = cursor++
      if (!state[index] || deps.some((value, i) => value !== state[index].deps[i])) {
        effects.push(() => { state[index]?.cleanup?.(); state[index] = { deps, cleanup: effect() } })
      }
    },
  }
  const cache = new Map()
  function load(filename) {
    if (cache.has(filename)) return cache.get(filename)
    const exports = {}
    cache.set(filename, exports)
    const code = ts.transpileModule(readFileSync(filename, 'utf8')
      .replace('import.meta.env.VITE_API_BASE_URL', "'http://test'"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
    vm.runInNewContext(code, { exports, URLSearchParams, AbortController,
      fetch(url, options) { return new Promise((resolve) => pending.push({ url, ...options, resolve })) },
      require(name) {
        if (name === 'react') return hooks
        if (name === 'react-router-dom') return { useSearchParams: () => [params, (next) => { params = next }] }
        if (name.includes('/shared/components/')) return {
          Table: 'Table', DrilldownNavigation: 'DrilldownNavigation', DonutChart: 'DonutChart',
        }
        if (name.includes('/shared/utils/reportDateRange')) return {
          getDefaultReportDateRange: () => ({ startDate: '2026-08-17', endDate: '2026-09-15' }),
        }
        if (name.startsWith('.')) {
          const base = path.resolve(path.dirname(filename), name)
          return load(['.tsx', '.ts'].map((ext) => base + ext).find(existsSync))
        }
        return require(name)
      },
    })
    return exports
  }
  const component = load(path.join(__dirname, `../src/features/adt/components/${componentName}.tsx`))[componentName]
  function renderNode(node, key = 'root') {
    if (Array.isArray(node)) return node.flatMap((child, i) => renderNode(child, `${key}/${child?.key ?? i}`))
    if (!node || typeof node !== 'object') return []
    if (typeof node.type === 'function') {
      const instanceKey = `${key}/${node.key ?? node.type.name}`
      if (!instances.has(instanceKey)) instances.set(instanceKey, [])
      slots = instances.get(instanceKey)
      cursor = 0
      return renderNode(node.type(node.props), instanceKey)
    }
    return [node, ...renderNode(node.props?.children, `${key}/children`)]
  }
  return {
    pending,
    setDates(start, end) { params = new URLSearchParams({ start_date: start, end_date: end }) },
    render() {
      effects = []
      const nodes = renderNode({ type: component, props: {} })
      effects.forEach((effect) => effect())
      return nodes
    },
  }
}
const flush = () => new Promise((resolve) => setImmediate(resolve))
const success = (data) => ({ ok: true, json: async () => data })
const charts = (nodes) => nodes.filter((node) => node.type === 'DonutChart')
const table = (nodes) => nodes.find((node) => node.type === 'Table')

test('overview mounts all seven sections immediately and each fills independently with retry', async () => {
  const h = harness('PayerChangesOverview')
  let nodes = h.render()
  assert.equal(charts(nodes).length, 6)
  assert.equal(h.pending.length, 7)
  assert.ok(table(nodes).props.loading)
  assert.ok(charts(nodes).every((chart) => chart.props.loading))
  h.pending[1].resolve(success([{ label: 'Medicaid', value: 15 }]))
  h.pending[2].resolve({ ok: false, status: 503 })
  await flush()
  nodes = h.render()
  assert.ok(table(nodes).props.loading)
  assert.equal(charts(nodes)[0].props.items[0].value, 15)
  assert.equal(charts(nodes)[0].props.loading, false)
  assert.match(charts(nodes)[1].props.error, /503/)
  assert.ok(charts(nodes)[2].props.loading)
  charts(nodes)[1].props.onRetry()
  nodes = h.render()
  assert.equal(charts(nodes)[1].props.loading, true)
  assert.equal(h.pending.length, 8)
  h.pending[7].resolve(success([]))
  await flush()
  assert.equal(charts(h.render())[1].props.error, null)
  assert.equal(charts(h.render())[1].props.loading, false)
})

test('date changes abort all obsolete sections and late responses cannot replace current results', async () => {
  const h = harness('PayerChangesOverview')
  h.render()
  const obsolete = [...h.pending]
  h.setDates('2026-09-01', '2026-09-10')
  const loading = h.render()
  assert.equal(h.pending.length, 14)
  assert.ok(obsolete.every((request) => request.signal.aborted))
  assert.ok(charts(loading).every((chart) => chart.props.loading))
  for (const request of h.pending.slice(7)) {
    request.resolve(success(request.url.includes('/overview') ? { items: [] } : [{ label: 'Medicaid', value: 4 }]))
  }
  await flush()
  for (const request of obsolete) request.resolve(success([{ label: 'Outdated', value: 99 }]))
  await flush()
  const current = h.render()
  assert.equal(table(current).props.loading, false)
  assert.ok(charts(current).every((chart) => chart.props.items[0].value === 4))
})

test('logs retain their table and pagination through search, failure, retry and empty results', async () => {
  const h = harness('PayerChangesLogs')
  let view = table(h.render())
  assert.ok(view.props.loading)
  assert.ok(view.props.footer)
  const los = view.props.columns.find((column) => column.id === 'new_los_days')
  const row = { new_los_days: 10, new_los_ongoing: true }
  assert.equal(los.value(row), 10)
  assert.equal(los.format(10, row), '10')
  assert.equal(los.format(1, row), '1')
  const status = view.props.columns.find((column) => column.id === 'status')
  assert.equal(status.filterable, true)
  assert.equal(status.value({ status: 'Ongoing' }), 'Ongoing')
  assert.equal(status.value({ status: 'Discharged' }), 'Discharged')
  view.props.onQueryChange({ filters: {}, sort: null, search: 'Medicaid' })
  view = table(h.render())
  assert.equal(h.pending[0].signal.aborted, true)
  assert.equal(new URL(h.pending[1].url).searchParams.get('search'), 'Medicaid')
  h.pending[1].resolve({ ok: false, status: 503 })
  await flush()
  view = table(h.render())
  assert.match(view.props.error, /503/)
  assert.ok(view.props.footer)
  view.props.onRetry()
  assert.equal(table(h.render()).props.loading, true)
  h.pending[2].resolve(success({ items: [], total: 0 }))
  h.pending[0].resolve(success({ items: [{ change_id: 'obsolete' }], total: 99 }))
  await flush()
  view = table(h.render())
  assert.equal(view.props.rows.length, 0)
  assert.equal(view.props.totalRows, 0)
  assert.equal(view.props.loading, false)
  assert.equal(view.props.error, null)
})
