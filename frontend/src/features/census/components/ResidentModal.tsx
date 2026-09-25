import { FullScreenModal } from '../../../shared/components/FullScreenModal'
import type { ResidentSummary } from '../api'

/** One resident, full screen. Only who and where for now; details come later. */
export function ResidentModal({ resident, onClose }: { resident: ResidentSummary | null; onClose: () => void }) {
  return <FullScreenModal open={resident !== null} onClose={onClose} destroyOnHidden
    title={resident && <span className="resident-modal__title">
      <span>{resident.resident_name}</span>
      <small>{resident.facility_name} · {resident.region}, {resident.state}</small>
    </span>}>
    {resident && <div className="admissions-overview-modal__content">
      <section className="resident-modal__placeholder" aria-label="Resident details">
        <p>Resident details are coming soon.</p>
      </section>
    </div>}
  </FullScreenModal>
}
