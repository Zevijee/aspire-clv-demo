const assert = require('node:assert/strict')
const { readFileSync, existsSync } = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')
const { test } = require('node:test')

// Exercise the actual component callbacks with deterministic hook storage.
// This checks state transitions; browser layout/focus still require visual verification.
function harness(file, exportName, initialProps) {
  const slots = []
  let cursor = 0
  let props = initialProps
  const hooks = {
    useState(initial) {
      const index = cursor++
      if (!(index in slots)) slots[index] = typeof initial === 'function' ? initial() : initial
      return [slots[index], (next) => { slots[index] = typeof next === 'function' ? next(slots[index]) : next }]
    },
    useRef(initial) { const [ref] = hooks.useState({ current: initial }); return ref },
    useId() { return `test-${cursor++}` },
    useMemo(factory) { return factory() },
  }
  const cache = new Map()
  function load(filename) {
    if (cache.has(filename)) return cache.get(filename)
    const exports = {}
    cache.set(filename, exports)
    const code = ts.transpileModule(readFileSync(filename, 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
    vm.runInNewContext(code, { exports, require(name) {
      if (name === 'react') return hooks
      if (name === 'antd') return { Drawer: 'drawer' }
      if (name.startsWith('.')) {
        const base = path.resolve(path.dirname(filename), name)
        return load(['.tsx', '.ts'].map((extension) => base + extension).find(existsSync))
      }
      return require(name)
    } })
    return exports
  }
  const component = load(path.join(__dirname, '../src', file))[exportName]
  return {
    render() { cursor = 0; return component(props) },
    update(next) { props = { ...props, ...next } },
  }
}
function nodes(tree) {
  if (Array.isArray(tree)) return tree.flatMap(nodes)
  if (!tree || typeof tree !== 'object') return []
  return [tree, ...nodes(tree.props?.children)]
}
function find(tree, predicate) { const node = nodes(tree).find(predicate); assert.ok(node); return node }
function text(tree) {
  if (typeof tree === 'boolean') return ''
  if (Array.isArray(tree)) return tree.map(text).join('')
  return tree && typeof tree === 'object' ? text(tree.props?.children) : String(tree ?? '')
}
const plain = (value) => JSON.parse(JSON.stringify(value))

test('switching levels restores ten facility selections and applying an empty level remains possible', () => {
  const chosen = Array.from({ length: 10 }, (_, i) => JSON.stringify(['Texas', 'Oak', 'North', `Facility ${i}`]))
  let settings = { level: ['facility'], scope: [] }
  let values = chosen
  const picker = harness('features/adt/components/AdmissionsLocationPicker.tsx', 'AdmissionsLocationPicker', {
    locations: [], values, settings,
    onChange(next) { values = next; picker.update({ values }) },
    onSettingsChange(next) { settings = { ...settings, ...next }; picker.update({ settings }) },
  })
  const segment = (value) => find(picker.render(), (node) => node.type === 'input' && node.props.type === 'radio' && node.props.value === value)
  assert.equal(segment('facility').props.checked, true)
  segment('region').props.onChange()
  assert.deepEqual(plain(values), [])
  assert.equal(settings.level[0], 'region')
  assert.equal(segment('region').props.checked, true)
  segment('facility').props.onChange()
  assert.deepEqual(plain(values), chosen)
})

test('both bulk buttons stay visible and select or unselect every option even during search', () => {
  const options = [
    { label: 'Cedar', value: 'cedar' }, { label: 'Cedar Grove', value: 'grove' }, { label: 'Bay', value: 'bay' },
  ]
  let values = ['bay']
  const picker = harness('shared/components/filters/FilterValuePicker.tsx', 'FilterValuePicker', {
    label: 'Facilities', options, values,
    onChange(next) { values = next; picker.update({ values }) },
  })
  const input = () => find(picker.render(), (node) => node.type === 'input' && node.props.type === 'search')
  const click = (label) => find(picker.render(), (node) => node.type === 'button' && text(node) === label).props.onClick()
  input().props.onChange({ target: { value: 'Cedar' } })
  const buttonLabels = () => nodes(picker.render()).filter((node) => node.type === 'button').map(text)
  assert.deepEqual(buttonLabels(), ['Select all', 'Unselect all'])
  click('Select all')
  assert.deepEqual(plain(values), ['cedar', 'grove', 'bay'])
  click('Select all')
  assert.deepEqual(plain(values), ['cedar', 'grove', 'bay'])
  click('Unselect all')
  assert.deepEqual(plain(values), [])
  assert.deepEqual(buttonLabels(), ['Select all', 'Unselect all'])
  assert.equal(input().props.value, 'Cedar')
})

test('grouping-only changes enable Apply, Cancel discards drafts, and Clear all commits immediately', () => {
  const applied = []
  const bar = harness('shared/components/filters/TabFilterBar.tsx', 'TabFilterBar', {
    settings: { level: ['state'], scope: [] },
    filters: [{ id: 'location', label: 'Location', options: [], values: [],
      renderPicker: (props) => ({ type: 'picker', props }) }],
    onApplyFilters: (values) => applied.push(values),
  })
  const open = () => find(bar.render(), (node) => node.type === 'button' && node.props.className === 'tab-filter-bar__toggle').props.onClick()
  const drawer = () => find(bar.render(), (node) => node.type === 'drawer')
  const button = (label) => find(drawer().props.footer, (node) => node.type === 'button' && text(node) === label)
  open()
  assert.equal(button('Apply filters').props.disabled, true)
  find(bar.render(), (node) => node.type === 'picker').props.onSettingsChange({ level: ['facility'] })
  assert.equal(button('Apply filters').props.disabled, false)
  assert.ok(text(drawer().props.footer).includes('Unapplied changes'))
  button('Cancel').props.onClick()
  assert.equal(applied.length, 0)
  open()
  assert.equal(button('Apply filters').props.disabled, true)
  find(bar.render(), (node) => node.type === 'picker').props.onSettingsChange({ level: ['facility'] })
  button('Apply filters').props.onClick()
  assert.equal(applied[0].level[0], 'facility')
  assert.deepEqual(plain(applied[0].location), [])
  assert.equal(drawer().props.open, false)
  open()
  const picker = find(bar.render(), (node) => node.type === 'picker')
  picker.props.onChange(['one facility'])
  button('Clear all').props.onClick()
  assert.deepEqual(plain(applied[1].location), [])
  assert.deepEqual(plain(applied[1].scope), [])
  assert.equal(drawer().props.open, false)
})

test('switching category tabs retains mounted picker instances', () => {
  const bar = harness('shared/components/filters/TabFilterBar.tsx', 'TabFilterBar', {
    filters: ['location', 'payer', 'source'].map((id) => ({ id, label: id, values: [], options: [] })),
  })
  find(bar.render(), (node) => node.props.className === 'tab-filter-bar__toggle').props.onClick()
  const before = nodes(bar.render()).filter((node) => node.props?.role === 'tabpanel')
  find(bar.render(), (node) => node.props.role === 'tab' && text(node) === 'payer').props.onClick()
  const after = nodes(bar.render()).filter((node) => node.props?.role === 'tabpanel')
  assert.equal(after.length, 3)
  assert.deepEqual(after.map((node) => node.key), before.map((node) => node.key))
  assert.equal(after[0].props.hidden, true)
  assert.equal(after[1].props.hidden, false)
})
