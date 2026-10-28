import { useEffect, useState } from 'react'
import { Check, ShieldCheck, X } from 'lucide-react'
import type { ApprovalBundle } from '../types'

interface Props {
  approval: ApprovalBundle
  streaming: boolean
  onSubmit: (decisions: { type: 'approve' | 'reject'; message?: string }[]) => void
}

type Choice = 'approve' | 'reject'

export default function ApprovalCard({ approval, streaming, onSubmit }: Props): React.JSX.Element {
  const [choices, setChoices] = useState<Choice[]>([])
  const [reasons, setReasons] = useState<string[]>([])

  useEffect(() => {
    setChoices(approval.requests.map(() => 'approve'))
    setReasons(approval.requests.map(() => ''))
  }, [approval.approval_id, approval.requests])

  const setChoice = (index: number, choice: Choice): void => {
    setChoices((prev) => prev.map((item, i) => (i === index ? choice : item)))
  }

  const submit = (all?: Choice): void => {
    const decisions = approval.requests.map((_, index) => {
      const choice = all ?? choices[index] ?? 'approve'
      return choice === 'reject'
        ? { type: 'reject' as const, message: reasons[index] || '用户拒绝了这次写入' }
        : { type: 'approve' as const }
    })
    onSubmit(decisions)
  }

  return (
    <div className="approval-card">
      <div className="approval-head">
        <ShieldCheck size={14} />
        <span>需要你确认 {approval.requests.length} 处写入</span>
        <button className="approval-all" disabled={streaming} onClick={() => submit('approve')}>
          全部通过
        </button>
      </div>

      {approval.requests.map((request, index) => {
        const choice = choices[index] ?? 'approve'
        return (
          <details className="approval-item" key={`${request.name}-${index}`} open>
            <summary>
              <span className="approval-tool">{request.name}</span>
              <span className="approval-target">{request.target || '—'}</span>
              <span className={`approval-choice ${choice}`}>{choice === 'approve' ? '通过' : '拒绝'}</span>
            </summary>
            <div className="approval-body">
              {request.note && <div className="approval-note">{request.note}</div>}
              <pre className="approval-diff">{renderDiff(request.diff)}</pre>
              <div className="approval-row">
                <button
                  className={`approval-btn ${choice === 'approve' ? 'active' : ''}`}
                  onClick={() => setChoice(index, 'approve')}
                >
                  <Check size={11} /> 通过
                </button>
                <button
                  className={`approval-btn ${choice === 'reject' ? 'active danger' : ''}`}
                  onClick={() => setChoice(index, 'reject')}
                >
                  <X size={11} /> 拒绝
                </button>
              </div>
              {choice === 'reject' && (
                <input
                  className="approval-reason"
                  placeholder="拒绝原因（可选，会告诉模型）"
                  value={reasons[index] ?? ''}
                  onChange={(event) =>
                    setReasons((prev) =>
                      prev.map((item, i) => (i === index ? event.target.value : item))
                    )
                  }
                />
              )}
            </div>
          </details>
        )
      })}

      <div className="approval-foot">
        <span className="approval-hint">未执行的工具不会改任何文件</span>
        <button className="primary-btn" disabled={streaming} onClick={() => submit()}>
          {streaming ? '执行中…' : '提交审批'}
        </button>
      </div>
    </div>
  )
}

function renderDiff(diff: string): React.ReactNode {
  if (!diff) return '（无可预览的 diff）'
  return diff.split('\n').map((line, index) => {
    let tone = ''
    if (line.startsWith('+++') || line.startsWith('---')) tone = 'meta'
    else if (line.startsWith('@@')) tone = 'hunk'
    else if (line.startsWith('+')) tone = 'add'
    else if (line.startsWith('-')) tone = 'del'
    return (
      <span className={`diff-line ${tone}`} key={index}>
        {line || ' '}
        {'\n'}
      </span>
    )
  })
}
