import { type ExportExtra } from '../../shared/exportExtensions'
import { getEmployeesPacked } from './api'

/** The Staffing Overview's employee windows, for its HTML export: the file
 * carries every employee of the range (getEmployeesPacked, some 3-4 MB) and
 * this script, so a role's or department's name, or an overtime figure,
 * opens the same list the page opens -- filtered to its row, sortable and
 * filterable by column, searchable and paged -- in the browser, with no API.
 * The links say what they stand for in their data-employees attribute
 * (drillLinks). */
export async function employeesExportExtra(startDate: string, endDate: string): Promise<ExportExtra> {
  const data = await getEmployeesPacked(startDate, endDate)
  // In a script element, `</script>` in a name would end it: every `<` escaped.
  const json = JSON.stringify(data).replace(/</g, '\\u003c')
  return {
    css: WINDOW_CSS,
    html: `<script type="application/json" id="report-employees-data">${json}</script>`,
    // The function's own source, run in the file: it reads nothing outside itself.
    script: `(${employeesWindow.toString()})()`,
  }
}

const WINDOW_CSS = `
.report-export button[data-employees] { cursor: pointer; pointer-events: auto; }
.xw-overlay { align-items: stretch; background: rgba(15, 23, 42, 0.45); display: flex; inset: 0; justify-content: center;
  padding: 24px; position: fixed; z-index: 1000; }
.xw-panel { background: var(--color-canvas); border-radius: 10px; display: flex; flex-direction: column; gap: 12px;
  max-width: 100%; padding: 16px 20px 20px; width: 100%; }
.xw-head { align-items: center; display: flex; justify-content: space-between; }
.xw-head h2 { font-size: 1rem; margin: 0; }
.xw-close { background: none; border: 0; color: var(--color-text-muted); cursor: pointer; font-size: 1.4rem; line-height: 1; }
.xw-panel .report-table { display: flex; flex: 1; flex-direction: column; min-height: 0; }
.xw-panel .report-table__header { align-items: center; display: flex; justify-content: space-between; gap: 12px; }
.xw-actions { align-items: center; display: flex; gap: 8px; }
.xw-search { border: 1px solid var(--color-border); border-radius: 6px; font: inherit; font-size: 0.8125rem;
  min-height: 32px; padding: 0 10px; width: 260px; }
.xw-scroll { flex: 1; min-height: 0; overflow: auto !important; }
/* No padding of its own: the app's header block inside (report-table__column-header) pads it, as in the app. */
.xw-scroll thead th { background: var(--color-surface-subtle); color: var(--color-text-muted); cursor: pointer;
  font-size: 0.6875rem; font-weight: 600; padding: 0; position: sticky; text-align: left; top: 0; z-index: 1;
  white-space: nowrap; }
.xw-scroll thead th.report-table__numeric { text-align: right; }
.xw-scroll td, .xw-scroll tbody th { white-space: nowrap; }
/* The employee's name held at the left as the columns scroll, as in the app. */
.xw-scroll tbody th { background: var(--color-table-pinned-background); left: 0; position: sticky; z-index: 1; }
.xw-scroll thead th:first-child { left: 0; z-index: 2; }
.xw-scroll tbody tr:hover { background: var(--color-surface-hover); }
.xw-pages { align-items: center; border-top: 1px solid var(--color-border); display: flex; font-size: 0.8125rem;
  gap: 8px; justify-content: space-between; padding: 10px 16px; }
.xw-pages button { background: none; border: 1px solid var(--color-border); border-radius: 6px; cursor: pointer;
  font: inherit; min-width: 32px; padding: 4px 8px; }
.xw-pages button:disabled { cursor: default; opacity: 0.4; }
`

/** Runs in the exported file, from its source text: everything it needs is
 * inside it. Opens the employee window for a clicked data-employees link. */
function employeesWindow() {
  const source = document.getElementById('report-employees-data')
  if (!source) return
  const data = JSON.parse(source.textContent || '{}')
  type Value = string | number
  type Item = Record<string, Value>
  const items: Item[] = data.rows.map((row: Value[]) => {
    const [name, facilityIndex, role, type, left, gone, hired, shifts, hours, wages, overtime, holiday, bonuses] = row
    const [facility, state, portfolio, region] = data.facilities[facilityIndex as number]
    const [roleLabel, department] = data.roles[role as string]
    const rate = (hours as number) > 0 ? (wages as number) / (hours as number) : 0
    return { name, facility, facilityLabel: `${facility} · ${state}`, state, portfolio, region, role, roleLabel, department, type,
      status: left ? `Left ${new Date(`${gone}T00:00:00Z`).toLocaleDateString('en-US',
        { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' })}` : 'Active',
      // What the Status filter offers, as the app's does: Active or Left, not each day.
      statusGroup: left ? 'Left' : 'Active', agency: type === 'Agency' ? 'Yes' : 'No', hired, shifts, hours, wages,
      overtime, holiday, bonuses, rate, perWeek: (hours as number) / data.weeks,
      overtimePremium: (overtime as number) * rate * data.overtime_premium,
      overtimeShare: (hours as number) > 0 ? (overtime as number) / (hours as number) : 0 }
  })
  type Kind = 'text' | 'date' | 'int' | 'tenths' | 'cents' | 'dollars' | 'share'
  const allColumns: [string, string, Kind][] = [
    ['name', 'Employee', 'text'], ['status', 'Status', 'text'], ['facilityLabel', 'Facility', 'text'],
    ['department', 'Department', 'text'], ['roleLabel', 'Role', 'text'], ['type', 'Type', 'text'],
    ['agency', 'Agency', 'text'], ['hired', 'Hired', 'date'], ['rate', 'Avg. hourly rate', 'cents'],
    ['shifts', 'Shifts', 'int'], ['hours', 'Hours worked', 'tenths'], ['perWeek', 'Hours / week', 'tenths'],
    ['overtime', 'Overtime hours', 'tenths'], ['overtimePremium', 'Overtime premium', 'dollars'],
    ['holiday', 'Holiday premium', 'dollars'], ['bonuses', 'Bonuses', 'dollars'], ['wages', 'Wages', 'dollars'],
  ]
  const overtimeColumns: [string, string, Kind][] = [
    ['name', 'Employee', 'text'], ['facilityLabel', 'Facility', 'text'], ['roleLabel', 'Role', 'text'], ['type', 'Type', 'text'],
    ['shifts', 'Shifts', 'int'], ['hours', 'Hours worked', 'tenths'], ['overtime', 'Overtime hours', 'tenths'],
    ['overtimeShare', 'Overtime share', 'share'], ['rate', 'Avg. hourly rate', 'cents'],
    ['overtimePremium', 'Overtime premium', 'dollars'],
  ]
  const filterFields: Record<string, string> = { state: 'state', portfolio: 'portfolio', region: 'region',
    facility: 'facility', department: 'department', role: 'roleLabel' }
  const searched = ['name', 'facility', 'state', 'portfolio', 'region', 'department', 'roleLabel', 'type', 'status']
  // The columns with a filter menu, as in the app, and the field each filters on.
  const columnFilters: Record<string, string> = { status: 'statusGroup', facilityLabel: 'facilityLabel',
    department: 'department', roleLabel: 'roleLabel', type: 'type', agency: 'agency' }
  // The app's sort and filter icons (Table).
  const sortIcon = (direction?: 'ascending' | 'descending') => `<svg aria-hidden="true" class="report-table__sort-icon" `
    + `fill="none" viewBox="0 0 24 24"><path d="${direction === 'ascending' ? 'm8 11 4-4 4 4M12 7v14'
      : direction === 'descending' ? 'm8 13 4 4 4-4M12 17V3' : 'm8 7 4-4 4 4M16 17l-4 4-4-4'}" /></svg>`
  const filterIcon = '<svg aria-hidden="true" class="report-table__filter-icon" fill="none" viewBox="0 0 24 24">'
    + '<path d="M4 5h16l-6 7v5l-4 2v-7z" /></svg>'
  const escape = (text: string) => text.replace(/[&<>"]/g, character =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[character] ?? character)
  const number = (value: number, digits: number) => value.toLocaleString(undefined,
    { minimumFractionDigits: digits, maximumFractionDigits: digits })
  const format = (value: Value, kind: Kind) => {
    if (kind === 'text') return escape(String(value))
    if (kind === 'date') return new Date(`${value}T00:00:00Z`).toLocaleDateString('en-US',
      { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' })
    const amount = value as number
    if (kind === 'int') return number(amount, 0)
    if (kind === 'tenths') return number(amount, 1)
    if (kind === 'cents') return `$${number(amount, 2)}`
    if (kind === 'dollars') return `$${number(Math.round(amount), 0)}`
    return `${number(amount * 100, 1)}%`
  }
  const PAGE = 50

  const open = (scope: { name: string; roles: string[]; filters: Record<string, string[]>; overtime: boolean }) => {
    const columns = scope.overtime ? overtimeColumns : allColumns
    const inScope = items.filter(item => (!scope.overtime || (item.overtime as number) > 0)
      && (!scope.roles.length || scope.roles.includes(item.role as string))
      && Object.entries(scope.filters).every(([key, values]) =>
        !filterFields[key] || values.includes(String(item[filterFields[key]]))))
    let sortKey = scope.overtime ? 'overtime' : 'hours'
    let descending = true
    let search = ''
    let page = 0
    // Each filtered column's ticked values; none ticked is every value.
    const picked: Record<string, Set<string>> = {}

    const overlay = document.createElement('div')
    overlay.className = 'xw-overlay'
    overlay.setAttribute('role', 'dialog')
    overlay.setAttribute('aria-modal', 'true')
    overlay.innerHTML = `<div class="xw-panel">
      <div class="xw-head"><h2>${escape(`${scope.overtime ? 'Overtime' : 'Employees'} · ${scope.name}`)}</h2>
        <button type="button" class="xw-close" aria-label="Close">×</button></div>
      <section class="report-table">
        <header class="report-table__header"><div class="report-table__heading">
          <h2 class="report-table__title">${scope.overtime ? 'Employees with overtime' : 'Employees'}</h2>
          <p class="report-table__subtitle xw-count"></p></div>
          <div class="xw-actions"><button type="button" class="report-table__clear-filters xw-clear">Clear filters</button>
          <input class="xw-search" type="search" placeholder="Search all columns…" aria-label="Search"></div></header>
        <div class="report-table__scroll xw-scroll"><table class="report-table__table"><thead><tr>${columns.map(([key, header, kind]) => {
          const numeric = !(kind === 'text' || kind === 'date')
          return `<th data-key="${key}" scope="col" class="${numeric ? 'report-table__numeric' : ''}">`
            + `<div class="report-table__column-header${numeric ? ' report-table__column-header--numeric' : ''}">`
            + `<button type="button" class="report-table__sort-button" aria-label="Sort by ${header}"><span>${header}</span>`
            + `<span class="xw-sort"></span></button>`
            + (columnFilters[key] ? `<div class="report-table__filter-menu"><button type="button" class="report-table__filter-button" `
              + `data-filter="${key}" aria-label="Filter ${header}">${filterIcon}</button></div>` : '')
            + '</div></th>'
        }).join('')}
        </tr></thead><tbody></tbody></table></div>
        <footer class="xw-pages"><span class="xw-summary"></span><span>
          <button type="button" data-step="-1" aria-label="Previous page">‹</button>
          <button type="button" data-step="1" aria-label="Next page">›</button></span></footer>
      </section></div>`
    document.body.appendChild(overlay)
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const render = () => {
      const text = search.trim().toLowerCase()
      const matching = inScope.filter(item => (!text || searched.some(key => String(item[key]).toLowerCase().includes(text)))
        && Object.entries(picked).every(([key, values]) => !values.size || values.has(String(item[columnFilters[key]]))))
      const textual = typeof (matching[0] ?? {})[sortKey] === 'string'
      const sorted = [...matching].sort((a, b) => {
        const order = textual ? String(a[sortKey]).localeCompare(String(b[sortKey]))
          : (a[sortKey] as number) - (b[sortKey] as number)
        return descending ? -order : order
      })
      const pages = Math.max(1, Math.ceil(sorted.length / PAGE))
      page = Math.min(page, pages - 1)
      overlay.querySelector('tbody')!.innerHTML = sorted.length ? sorted.slice(page * PAGE, page * PAGE + PAGE).map(item =>
        `<tr>${columns.map(([key, , kind], index) => index === 0
          ? `<th scope="row">${format(item[key], kind)}</th>`
          : `<td class="${kind === 'text' || kind === 'date' ? '' : 'report-table__numeric'}">${format(item[key], kind)}</td>`)
          .join('')}</tr>`).join('')
        : `<tr><td class="report-table__empty" colspan="${columns.length}">No employees match your search and selected filters.</td></tr>`
      overlay.querySelectorAll<HTMLElement>('thead th').forEach(cell => {
        const key = cell.dataset.key!
        const direction = key === sortKey ? (descending ? 'descending' : 'ascending') : undefined
        cell.setAttribute('aria-sort', direction ?? 'none')
        cell.querySelector('.xw-sort')!.innerHTML = sortIcon(direction)
        cell.querySelector('[data-filter]')?.classList.toggle('report-table__filter-button--active', Boolean(picked[key]?.size))
      })
      const filtered = Boolean(text) || Object.values(picked).some(values => values.size > 0)
      overlay.querySelector<HTMLElement>('.xw-clear')!.style.display = filtered ? '' : 'none'
      overlay.querySelector('.xw-count')!.textContent = filtered
        ? `Showing ${sorted.length.toLocaleString()} of ${inScope.length.toLocaleString()} employees`
        : `Showing ${sorted.length.toLocaleString()} employees`
      overlay.querySelector('.xw-summary')!.textContent =
        `Page ${page + 1} of ${pages} — ${sorted.length.toLocaleString()} employees`
      const [back, next] = overlay.querySelectorAll<HTMLButtonElement>('[data-step]')
      back.disabled = page === 0
      next.disabled = page + 1 >= pages
    }

    // A column's filter menu: the app's, its values ticked or not, with its own search.
    let menu: HTMLElement | null = null
    const closeMenu = () => { menu?.remove(); menu = null }
    const openMenu = (button: HTMLElement, key: string) => {
      const reopening = menu?.dataset.key === key
      closeMenu()
      if (reopening) return
      const values = picked[key] ??= new Set()
      const options = [...new Set(inScope.map(item => String(item[columnFilters[key]])))]
        .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))
      const header = columns.find(([column]) => column === key)![1]
      menu = document.createElement('div')
      menu.className = 'report-table__filter-options'
      menu.dataset.key = key
      menu.setAttribute('role', 'dialog')
      menu.setAttribute('aria-label', `Filter ${header}`)
      menu.innerHTML = `<label class="multi-select-filter__search"><input type="search" placeholder="Search ${escape(header)}"></label>
        <div class="multi-select-filter__actions"><button type="button" data-all>Select all</button>
        <button type="button" class="multi-select-filter__clear" data-none>Clear</button></div>
        <div class="multi-select-filter__list"></div>`
      const find = menu.querySelector('input')!
      const all = menu.querySelector<HTMLButtonElement>('[data-all]')!
      const list = menu.querySelector<HTMLElement>('.multi-select-filter__list')!
      const shown = () => options.filter(option => option.toLowerCase().includes(find.value.trim().toLowerCase()))
      const draw = () => {
        const visible = shown()
        all.textContent = find.value.trim() ? 'Select matches' : 'Select all'
        all.disabled = !visible.length
        list.innerHTML = visible.length ? visible.map(option => `<label class="multi-select-filter__option">`
          + `<input type="checkbox" value="${escape(option)}"${values.has(option) ? ' checked' : ''}>`
          + `<span>${escape(option)}</span></label>`).join('')
          : '<p class="multi-select-filter__empty">No matching options.</p>'
      }
      const changed = () => { page = 0; draw(); render() }
      find.addEventListener('input', draw)
      list.addEventListener('change', event => {
        const box = event.target as HTMLInputElement
        if (box.checked) values.add(box.value)
        else values.delete(box.value)
        page = 0
        render()
      })
      all.addEventListener('click', () => {
        if (!find.value.trim()) values.clear()
        shown().forEach(option => values.add(option))
        changed()
      })
      menu.querySelector('[data-none]')!.addEventListener('click', () => { values.clear(); changed() })
      draw()
      overlay.appendChild(menu)
      const bounds = button.getBoundingClientRect()
      menu.style.top = `${bounds.bottom + 6}px`
      menu.style.left = `${Math.max(8, Math.min(bounds.left, document.documentElement.clientWidth - menu.offsetWidth - 8))}px`
      find.focus()
    }

    const close = () => {
      closeMenu()
      overlay.remove()
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', onKey)
    }
    // Escape closes the filter menu first, then the window.
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      if (menu) closeMenu()
      else close()
    }
    document.addEventListener('keydown', onKey)
    overlay.addEventListener('mousedown', event => {
      const target = event.target as HTMLElement
      if (menu && !menu.contains(target) && !target.closest('[data-filter]')) closeMenu()
    })
    overlay.querySelector('.xw-scroll')!.addEventListener('scroll', closeMenu, { passive: true })
    overlay.addEventListener('click', event => {
      const target = event.target as HTMLElement
      if (target === overlay || target.closest('.xw-close')) return close()
      if (menu?.contains(target)) return
      const filter = target.closest<HTMLElement>('[data-filter]')
      if (filter) return openMenu(filter, filter.dataset.filter!)
      if (target.closest('.xw-clear')) {
        Object.values(picked).forEach(values => values.clear())
        search = ''
        overlay.querySelector<HTMLInputElement>('.xw-search')!.value = ''
        page = 0
        return render()
      }
      const cell = target.closest<HTMLElement>('thead th')
      if (cell) {
        const key = cell.dataset.key!
        if (key === sortKey) descending = !descending
        else { sortKey = key; descending = !(typeof (inScope[0] ?? {})[key] === 'string') }
        page = 0
        return render()
      }
      const step = target.closest<HTMLElement>('[data-step]')
      if (step) { page += Number(step.dataset.step); render() }
    })
    overlay.querySelector<HTMLInputElement>('.xw-search')!.addEventListener('input', event => {
      search = (event.target as HTMLInputElement).value
      page = 0
      render()
    })
    render()
  }

  document.addEventListener('click', event => {
    const link = (event.target as HTMLElement).closest<HTMLElement>('[data-employees]')
    if (!link) return
    event.preventDefault()
    open(JSON.parse(link.dataset.employees!))
  })
}
