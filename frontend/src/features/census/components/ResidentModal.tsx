import { FullScreenModal } from '../../../shared/components/FullScreenModal'
import type { ResidentSummary } from '../api'

/** Who and where, which is all the modal shows; any report listing residents can supply it. */
export type ResidentIdentity = Pick<ResidentSummary, 'resident_name' | 'facility_name' | 'region' | 'state'>

/** One resident, full screen. Only who and where for now; details come later. */
export function ResidentModal({ resident, onClose }: { resident: ResidentIdentity | null; onClose: () => void }) {
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
