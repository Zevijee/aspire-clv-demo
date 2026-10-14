import { FullScreenModal } from '../../../shared/components/FullScreenModal'
import { ReportSearchProvider } from '../../../shared/components/ReportSearchContext'
import { StaffingEmployees } from './StaffingEmployees'

/** What a clicked figure or name stands for: its row, its roles and locations,
 * and whether it is the row's overtime or its employees. */
export type EmployeesWindow = {
  name: string
  roles: string[]
  filters: Record<string, string[]>
  overtime: boolean
}

/** The people behind a row of the Staffing Overview, in a window over the page
 * rather than another view: its employees, one row each over the page's date
 * range, or for an overtime figure, those of them with overtime, most first. */
export function StaffingEmployeesModal({ scope, startDate, endDate, onClose }: {
  scope: EmployeesWindow | null
  startDate: string
  endDate: string
  onClose: () => void
}) {
  return <FullScreenModal open={scope !== null} onClose={onClose} destroyOnHidden
    title={scope ? `${scope.overtime ? 'Overtime' : 'Employees'} · ${scope.name}` : ''}>
    {scope && <ReportSearchProvider initialParams={new URLSearchParams({ start_date: startDate, end_date: endDate })}>
      {/* The full-screen modal's table area: the table fills the window and scrolls inside it. */}
      <div className="net-change-daily-modal__table">
        <StaffingEmployees overtime={scope.overtime} title={scope.overtime ? 'Employees with overtime' : 'Employees'}
          fileName={scope.overtime ? 'overtime-employees' : 'staffing-employees'} roles={scope.roles}
          initialFilters={scope.filters} />
      </div>
    </ReportSearchProvider>}
  </FullScreenModal>
}
