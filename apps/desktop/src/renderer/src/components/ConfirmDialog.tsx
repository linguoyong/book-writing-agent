import { AlertTriangle } from 'lucide-react'

export interface ConfirmRequest {
  title: string
  message: string
  confirmLabel?: string
  danger?: boolean
  onConfirm: () => void
}

/** 应用内确认框：与整体风格一致，替代 window.confirm */
export default function ConfirmDialog({
  request,
  onClose
}: {
  request: ConfirmRequest | null
  onClose: () => void
}): React.JSX.Element | null {
  if (!request) return null
  const confirm = (): void => {
    request.onConfirm()
    onClose()
  }
  return (
    <div
      className="modal-mask"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="modal confirm-modal">
        <div className="confirm-head">
          {request.danger && <AlertTriangle size={15} className="confirm-warn" />}
          {request.title}
        </div>
        <div className="confirm-body">{request.message}</div>
        <div className="modal-footer">
          <button className="small-btn" onClick={onClose}>
            取消
          </button>
          <button
            className={`small-btn ${request.danger ? 'confirm-danger' : 'primary'}`}
            onClick={confirm}
            autoFocus
          >
            {request.confirmLabel ?? '确定'}
          </button>
        </div>
      </div>
    </div>
  )
}
