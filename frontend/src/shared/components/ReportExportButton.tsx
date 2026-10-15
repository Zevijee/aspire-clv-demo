import { useState } from 'react'
import { DownloadIcon } from './Table'
import { DetailModal } from './DetailModal'
import { collectExcelSheets, collectExportExtras } from '../exportExtensions'
import { reportWorkbook } from '../reportExcel'

// Controls that only work in the app, left out of the file: exports, searches,
// paging, the views a button opens, every filter and the sticky scrollbar. The
// file's script gives each table its own search and column filters instead.
const LIVE_ONLY = [
  '.filter-dropdown', '.toggle-field', '.segmented-control',
  '.report-table__export', '.report-table__search', '.report-table__pagination-actions',
  '.report-table__view-action', '.report-table__filter-menu',
  '.report-table__clear-filters', '.report-table__filter-icon',
  '.data-state__spinner', 'input', 'select', 'textarea',
].join(', ')
// The floating header's classes: in the file it sits where the table drew it.
const FLOATING = ['report-table__floating', 'report-table--floating', 'report-table__head--floating']

// The page's layout keeps the report in a scrolling area the height of the
// window; the file is one long page, every table at full length.
const FILE_CSS = `
/* The app pins the body to the window (index.css: position fixed, overflow
   hidden) so only its report area scrolls; the file scrolls as a page. */
html, body { height: auto !important; overflow: visible !important; }
body { background: var(--color-canvas); inset: auto !important; margin: 0; position: static !important; }
/* A margin at the sides of the page, around the title and the report alike, so
   the title stays lined up with the report's edge inside it. */
.report-export { padding: 0 12px; }
.report-export__header { padding: var(--space-4) var(--layout-report-inline-padding) 0; }
.report-export__header h1 { margin: 0 0 4px; }
.report-export__header p { color: var(--color-text-muted); font-size: 0.8125rem; margin: 2px 0 0; }
/* Every table at full length in the page, which scrolls as one, as the site's
   report area does: the tables keep the app's own sideways scrolling, pinned
   first column and floating top, which the script below drives. */
.report-export .content-area, .report-export .report-content, .report-export .main-panel {
  height: auto !important; max-height: none !important; min-height: 0 !important; overflow: visible !important;
}
.report-export .report-table, .report-export .report-table__scroll {
  height: auto !important; max-height: none !important; min-height: 0 !important;
}
.report-export .drilldown-navigation { position: static !important; }
.report-export .drilldown-navigation::before { display: none !important; }
.report-export button { cursor: default; pointer-events: none; }
.report-export button.report-export__live { cursor: pointer; pointer-events: auto; }
`

// The app's floating table top and sideways scrollbar, for the file: the page
// scrolls instead of the report area, so the top floats to the top of the
// window. As Table's floatHeader places it (CSS draws the floating block from
// the same classes and properties), without the drilldown bar, which the file
// does not hold at the top.
const FILE_SCRIPT = `
(() => {
  const CORNER = 8
  // Blank page between the top of the window and the floating block, as the
  // app leaves below its drilldown bar.
  const SPACE = 8
  const floating = [...document.querySelectorAll('.report-table[data-float-header]')].map(card => {
    const box = card.querySelector(':scope > .report-table__scroll')
    const table = box && box.querySelector('table')
    const head = table && table.querySelector('thead')
    return box && table && head ? { card, box, table, head, titleBar: card.querySelector(':scope > .report-table__header') } : null
  }).filter(Boolean)
  const place = () => {
    for (const { card, box, table, head, titleBar } of floating) {
      const tableRect = table.getBoundingClientRect()
      const footer = table.querySelector('tfoot') ? table.querySelector('tfoot').getBoundingClientRect().height : 0
      const room = tableRect.height - head.offsetHeight - footer
      const start = titleBar ? box.getBoundingClientRect().top - (box.offsetTop - titleBar.offsetTop) : tableRect.top
      const shift = Math.round(Math.max(0, Math.min(SPACE - start, room)))
      const firstRow = head.rows[0] ? head.rows[0].getBoundingClientRect().height : 0
      const ratio = window.devicePixelRatio || 1
      const headLift = titleBar ? Math.min(4, shift) : 0
      const line = tableRect.top + shift - headLift + firstRow
      const snap = shift > 0 ? Math.round(line * ratio) / ratio - line : 0
      for (const element of [titleBar, head]) {
        if (!element) continue
        const move = element === head ? shift - headLift + snap : shift
        element.style.transform = shift > 0 ? 'translateY(' + move + 'px)' : ''
        element.classList.toggle('report-table__floating', shift > 0)
      }
      head.classList.toggle('report-table__head--floating', shift > 0)
      if (titleBar) {
        const gap = Math.round(tableRect.top - start - titleBar.offsetHeight)
        titleBar.style.boxShadow = shift > 0 ? ['0 0 0 1px var(--color-border)', 'var(--shadow-report-card)']
          .concat(gap > 0 ? ['0 ' + gap + 'px 0 0 var(--color-surface)'] : []).join(', ') : ''
        titleBar.style.setProperty('--float-head-height', head.offsetHeight + 'px')
        const lastRow = head.rows[head.rows.length - 1]
        const pinned = table.classList.contains('report-table__table--sticky-first') && lastRow && lastRow.cells[0]
          ? lastRow.cells[0].getBoundingClientRect().width : 0
        titleBar.style.setProperty('--float-pin-width', pinned + 'px')
        card.classList.toggle('report-table--floating', shift > 0)
        const blockTop = start + shift - card.getBoundingClientRect().top
        // A pixel past the top of the window: from exactly its edge, a fraction
        // of a pixel left the rows behind showing in the first pixel row.
        const cover = shift > 0 ? Math.max(0, start + shift) + 1 : 0
        card.style.setProperty('--float-band-top', (blockTop - cover) + 'px')
        card.style.setProperty('--float-band-height', (cover + CORNER) + 'px')
      }
    }
  }
  // The sideways scrollbar under a pinned first column, held at the foot of the
  // window, sized to the table here and kept in step with it.
  const bars = [...document.querySelectorAll('.report-table')].map(card => {
    const scroller = card.querySelector(':scope > .report-table__scroll')
    const bar = card.querySelector(':scope > .report-table__horizontal-scroll')
    const firstCell = scroller && scroller.querySelector('thead th')
    return scroller && bar && firstCell ? { scroller, bar, firstCell } : null
  }).filter(Boolean)
  const measure = () => {
    for (const { scroller, bar, firstCell } of bars) {
      const left = Math.min(firstCell.getBoundingClientRect().width, scroller.clientWidth)
      const width = Math.max(0, scroller.clientWidth - left)
      const overflow = Math.max(0, scroller.scrollWidth - scroller.clientWidth)
      bar.style.marginLeft = left + 'px'
      bar.style.width = width + 'px'
      bar.style.display = width > 0 && overflow > 0 ? '' : 'none'
      if (bar.firstElementChild) bar.firstElementChild.style.width = (width + overflow) + 'px'
      bar.scrollLeft = scroller.scrollLeft
    }
  }
  for (const { scroller, bar } of bars) {
    bar.addEventListener('scroll', () => { if (scroller.scrollLeft !== bar.scrollLeft) scroller.scrollLeft = bar.scrollLeft })
    scroller.addEventListener('wheel', event => {
      const delta = event.deltaX || (event.shiftKey ? event.deltaY : 0)
      if (!delta || scroller.scrollWidth <= scroller.clientWidth) return
      event.preventDefault()
      scroller.scrollLeft += delta * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? scroller.clientWidth : 1)
      bar.scrollLeft = scroller.scrollLeft
    }, { passive: false })
  }
  let frame = 0
  const schedule = () => { if (!frame) frame = requestAnimationFrame(() => { frame = 0; place() }) }
  window.addEventListener('scroll', schedule, { passive: true })
  window.addEventListener('resize', () => { measure(); schedule() })
  measure()
  place()
})()
`

// Each table's search, column filters and sorting, for the file: the app's own
// search box, filter menus and sort buttons, drawn with its classes, over the rows
// the file holds. A row stays when it holds the search and, in every filtered
// column, a ticked value; a department or other section row stays while any of
// its rows does. The Total row is every row's, before filtering, so it fades while
// a filter is on. Sorting orders the rows within each section, as the app does.
const FILE_FILTER_SCRIPT = `
(() => {
  const ICON = '<svg aria-hidden="true" class="report-table__filter-icon" fill="none" viewBox="0 0 24 24">'
    + '<path d="M4 5h16l-6 7v5l-4 2v-7z" /></svg>'
  const text = cell => cell ? cell.textContent.replace(/\\s+/g, ' ').trim() : ''
  const make = (tag, className, content) => {
    const element = document.createElement(tag)
    if (className) element.className = className
    if (content) element.textContent = content
    return element
  }
  let popup = null
  const closePopup = () => { if (popup) { popup.remove(); popup = null } }
  document.addEventListener('mousedown', event => {
    if (popup && !popup.contains(event.target) && !event.target.closest('.report-table__filter-button')) closePopup()
  })
  document.addEventListener('keydown', event => { if (event.key === 'Escape') closePopup() })
  window.addEventListener('scroll', closePopup, { passive: true })
  const depth = row => Number((row.className.match(/report-table__row--depth-(\\d+)/) || [0, 0])[1])

  for (const card of document.querySelectorAll('.report-export .report-table')) {
    const table = card.querySelector(':scope > .report-table__scroll table')
    const body = table && table.tBodies[0]
    const headRow = table && table.tHead && table.tHead.rows[table.tHead.rows.length - 1]
    const header = card.querySelector(':scope > .report-table__header')
    if (!body || !headRow || !header) continue
    const rows = [...body.rows]
    const isSection = row => row.classList.contains('report-table__row--section')
    const members = rows.filter(row => !isSection(row) && !row.querySelector('.report-table__state, .report-table__empty'))
    if (!members.length) continue
    const title = text(card.querySelector('.report-table__title')) || 'table'
    const count = card.querySelector('.report-table__subtitle [role="status"]')
    const shownCount = count ? count.textContent : ''
    const state = { search: '', filters: new Map() }
    const buttons = new Map()

    let actions = header.querySelector(':scope > .report-table__header-actions')
    if (!actions) actions = header.appendChild(make('div', 'report-table__header-actions'))
    const clear = make('button', 'report-table__clear-filters report-export__live', 'Clear filters')
    clear.type = 'button'
    clear.hidden = true
    const searchLabel = make('label', 'report-table__search')
    const search = make('input')
    search.type = 'search'
    search.placeholder = 'Search all columns…'
    search.maxLength = 200
    search.setAttribute('aria-label', 'Search ' + title)
    searchLabel.appendChild(search)
    actions.prepend(clear, searchLabel)

    const empty = make('tr')
    const emptyCell = make('td', 'report-table__empty', 'No rows match your search and selected filters.')
    emptyCell.colSpan = headRow.cells.length
    empty.appendChild(emptyCell)
    empty.style.display = 'none'
    body.appendChild(empty)

    const apply = () => {
      const term = state.search.toLowerCase()
      let shown = 0
      for (const row of members) {
        const keep = (!term || text(row).toLowerCase().includes(term))
          && [...state.filters].every(([index, picked]) => !picked.size || picked.has(text(row.cells[index])))
        row.style.display = keep ? '' : 'none'
        if (keep) shown += 1
      }
      // From the bottom up, so a section knows whether any row below it stayed.
      const open = []
      for (let index = rows.length - 1; index >= 0; index -= 1) {
        const row = rows[index]
        if (!isSection(row)) { if (members.includes(row) && row.style.display !== 'none') open.push(depth(row)); continue }
        const level = depth(row)
        const keep = open.some(member => member > level)
        row.style.display = keep ? '' : 'none'
        for (let at = open.length - 1; at >= 0; at -= 1) if (open[at] > level) open.splice(at, 1)
        if (keep) open.push(level)
      }
      const active = Boolean(term) || [...state.filters.values()].some(picked => picked.size > 0)
      clear.hidden = !active
      for (const [index, button] of buttons) {
        const picked = state.filters.get(index)
        button.classList.toggle('report-table__filter-button--active', Boolean(picked && picked.size))
      }
      if (count) count.textContent = active
        ? 'Showing ' + shown.toLocaleString() + ' of ' + members.length.toLocaleString() + ' rows' : shownCount
      empty.style.display = shown ? 'none' : ''
      if (table.tFoot) {
        table.tFoot.style.opacity = active ? '0.45' : ''
        table.tFoot.title = active ? 'The total of every row, before the search and filters' : ''
      }
      // The floating top and sideways scrollbar measure the table again.
      window.dispatchEvent(new Event('resize'))
    }
    search.addEventListener('input', () => { state.search = search.value.trim(); apply() })
    clear.addEventListener('click', () => {
      state.search = ''
      search.value = ''
      state.filters.clear()
      closePopup()
      apply()
    })

    // Sorting: a header's sort button orders each run of rows between section
    // rows by that column, a figure by its number, anything else as text.
    const runs = []
    let run = []
    for (const row of rows) {
      if (members.includes(row)) run.push(row)
      else if (run.length) { runs.push(run); run = [] }
    }
    if (run.length) runs.push(run)
    const figure = cell => {
      const found = text(cell).replace(/\\u2212/g, '-').match(/-?\\$?[\\d,]*\\.?\\d+/)
      return found ? Number(found[0].replace(/[$,]/g, '')) : null
    }
    const sortIcons = {
      ascending: 'm8 11 4-4 4 4M12 7v14', descending: 'm8 13 4 4 4-4M12 17V3', none: 'm8 7 4-4 4 4M16 17l-4 4-4-4',
    }
    const sortButtons = [...headRow.cells].map(th => th.querySelector('.report-table__sort-button'))
    const sortBy = (index, direction) => {
      const numeric = headRow.cells[index].classList.contains('report-table__numeric')
      const compare = (a, b) => {
        if (numeric) {
          const left = figure(a.cells[index])
          const right = figure(b.cells[index])
          // Rows without a figure go last either way.
          if (left === null || right === null) return left === right ? 0 : left === null ? 1 : -1
          return direction === 'ascending' ? left - right : right - left
        }
        const order = text(a.cells[index]).localeCompare(text(b.cells[index]), undefined, { numeric: true })
        return direction === 'ascending' ? order : -order
      }
      const sorted = new Map(runs.map(members => [members[0], [...members].sort(compare)]))
      const order = []
      for (const row of rows) {
        if (sorted.has(row)) order.push(...sorted.get(row))
        else if (!members.includes(row)) order.push(row)
      }
      body.append(...order, empty)
      sortButtons.forEach((button, at) => {
        if (!button) return
        const shown = at === index ? direction : 'none'
        headRow.cells[at].setAttribute('aria-sort', shown)
        button.setAttribute('aria-label', 'Sort by ' + text(button) + ' '
          + (shown === 'ascending' ? 'descending' : 'ascending'))
        let icon = button.querySelector('.report-table__sort-icon')
        if (!icon) {
          icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
          icon.setAttribute('class', 'report-table__sort-icon')
          icon.setAttribute('aria-hidden', 'true')
          icon.setAttribute('fill', 'none')
          icon.setAttribute('viewBox', '0 0 24 24')
          icon.appendChild(document.createElementNS('http://www.w3.org/2000/svg', 'path'))
          button.appendChild(icon)
        }
        icon.firstElementChild.setAttribute('d', sortIcons[shown])
      })
      window.dispatchEvent(new Event('resize'))
    }
    sortButtons.forEach((button, index) => {
      if (!button) return
      button.classList.add('report-export__live')
      button.addEventListener('click', () => {
        const current = headRow.cells[index].getAttribute('aria-sort')
        sortBy(index, current === 'ascending' ? 'descending' : 'ascending')
      })
    })

    // A filter menu for each column the app could filter, and the name column.
    ;[...headRow.cells].forEach((th, index) => {
      if (!th.hasAttribute('data-export-filter')) return
      const holder = th.querySelector('.report-table__column-header') || th
      const menu = make('div', 'report-table__filter-menu')
      const button = make('button', 'report-table__filter-button report-export__live')
      button.type = 'button'
      button.innerHTML = ICON
      button.setAttribute('aria-label', 'Filter ' + text(th))
      menu.appendChild(button)
      holder.appendChild(menu)
      buttons.set(index, button)
      const values = [...new Set(members.map(row => text(row.cells[index])).filter(Boolean))]
        .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))
      button.addEventListener('click', () => {
        const reopening = popup && popup.dataset.owner === title + index
        closePopup()
        if (reopening) return
        if (!state.filters.has(index)) state.filters.set(index, new Set())
        const picked = state.filters.get(index)
        popup = make('div', 'report-table__filter-options')
        popup.dataset.owner = title + index
        popup.setAttribute('role', 'dialog')
        popup.setAttribute('aria-label', 'Filter ' + text(th))
        const findLabel = make('label', 'multi-select-filter__search')
        const find = make('input')
        find.type = 'search'
        find.placeholder = 'Search ' + text(th)
        findLabel.appendChild(find)
        const buttonsRow = make('div', 'multi-select-filter__actions')
        const all = make('button', '', 'Select all')
        const none = make('button', 'multi-select-filter__clear', 'Clear')
        all.type = none.type = 'button'
        buttonsRow.append(all, none)
        const list = make('div', 'multi-select-filter__list')
        const draw = () => {
          const term = find.value.trim().toLowerCase()
          const visible = values.filter(value => value.toLowerCase().includes(term))
          all.textContent = term ? 'Select matches' : 'Select all'
          all.disabled = !visible.length
          list.replaceChildren(...(visible.length ? visible.map(value => {
            const option = make('label', 'multi-select-filter__option')
            const box = make('input')
            box.type = 'checkbox'
            box.checked = picked.has(value)
            box.addEventListener('change', () => {
              if (box.checked) picked.add(value)
              else picked.delete(value)
              apply()
            })
            option.append(box, make('span', '', value))
            return option
          }) : [make('p', 'multi-select-filter__empty', 'No matching options.')]))
          return visible
        }
        find.addEventListener('input', draw)
        all.addEventListener('click', () => {
          const visible = draw()
          if (!find.value.trim()) picked.clear()
          visible.forEach(value => picked.add(value))
          draw()
          apply()
        })
        none.addEventListener('click', () => { picked.clear(); draw(); apply() })
        draw()
        popup.append(findLabel, buttonsRow, list)
        document.body.appendChild(popup)
        const bounds = button.getBoundingClientRect()
        const width = popup.offsetWidth
        popup.style.top = (bounds.bottom + 6) + 'px'
        popup.style.left = Math.max(8, Math.min(bounds.left, document.documentElement.clientWidth - width - 8)) + 'px'
        find.focus()
      })
    })
  }
})()
`

const escape = (text: string) => text.replace(/[&<>"]/g, character =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[character] ?? character)
const slug = (text: string) => text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')

/** Every style the page has, as text, so the file looks as the report does.
 * A sheet from another origin cannot be read; the app serves its own. */
function pageStyles() {
  return Array.from(document.styleSheets).map(sheet => {
    try {
      return Array.from(sheet.cssRules).map(rule => rule.cssText).join('\n')
    } catch {
      return ''
    }
  }).join('\n')
}

/** The report on screen and what an export calls it: its module, title and tab
 * as the heading, the range line under the title, and a file name of those and
 * the day, without its extension. */
function reportOnScreen(module?: string) {
  const content = document.getElementById('main-content')
  if (!content) throw new Error('There is no report on the page to export.')
  const title = document.querySelector('.report-title-block h1')?.textContent?.trim() || 'Report'
  const detail = document.querySelector('.report-title-block .report-title-detail')?.textContent?.trim() ?? ''
  const activeTab = document.querySelector('.report-tab--active')?.textContent?.trim() ?? ''
  // The tab only where it adds something: the Staffing Overview's Overview tab is just "Overview".
  const tab = activeTab === title ? '' : activeTab
  const exported = new Date()
  return {
    content, detail,
    stamp: exported.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }),
    heading: [module, title, tab].filter(Boolean).join(' · '),
    file: `${[module, title, tab].filter(Boolean).map(part => slug(part as string)).join('-')}-`
      + exported.toISOString().slice(0, 10),
  }
}

function download(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** The report as it is on screen -- its title, its tab, every table and chart
 * with the rows, filters and drilldown shown -- as one HTML file to keep or send,
 * each table searchable and filterable by column in the file.
 * Paged tables carry the page shown; their CSV export has every row. */
async function exportReport(module?: string) {
  const { content, detail, stamp, heading, file } = reportOnScreen(module)
  const extras = await collectExportExtras()
  const copy = content.cloneNode(true) as HTMLElement
  copy.removeAttribute('id')
  // The columns the file's filter menus go on: those the app filters, and the
  // first, which names each row, unless it holds figures.
  copy.querySelectorAll<HTMLTableSectionElement>('.report-table thead').forEach(head => {
    const row = head.rows[head.rows.length - 1]
    if (!row) return
    Array.from(row.cells).forEach((cell, index) => {
      if (cell.querySelector('.report-table__filter-menu')
        || (index === 0 && !cell.classList.contains('report-table__numeric'))) cell.setAttribute('data-export-filter', '')
    })
  })
  copy.querySelectorAll(LIVE_ONLY).forEach(element => element.remove())
  copy.querySelectorAll<HTMLElement>(FLOATING.map(name => `.${name}`).join(', ')).forEach(element => {
    element.classList.remove(...FLOATING)
    element.style.removeProperty('transform')
  })

  const theme = document.documentElement.getAttribute('data-theme')
  const html = `<!doctype html>
<html lang="en"${theme ? ` data-theme="${escape(theme)}"` : ''}>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escape(heading)}</title>
<style>${pageStyles()}
${FILE_CSS}
${extras.css}</style>
</head>
<body>
<div class="report-export">
<header class="report-export__header">
<h1>${escape(heading)}</h1>
${detail ? `<p>${escape(detail)}</p>` : ''}
<p>Exported ${escape(stamp)} from Clearview</p>
</header>
${copy.outerHTML}
</div>
${extras.html}
<script>${FILE_SCRIPT};
${FILE_FILTER_SCRIPT};
${extras.script}</script>
</body>
</html>
`
  download(new Blob([html], { type: 'text/html;charset=utf-8' }), `${file}.html`)
}

/** The report's tables as they are on screen, as an Excel workbook: one sheet
 * per table, with the report's heading and range above it -- or the report's own
 * sheets where it gives them (registerExcelSheets) (reportExcel). */
async function exportReportExcel(module?: string) {
  const { content, detail, stamp, heading, file } = reportOnScreen(module)
  const details = [detail, `Exported ${stamp} from Clearview`].filter(Boolean)
  download(await reportWorkbook(content, heading, details, await collectExcelSheets()), `${file}.xlsx`)
}

const FORMATS = [
  { id: 'html', label: 'Export to HTML', run: exportReport,
    description: 'The report as it looks, in one file for a browser: its tables searchable, sortable and '
      + 'filterable, and its charts.' },
  { id: 'excel', label: 'Export to Excel', run: exportReportExcel,
    description: 'Every table on the page as a sheet of a workbook, figures as numbers Excel can add up and sort.' },
] as const

/** The report header's Export button, right of the date range, labelled as the
 * header's other controls are. It asks how: the report as shown as an HTML file,
 * or its tables as an Excel workbook, each named for its module, report and tab.
 * Orange, so it stands apart from the filters. */
export function ReportExportButton({ module }: { module?: string }) {
  const [failed, setFailed] = useState(false)
  const [preparing, setPreparing] = useState(false)
  const [choosing, setChoosing] = useState(false)
  const run = async (format: typeof FORMATS[number]) => {
    setChoosing(false)
    setPreparing(true)
    try {
      await format.run(module)
      setFailed(false)
    } catch {
      setFailed(true)
    } finally {
      setPreparing(false)
    }
  }
  return <div className="report-export-field">
    <span className="report-export-field__label">Export</span>
    <button type="button" className="report-table__export report-export-button" disabled={preparing}
      title={failed ? 'The export failed. Try again.' : 'Export this report, as shown, to HTML or Excel'}
      onClick={() => setChoosing(true)}>
      <DownloadIcon />
      {preparing ? 'Preparing…' : failed ? 'Export failed' : 'Export report'}
    </button>
    <DetailModal open={choosing} onClose={() => setChoosing(false)} title="Export report"
      subtitle="The report as it is on screen: the rows, filters and drilldown shown.">
      <div className="report-export-choice">
        {FORMATS.map(format => <button key={format.id} type="button" className="report-export-choice__option"
          onClick={() => void run(format)}>
          <span className="report-export-choice__label"><DownloadIcon />{format.label}</span>
          <span className="report-export-choice__description">{format.description}</span>
        </button>)}
      </div>
    </DetailModal>
  </div>
}
