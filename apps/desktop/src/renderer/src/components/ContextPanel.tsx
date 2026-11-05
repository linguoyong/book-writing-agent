import { useEffect, useState } from 'react'
import { Brain, Layers, RefreshCw, Sparkles } from 'lucide-react'
import { Pencil } from 'lucide-react'
import { useAppStore } from '../store'

function formatTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(value % 1_000_000 === 0 ? 0 : 1)}M`
  if (value >= 1000) return `${Math.round(value / 1000)}K`
  return String(value)
}

// runtime / skills 由程序生成，其余都能在「提示词」页改
const EDITABLE_LAYERS = new Set(['identity', 'persona', 'domain', 'user', 'long', 'project'])

export default function ContextPanel(): React.JSX.Element {
  const context = useAppStore((state) => state.context)
  const memory = useAppStore((state) => state.memory)
  const activeSessionId = useAppStore((state) => state.activeSessionId)
  const setView = useAppStore((state) => state.setView)
  const setPromptFocus = useAppStore((state) => state.setPromptFocus)
  const refreshContext = useAppStore((state) => state.refreshContext)
  const refreshMemory = useAppStore((state) => state.refreshMemory)
  const distillMemory = useAppStore((state) => state.distillMemory)

  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    void refreshContext()
    void refreshMemory()
  }, [activeSessionId, refreshContext, refreshMemory])

  if (!activeSessionId) {
    return <div className="panel-empty">选择会话后查看本轮注入的上下文</div>
  }

  const items = context?.items ?? []
  const memoryFiles = (memory?.status ?? []).filter((item) => item.scope !== 'daily')

  const distill = async (): Promise<void> => {
    setBusy(true)
    const result = await distillMemory()
    setBusy(false)
    setNotice(result.ok ? `已沉淀 ${result.added} 条到长期记忆` : result.message ?? '没有可沉淀的内容')
  }

  return (
    <div className="ctx-panel">
      <div className="ctx-head">
        <span className="ctx-title">
          <Layers size={13} />
          本轮注入
        </span>
        <span className="ctx-total">{context ? `${context.total_chars} 字` : '—'}</span>
        <button className="ctx-icon-btn" title="刷新" onClick={() => void refreshContext()}>
          <RefreshCw size={12} />
        </button>
      </div>
      {context && (
        <div className="ctx-fingerprint">
          {context.domain_id} · {context.expert_id || '域默认人格'} · {context.fingerprint}
        </div>
      )}
      {context?.compaction && (
        <div className="ctx-compact" title="接近触发点时旧消息会被摘要压缩。触发点 = 窗口的 60%（不设绝对上限）；原文另存为 conversation_history 可回读">
          <span>窗口 {formatTokens(context.compaction.window)}</span>
          <span className="ctx-compact-dot" />
          <span>{formatTokens(context.compaction.trigger)} 自动压缩</span>
        </div>
      )}

      <div className="ctx-list">
        {items.map((item) => (
          <details className="ctx-item" key={item.layer}>
            <summary>
              <span className={`ctx-dot ${item.included ? 'on' : 'off'}`} />
              <span className="ctx-name">{item.title}</span>
              <span className={`ctx-chars ${item.truncated ? 'warn' : ''}`}>
                {item.chars}/{item.limit}
              </span>
              {EDITABLE_LAYERS.has(item.layer) && (
                <button
                  className="ctx-edit"
                  title="编辑这一层"
                  onClick={(event) => {
                    event.preventDefault()
                    event.stopPropagation()
                    setPromptFocus(item.layer)
                    setView('prompts')
                  }}
                >
                  <Pencil size={11} />
                </button>
              )}
            </summary>
            <div className="ctx-body">
              <div className="ctx-src">{item.source || item.layer}</div>
              <div className="ctx-preview">{item.preview || '（空）'}</div>
              {item.truncated && <div className="ctx-warn">超出该层预算，已截断</div>}
            </div>
          </details>
        ))}
        {!items.length && <div className="panel-empty">还没有装配记录，发送一条消息后可见</div>}
      </div>

      <div className="ctx-section">
        <div className="ctx-head">
          <span className="ctx-title">
            <Brain size={13} />
            记忆
          </span>
          <button className="ctx-icon-btn" title="刷新" onClick={() => void refreshMemory()}>
            <RefreshCw size={12} />
          </button>
        </div>
        <div className="mem-list">
          {memoryFiles.map((file) => (
            <div className="mem-row" key={file.scope} title={file.path}>
              <span className="mem-name">{file.title}</span>
              <span className="mem-chars">{file.chars} 字</span>
            </div>
          ))}
          {!memoryFiles.length && <div className="panel-empty">记忆文件尚未初始化</div>}
        </div>
        <button className="ghost-btn ctx-distill" onClick={() => void distill()} disabled={busy}>
          <Sparkles size={12} />
          {busy ? '沉淀中…' : '把本会话沉淀到长期记忆'}
        </button>
        {notice && <div className="ctx-notice">{notice}</div>}
      </div>

      {context && (
        <details className="ctx-raw">
          <summary>查看完整 system prompt</summary>
          <pre>{context.system_prompt}</pre>
        </details>
      )}
    </div>
  )
}
