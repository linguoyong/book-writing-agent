import { useEffect, useState } from 'react'
import { Check, PenLine, ShieldCheck, X } from 'lucide-react'
import type { ApprovalBundle, ApprovalDecision, ApprovalRequest } from '../types'

interface Props {
  approval: ApprovalBundle
  streaming: boolean
  onSubmit: (decisions: ApprovalDecision[]) => void
}

type Choice = 'approve' | 'reject' | 'edit'

/** 各工具「主要文本」与「目标路径」参数名；编辑面板直接改这两个字段 */
const TEXT_FIELD: Record<string, string> = {
  manuscript_write: 'content',
  kb_write: 'body',
  write_file: 'content',
  edit_file: 'new_string'
}
const PATH_FIELD: Record<string, string> = {
  manuscript_write: 'path',
  kb_write: 'entity_id',
  write_file: 'file_path',
  edit_file: 'file_path',
  delete: 'file_path'
}

interface EditState {
  path: string
  text: string
}

export default function ApprovalCard({ approval, streaming, onSubmit }: Props): React.JSX.Element {
  const [choices, setChoices] = useState<Choice[]>([])
  const [reasons, setReasons] = useState<string[]>([])
  const [edits, setEdits] = useState<Record<number, EditState>>({})

  useEffect(() => {
    setChoices(approval.requests.map(() => 'approve'))
    setReasons(approval.requests.map(() => ''))
    setEdits({})
  }, [approval.approval_id, approval.requests])

  const setChoice = (index: number, choice: Choice): void => {
    setChoices((prev) => prev.map((item, i) => (i === index ? choice : item)))
    if (choice === 'edit' && edits[index] === undefined) {
      const request = approval.requests[index]
      const raw = request.raw_args ?? request.args
      const textKey = TEXT_FIELD[request.name]
      const pathKey = PATH_FIELD[request.name]
      setEdits((prev) => ({
        ...prev,
        [index]: {
          path: String(pathKey ? (raw[pathKey] ?? '') : ''),
          text: String(textKey ? (raw[textKey] ?? '') : '')
        }
      }))
    }
  }

  const patchEdit = (index: number, patch: Partial<EditState>): void =>
    setEdits((prev) => ({ ...prev, [index]: { ...(prev[index] as EditState), ...patch } }))

  const buildDecision = (index: number, choice: Choice): ApprovalDecision => {
    const request = approval.requests[index]
    if (choice === 'reject') {
      return { type: 'reject', message: reasons[index] || '用户拒绝了这次写入' }
    }
    const edit = edits[index]
    if (choice === 'edit' && edit) {
      const raw = request.raw_args ?? request.args
      const textKey = TEXT_FIELD[request.name]
      const pathKey = PATH_FIELD[request.name]
      const args: Record<string, unknown> = { ...raw }
      if (textKey) args[textKey] = edit.text
      if (pathKey) args[pathKey] = edit.path
      return { type: 'edit', edited_action: { name: request.name, args } }
    }
    return { type: 'approve' }
  }

  const submit = (all?: Choice): void => {
    onSubmit(
      approval.requests.map((_, index) =>
        buildDecision(index, all ?? choices[index] ?? 'approve')
      )
    )
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
              <span className={`approval-choice ${choice}`}>
                {choice === 'approve' ? '通过' : choice === 'edit' ? '编辑后执行' : '拒绝'}
              </span>
            </summary>
            <div className="approval-body">
              {request.note && <div className="approval-note">{request.note}</div>}
              {choice === 'edit' ? (
                <EditFields
                  request={request}
                  edit={edits[index]}
                  onChange={(patch) => patchEdit(index, patch)}
                />
              ) : (
                <pre className="approval-diff">{renderDiff(request.diff)}</pre>
              )}
              <div className="approval-row">
                <button
                  className={`approval-btn ${choice === 'approve' ? 'active' : ''}`}
                  onClick={() => setChoice(index, 'approve')}
                >
                  <Check size={11} /> 通过
                </button>
                {TEXT_FIELD[request.name] && (
                  <button
                    className={`approval-btn ${choice === 'edit' ? 'active' : ''}`}
                    onClick={() => setChoice(index, 'edit')}
                  >
                    <PenLine size={11} /> 编辑后执行
                  </button>
                )}
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

function EditFields({
  request,
  edit,
  onChange
}: {
  request: ApprovalRequest
  edit?: EditState
  onChange: (patch: Partial<EditState>) => void
}): React.JSX.Element {
  if (!edit) return <div className="approval-note">正在载入原文…</div>
  const pathKey = PATH_FIELD[request.name]
  const textKey = TEXT_FIELD[request.name]
  return (
    <div className="approval-edit">
      {pathKey && (
        <label className="approval-field">
          <span>目标{request.name === 'kb_write' ? '条目 ID' : '路径'}</span>
          <input value={edit.path} onChange={(event) => onChange({ path: event.target.value })} />
        </label>
      )}
      {textKey && (
        <label className="approval-field">
          <span>{request.name === 'edit_file' ? '替换后的内容' : '写入内容'}</span>
          <textarea
            value={edit.text}
            spellCheck={false}
            onChange={(event) => onChange({ text: event.target.value })}
          />
        </label>
      )}
      <div className="approval-note">提交后 Agent 会按你改过的路径与内容执行。</div>
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
