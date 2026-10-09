/** A square, icon-only download button: a blue arrow into a tray, framed as a
 * quiet control. For a card that exports its own data where a labelled Export
 * to CSV button would crowd it. `label` names what downloads, for the tooltip
 * and screen readers, since the button has no visible text. */
export function DownloadButton({ label, onClick, disabled = false }: {
  label: string; onClick: () => void; disabled?: boolean
}) {
  return <button type="button" className="download-button" aria-label={label} title={label}
    disabled={disabled} onClick={onClick}>
    <svg aria-hidden="true" className="download-button__icon" fill="none" viewBox="0 0 24 24">
      <path d="M12 4v11m0 0 4.5-4.5M12 15l-4.5-4.5" />
      <path d="M4 14v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4" />
    </svg>
  </button>
}
