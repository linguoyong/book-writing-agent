import { useCallback, useEffect, useState } from 'react'
import { Check, RefreshCw, ShieldCheck, X } from 'lucide-react'
import { api } from '../api'
import { useAppStore } from '../store'
import type { ApprovalRecord } from '../types'

const FILTERS = [
  { key: 'all', label: '全部' },
  { key: 'pending', label: '待审批' },
  { key: 'approved', label: '已通过' },
  { key: 'rejected', label: '已拒绝' },
  { key: 'expired', label: '已过期' }
] as const

const STATUS_LABEL: Record<ApprovalRecord['status'], string> = {
  pending: '待审批',
  approved: '已通过',
  rejected: '已拒绝',
  expired: '已过期'
}

export default function ApprovalsPage(): React.JSX.Element {
  const project = useAppStore((state) => state.activeProject)
  const [status, setStatus] = useState<(typeof FILTERS)[number]['key']>('all')
  const [items, setItems] = useState<ApprovalRecord[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async (): Promise<void> => {
    if (!project) return
    setBusy(true)
    setError('')
    try {
      setItems(await api.projectApprovals(project.id, status))
    } catch (exc) {
      setError((exc as Error).message)
    }
    setBusy(false)
  }, [project, status])

  useEffect(() => {
    void load()
  }, [load])

  const editedCount = (record: ApprovalRecord): number =>
    record.decision.filter((item) => item.type === 'edit').length

  return (
    <div className="page approvals-page">
      <div className="page-header">
        <div className="page-title-block">
          <h1>变更审批</h1>
          <p>每一轮写入都留痕：谁批准的、改了什么参数、最终落到哪个文件。</p>
        </div>
        <div className="page-actions">
          <button className="ghost-btn" onClick={() => void load()} disabled={busy}>
            <RefreshCw size={12} /> 刷新
          </button>
        </div>
      </div>

      <div className="page-tabs">
        {FILTERS.map((item) => (
          <button
            key={item.key}
            className={`page-tab ${status === item.key ? 'active' : ''}`}
            onClick={() => setStatus(item.key)}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="page-scroll">
        {error && <div className="panel-empty">加载失败：{error}</div>}
        {!error && items.length === 0 && (
          <div className="panel-empty">这个空间还没有审批记录</div>
        )}
        {items.map((record) => (
          <details className="approval-record" key={record.id}>
            <summary>
              <span className={`apr-status ${record.status}`}>{STATUS_LABEL[record.status]}</span>
              <span className="apr-title">{record.session_title || record.session_id}</span>
              <span className="apr-meta">
                {(record.payload.requests ?? []).map((req) => req.target).filter(Boolean).join(' · ') ||
                  '—'}
              </span>
              <span className="apr-time">{formatTime(record.created_at)}</span>
              {editedCount(record) > 0 && (
                <span className="apr-edited">已编辑 {editedCount(record)} 处</span>
              )}
            </summary>
            <div className="approval-record-body">
              {(record.payload.requests ?? []).map((request, index) => (
                <div className="apr-request" key={`${record.id}-${index}`}>
                  <div className="apr-request-head">
                    <span className="approval-tool">{request.name}</span>
                    <span className="approval-target">{request.target || '—'}</span>
                    {request.note && <span className="apr-note">{request.note}</span>}
                  </div>
                  {request.diff && <pre className="approval-diff">{clip(request.diff, 60)}</pre>}
                </div>
              ))}
              {record.decision.length > 0 && (
                <div className="apr-decisions">
                  {record.decision.map((decision, index) => (
                    <span className="apr-decision" key={index}>
                      {decision.type === 'approve' && (
                        <>
                          <Check size={10} /> 通过
                        </>
                      )}
                      {decision.type === 'reject' && (
                        <>
                          <X size={10} /> 拒绝{decision.message ? `：${decision.message}` : ''}
                        </>
                      )}
                      {decision.type === 'edit' && (
                        <>
                          <PenMark /> 编辑后执行
                        </>
                      )}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </details>
        ))}
      </div>
    </div>
  )
}

function PenMark(): React.JSX.Element {
  return <span className="apr-pen">✎</span>
}

function clip(text: string, maxLines: number): string {
  const lines = text.split('\n')
  if (lines.length <= maxLines) return text
  return `${lines.slice(0, maxLines).join('\n')}\n…（其余 ${lines.length - maxLines} 行省略）`
}

function formatTime(value: string): string {
  try {
    return new Date(value).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return value
  }
}
