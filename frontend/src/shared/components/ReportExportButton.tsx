import { useState } from 'react'
import { DownloadIcon } from './Table'
import { collectExportExtras } from '../exportExtensions'

// Controls that only work in the app, left out of the file: exports, searches,
// paging, the views a button opens, every filter and the sticky scrollbar.
const LIVE_ONLY = [
  '.filter-dropdown', '.toggle-field', '.segmented-control',
  '.report-table__export', '.report-table__search', '.report-table__pagination-actions',
  '.report-table__view-action', '.report-table__filter-menu',
  '.report-table__clear-filters', '.report-table__filter-icon', '.report-table__sort-icon',
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

/** The report as it is on screen -- its title, its tab, every table and chart
 * with the rows, filters and drilldown shown -- as one HTML file to keep or send.
 * Paged tables carry the page shown; their CSV export has every row. */
export async function exportReport(module?: string) {
  const content = document.getElementById('main-content')
  if (!content) throw new Error('There is no report on the page to export.')
  const title = document.querySelector('.report-title-block h1')?.textContent?.trim() || 'Report'
  const detail = document.querySelector('.report-title-block .report-title-detail')?.textContent?.trim() ?? ''
  const activeTab = document.querySelector('.report-tab--active')?.textContent?.trim() ?? ''
  // The tab only where it adds something: the Staffing Overview's Overview tab is just "Overview".
  const tab = activeTab === title ? '' : activeTab

  const extras = await collectExportExtras()
  const copy = content.cloneNode(true) as HTMLElement
  copy.removeAttribute('id')
  copy.querySelectorAll(LIVE_ONLY).forEach(element => element.remove())
  copy.querySelectorAll<HTMLElement>(FLOATING.map(name => `.${name}`).join(', ')).forEach(element => {
    element.classList.remove(...FLOATING)
    element.style.removeProperty('transform')
  })

  const exported = new Date()
  const stamp = exported.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  const theme = document.documentElement.getAttribute('data-theme')
  const heading = [module, title, tab].filter(Boolean).join(' · ')
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
${extras.script}</script>
</body>
</html>
`
  const url = URL.createObjectURL(new Blob([html], { type: 'text/html;charset=utf-8' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${[module, title, tab].filter(Boolean).map(part => slug(part as string)).join('-')}-`
    + `${exported.toISOString().slice(0, 10)}.html`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** The report header's Export button, right of the date range, labelled as the
 * header's other controls are: the report as shown, as an HTML file named for
 * its module, report and tab. Orange, so it stands apart from the filters. */
export function ReportExportButton({ module }: { module?: string }) {
  const [failed, setFailed] = useState(false)
  const [preparing, setPreparing] = useState(false)
  return <div className="report-export-field">
    <span className="report-export-field__label">Export</span>
    <button type="button" className="report-table__export report-export-button" disabled={preparing}
      title={failed ? 'The export failed. Try again.' : 'Export this report, as shown, to an HTML file'}
      onClick={async () => {
        setPreparing(true)
        try {
          await exportReport(module)
          setFailed(false)
        } catch {
          setFailed(true)
        } finally {
          setPreparing(false)
        }
      }}>
      <DownloadIcon />
      {preparing ? 'Preparing…' : failed ? 'Export failed' : 'Export'}
    </button>
  </div>
}
