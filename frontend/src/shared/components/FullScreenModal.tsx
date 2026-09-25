import type { ReactNode } from 'react'
import { Modal } from 'antd'

type FullScreenModalProps = {
  open: boolean
  onClose: () => void
  title: ReactNode
  children?: ReactNode
  /** Unmount the content when closed, so reopening starts fresh. */
  destroyOnHidden?: boolean
}

/** The report detail modal: the whole viewport less a 24px margin, on the canvas
 * colour, with the body filling the height so tables inside can scroll. */
export function FullScreenModal({ open, onClose, title, children, destroyOnHidden }: FullScreenModalProps) {
  return <Modal open={open} onCancel={onClose} footer={null} destroyOnHidden={destroyOnHidden}
    title={title} width="calc(100vw - 48px)" className="net-change-daily-modal"
    style={{ top: 24, paddingBottom: 0, maxWidth: 'calc(100vw - 48px)' }}>
    {children}
  </Modal>
}
