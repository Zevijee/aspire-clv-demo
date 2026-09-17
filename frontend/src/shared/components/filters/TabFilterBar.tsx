import { useId, useState, type ReactNode } from 'react'
import { Drawer } from 'antd'
import { FilterValuePicker } from './FilterValuePicker'
import type { MultiSelectFilterOption } from './MultiSelectFilterOptions'

export type TabFilterBarFilter = {
  id: string
  label: string
  onChange?: (values: string[]) => void
  options: MultiSelectFilterOption[]
  getOptions?: (draftValues: Record<string, string[]>) => MultiSelectFilterOption[]
  singleSelect?: boolean
  renderPicker?: (props: { values: string[]; onChange: (values: string[]) => void; settings: Record<string, string[]>; onSettingsChange: (settings: Record<string, string[]>) => void }) => ReactNode
  values: string[]
  isApplied?: boolean
  isLoading?: boolean
  error?: string | null
  onRetry?: () => void
}

type TabFilterBarProps = {
  ariaLabel?: string
  filters?: TabFilterBarFilter[]
  settings?: Record<string, string[]>
  onApplyFilters?: (values: Record<string, string[]>) => void
  onDraftChange?: (current: Record<string, string[]>, id: string, values: string[]) => Record<string, string[]>
  onPayerTypesChange?: (payerTypes: string[]) => void
  payerTypes?: string[]
}

const payerOptions = [
  { label: 'Medicare', value: 'Medicare' },
  { label: 'Commercial Medicare', value: 'Medicare Advantage' },
  { label: 'Medicare HMO', value: 'Medicare HMO' },
  { label: 'Managed Medicaid', value: 'Managed Medicaid' },
  { label: 'Medicaid', value: 'Medicaid' },
  { label: 'Hospice', value: 'Hospice' },
  { label: 'Private Pay', value: 'Private Pay' },
]

function FilterIcon() {
  return (
    <svg aria-hidden="true" className="tab-filter-bar__filter-icon" viewBox="0 0 16 16">
      <path d="M3 4h10M3 8h10M3 12h10M6 2.5v3M10 6.5v3M5 10.5v3" />
    </svg>
  )
}

function sameValues(first: string[], second: string[]) {
  return first.length === second.length && first.every((value) => second.includes(value))
}

export function TabFilterBar({
  ariaLabel = 'Report filters',
  filters: suppliedFilters,
  settings = {},
  onApplyFilters,
  onDraftChange,
  onPayerTypesChange,
  payerTypes = [],
}: TabFilterBarProps) {
  const drawerId = useId()
  const [isOpen, setIsOpen] = useState(false)
  const [activeFilterId, setActiveFilterId] = useState<string | null>(null)
  const [draftValues, setDraftValues] = useState<Record<string, string[]>>({})
  const [session, setSession] = useState(0)
  const filters: TabFilterBarFilter[] = suppliedFilters ?? [
    {
      id: 'payer',
      label: 'Payer',
      onChange: onPayerTypesChange ?? (() => undefined),
      options: payerOptions,
      values: payerTypes,
    },
  ]
  const activeFilter = filters.find((filter) => filter.id === activeFilterId) ?? filters[0]
  const appliedCategoryCount = filters.filter((filter) => filter.values.length > 0 || filter.isApplied).length
  const hasSelections = filters.some((filter) => (draftValues[filter.id] ?? filter.values).length > 0)
  const hasChanges = filters.some((filter) => !sameValues(draftValues[filter.id] ?? filter.values, filter.values))
    || Object.entries(settings).some(([key, values]) => !sameValues(draftValues[key] ?? values, values))

  function openDrawer() {
    setDraftValues({ ...settings, ...Object.fromEntries(filters.map((filter) => [filter.id, [...filter.values]])) })
    setActiveFilterId(filters[0]?.id ?? null)
    setSession((value) => value + 1)
    setIsOpen(true)
  }

  function applyFilters(valuesToApply: Record<string, string[]>) {
    if (onApplyFilters) {
      onApplyFilters(valuesToApply)
      setIsOpen(false)
      return
    }
    for (const filter of filters) {
      const values = valuesToApply[filter.id] ?? filter.values
      if (!sameValues(values, filter.values)) {
        filter.onChange?.(values)
      }
    }
    setIsOpen(false)
  }

  return (
    <section aria-label={ariaLabel} className="tab-filter-bar">
      <button
        aria-controls={isOpen ? drawerId : undefined}
        aria-expanded={isOpen}
        aria-haspopup="dialog"
        aria-label={`Filters${appliedCategoryCount > 0 ? ` (${appliedCategoryCount} ${appliedCategoryCount === 1 ? 'category' : 'categories'} applied)` : ''}`}
        className="tab-filter-bar__toggle"
        onClick={openDrawer}
        type="button"
      >
        <FilterIcon />
        {appliedCategoryCount > 0 && (
          <span aria-hidden="true" className="tab-filter-bar__count">{appliedCategoryCount}</span>
        )}
      </button>
      <Drawer
        classNames={{
          root: 'report-filter-drawer',
          mask: 'report-filter-drawer__mask',
          wrapper: 'report-filter-drawer__wrapper',
          section: 'report-filter-drawer__section',
          header: 'report-filter-drawer__header',
          title: 'report-filter-drawer__title',
          close: 'report-filter-drawer__close',
          body: 'report-filter-drawer__body',
          footer: 'report-filter-drawer__footer',
        }}
        closable={{ placement: 'end' }}
        destroyOnHidden
        focusable={{ trap: true, focusTriggerAfterClose: true }}
        footer={
          <>
          <div className="report-filter-drawer__actions">
            <button
              className="report-filter-drawer__button report-filter-drawer__button--danger"
              title="Clear all filters immediately and close"
              disabled={!hasSelections && appliedCategoryCount === 0 && !(draftValues.scope?.length || settings.scope?.length)}
              onClick={() => {
                const cleared = Object.fromEntries([...filters.map((filter) => filter.id), ...Object.keys(settings)].map((key) => [key, []]))
                setDraftValues(cleared)
                applyFilters(cleared)
              }}
              type="button"
            >
              Clear all
            </button>
            <div className="report-filter-drawer__commit-actions">
              <button className="report-filter-drawer__button" onClick={() => setIsOpen(false)} type="button">
                Cancel
              </button>
              <button
                className="report-filter-drawer__button report-filter-drawer__button--primary"
                disabled={!hasChanges}
                onClick={() => applyFilters({ ...settings, ...draftValues })}
                type="button"
              >
                Apply filters
              </button>
            </div>
          </div>
          </>
        }
        id={drawerId}
        keyboard
        mask={{ closable: true }}
        onClose={() => setIsOpen(false)}
        open={isOpen}
        placement="right"
        size="min(680px, 100vw)"
        title={ariaLabel}
      >
        <div className="report-filter-drawer__workspace" key={session}>
          {filters.length > 0 && <div role="tablist" aria-label="Filter categories" aria-orientation="vertical" className="report-filter-drawer__tabs">
            {filters.map((filter, index) => <button key={filter.id} type="button" role="tab"
              id={`${drawerId}-tab-${filter.id}`} aria-controls={`${drawerId}-panel-${filter.id}`}
              aria-selected={activeFilter?.id === filter.id} tabIndex={activeFilter?.id === filter.id ? 0 : -1}
              className="report-filter-drawer__tab" onClick={() => setActiveFilterId(filter.id)}
              onKeyDown={(event) => {
                let next = index
                if (event.key === 'ArrowDown') next = (index + 1) % filters.length
                else if (event.key === 'ArrowUp') next = (index + filters.length - 1) % filters.length
                else if (event.key === 'Home') next = 0
                else if (event.key === 'End') next = filters.length - 1
                else return
                event.preventDefault()
                setActiveFilterId(filters[next].id)
                document.getElementById(`${drawerId}-tab-${filters[next].id}`)?.focus()
              }}>
              {filter.label}
              {(draftValues[filter.id] ?? filter.values).length > 0 && <span
                aria-label={`${(draftValues[filter.id] ?? filter.values).length} selected`}>
                {(draftValues[filter.id] ?? filter.values).length}
              </span>}
            </button>)}
          </div>}
          {filters.map((filter) => {
            const values = draftValues[filter.id] ?? filter.values
            const options = filter.getOptions?.(draftValues) ?? filter.options
            const onChange = (values: string[]) => setDraftValues((current) => onDraftChange
              ? onDraftChange(current, filter.id, values) : { ...current, [filter.id]: values })
            return <section key={filter.id} role="tabpanel" tabIndex={0}
              id={`${drawerId}-panel-${filter.id}`} aria-labelledby={`${drawerId}-tab-${filter.id}`}
              hidden={activeFilter?.id !== filter.id} className="report-filter-drawer__options">
              {filter.isLoading ? <p className="report-filter-drawer__state" role="status">Loading options...</p>
                : filter.error ? <div className="report-filter-drawer__state" role="alert">
                  <p>{filter.error}</p>
                  {filter.onRetry && <button className="report-filter-drawer__button" onClick={filter.onRetry} type="button">Try again</button>}
                </div> : filter.renderPicker ? filter.renderPicker({ values, onChange,
                  settings: { ...settings, ...draftValues },
                  onSettingsChange: (changes) => setDraftValues((current) => ({ ...current, ...changes })),
                }) : <FilterValuePicker label={filter.label} options={options} values={values}
                  onChange={onChange} singleSelect={filter.singleSelect} />}
            </section>
          })}
        </div>
      </Drawer>
    </section>
  )
}
