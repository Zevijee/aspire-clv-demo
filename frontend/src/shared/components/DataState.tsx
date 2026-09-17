export type DataStateProps = {
  loading?: boolean
  error?: string | null
  onRetry?: () => void
}

export function DataState({
  loading,
  error,
  onRetry,
  label,
}: DataStateProps & { label: string }) {
  return (
    <div className="data-state" role={error ? 'alert' : 'status'}>
      {loading && <span aria-hidden="true" className="data-state__spinner" />}
      <span className={error ? 'report-status--error' : undefined}>
        {error ?? (loading ? `Loading ${label}…` : 'No data matches the selected filters.')}
      </span>
      {error && onRetry && <button onClick={onRetry} type="button">Retry</button>}
    </div>
  )
}
