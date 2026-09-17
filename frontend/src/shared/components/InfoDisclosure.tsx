import { useId, type ReactNode } from 'react'

type InfoDisclosureProps = {
  label: string
  children: ReactNode
  collapsible?: boolean
  defaultOpen?: boolean
}

/** An inline explanation that keeps metric definitions visible beside the report. */
export function InfoDisclosure({ label, children, collapsible = false, defaultOpen = false }: InfoDisclosureProps) {
  const titleId = useId()

  if (collapsible) return (
    <details className="info-disclosure info-disclosure--collapsible" open={defaultOpen}>
      <summary className="info-disclosure__title">{label}</summary>
      <div className="info-disclosure__content">{children}</div>
    </details>
  )

  return (
    <aside className="info-disclosure" aria-labelledby={titleId}>
      <svg aria-hidden="true" className="info-disclosure__icon" viewBox="0 0 24 24">
        <circle cx="12" cy="12" r="9" />
        <path d="M12 11v6M12 7v1" />
      </svg>
      <div className="info-disclosure__body">
        <h2 className="info-disclosure__title" id={titleId}>{label}</h2>
        <div className="info-disclosure__content">{children}</div>
      </div>
    </aside>
  )
}
