import type { ReactNode } from 'react'
import { Modal } from 'antd'

type DetailModalProps = {
  open: boolean
  onClose: () => void
  /** The record's name, such as the resident. */
  title: ReactNode
  /** One line under the title: where, when, what kind. */
  subtitle?: ReactNode
  children?: ReactNode
}

/** A compact, centred modal for reading one record -- a note, an event -- where
 * FullScreenModal would leave it lost in empty space. For tables and charts in
 * a modal, use FullScreenModal. */
export function DetailModal({ open, onClose, title, subtitle, children }: DetailModalProps) {
  return <Modal open={open} onCancel={onClose} footer={null} centered destroyOnHidden width={600}
    className="detail-modal"
    title={<div className="detail-modal__heading">
      <span className="detail-modal__title">{title}</span>
      {subtitle && <span className="detail-modal__subtitle">{subtitle}</span>}
    </div>}>
    {children}
  </Modal>
}
