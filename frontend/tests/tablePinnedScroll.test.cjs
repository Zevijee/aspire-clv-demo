const assert = require('node:assert/strict')
const { test } = require('node:test')
const { readFileSync } = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')

test('pinned table scrollbar covers only moving columns and synchronizes scrolling and resizing', () => {
  const slots = []; let cursor = 0; let layouts = []; let observer
  const hooks = {
    useState(initial) { const i = cursor++; if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial
      return [slots[i], next => { slots[i] = typeof next === 'function' ? next(slots[i]) : next }] },
    useRef(initial) { return hooks.useState({ current: initial })[0] },
    useId() { return 'table-test' }, useMemo(fn) { return fn() },
    useEffect() {}, useLayoutEffect(fn) { layouts.push(fn) },
  }
  const exported = {}
  const code = ts.transpileModule(readFileSync(path.join(__dirname, '../src/shared/components/Table.tsx'), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText
  vm.runInNewContext(code, { exports: exported,
    ResizeObserver: class { constructor(fn) { this.measure = fn; observer = this } observe() {} disconnect() {} },
    require(name) {
      if (name === 'react') return hooks
      if (name.includes('useTableFilterOptions')) return { useTableFilterOptions: () => ({ options: [] }) }
      if (name.includes('tableFilters')) return { matchesTableFilters: () => true, matchesTableSearch: () => true }
      if (name.includes('tableChange')) return {}
      if (name.startsWith('.')) return { BooleanBadge: 'badge', DataState: 'state', MultiSelectFilterOptions: 'options' }
      return require(name)
    },
  })
  const props = { title: 'Logs', subtitle: '', columns: [{ id: 'resident', header: 'Resident', value: r => r.name }],
    rows: [], getRowKey: r => r.name, emptyMessage: 'Empty', stickyFirstColumn: true, internalScroll: true }
  function nodes(tree) { return Array.isArray(tree) ? tree.flatMap(nodes) : !tree || typeof tree !== 'object' ? [] : [tree, ...nodes(tree.props?.children)] }
  function render() { cursor = 0; layouts = []; return nodes(exported.Table(props)) }
  let tree = render()
  const findBar = tree => tree.find(n => n.props?.className === 'report-table__horizontal-scroll')
  const scrollerNode = tree.find(n => n.props?.className?.includes('report-table__scroll--pinned'))
  const listeners = {}; let pinnedWidth = 180
  const first = { getBoundingClientRect: () => ({ width: pinnedWidth }) }
  const table = { querySelector: () => first }
  const scroller = { clientWidth: 780, scrollWidth: 1380, scrollLeft: 0, querySelector: () => table,
    addEventListener: (name, fn) => { listeners[name] = fn }, removeEventListener: name => { delete listeners[name] } }
  const bar = { scrollLeft: 0 }
  scrollerNode.props.ref.current = scroller
  findBar(tree).props.ref.current = bar
  const cleanup = layouts[0]()
  tree = render()
  assert.equal(findBar(tree).props.style.marginLeft, 180)
  assert.equal(findBar(tree).props.style.width, 600)
  assert.equal(findBar(tree).props.children.props.style.width, 1200)
  bar.scrollLeft = 300
  findBar(tree).props.onScroll({ currentTarget: bar })
  assert.equal(scroller.scrollLeft, 300)
  let prevented = false
  listeners.wheel({ deltaX: 50, deltaY: 0, deltaMode: 0, preventDefault() { prevented = true } })
  assert.ok(prevented)
  assert.equal(scroller.scrollLeft, 350)
  assert.equal(bar.scrollLeft, 350)
  scroller.scrollLeft = 100; listeners.scroll()
  assert.equal(bar.scrollLeft, 100)
  pinnedWidth = 220; scroller.clientWidth = 900; observer.measure()
  tree = render()
  assert.equal(findBar(tree).props.style.marginLeft, 220)
  assert.equal(findBar(tree).props.style.width, 680)
  assert.equal(findBar(tree).props.children.props.style.width - 680, 480)
  scroller.scrollWidth = 900; observer.measure()
  assert.equal(findBar(render()).props.style.display, 'none')
  cleanup()
  assert.equal(Object.keys(listeners).length, 0)
})
