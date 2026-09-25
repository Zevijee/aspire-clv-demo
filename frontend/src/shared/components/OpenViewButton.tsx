/** A header action that opens another view of the data. Outlined, so it never
 * reads as the solid Export button beside it. Two kinds, told apart by icon
 * only: `facilities` opens every facility in a modal (expand arrows); `table`
 * shows a chart's numbers as a table (a grid). */
export function OpenViewButton({ label, onClick, kind }: {
  label: string; onClick: () => void; kind: 'facilities' | 'table'
}) {
  return <button type="button" className="report-table__view-action" onClick={onClick}>
    <svg aria-hidden="true" className="report-table__view-action-icon" fill="none" viewBox="0 0 24 24">
      {kind === 'facilities' ? <>
        <path d="M15 3h6v6" />
        <path d="M9 21H3v-6" />
        <path d="m21 3-7 7" />
        <path d="m3 21 7-7" />
      </> : <>
        <rect x="3" y="4" width="18" height="16" rx="2" />
        <path d="M3 10h18M3 15h18M9 4v16" />
      </>}
    </svg>
    {label}
  </button>
}
