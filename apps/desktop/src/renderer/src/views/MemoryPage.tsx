import { useEffect, useRef, useState } from 'react'
import { Brain, Check, RefreshCw, Trash2 } from 'lucide-react'
import { api } from '../api'
import { useAppStore } from '../store'
import type { MemoryEntry, MemoryState } from '../types'

const SCOPES = [
  { key: 'user', title: '用户记忆', hint: '跨项目的偏好，始终注入上下文' },
  { key: 'long', title: '长期记忆', hint: '沉淀的事实与决策，按日期归档' },
  { key: 'project', title: '项目记忆', hint: '当前书稿的约定，写入 AGENTS.md' }
] as const

type Scope = (typeof SCOPES)[number]['key']

export default function MemoryPage(): React.JSX.Element {
  const project = useAppStore((state) => state.activeProject)
  const refreshMemory = useAppStore((state) => state.refreshMemory)
  const [scope, setScope] = useState<Scope>('long')
  const [data, setData] = useState<MemoryState | null>(null)
  const [draft, setDraft] = useState('')
  const [saved, setSaved] = useState(true)
  const [busy, setBusy] = useState(false)
  const loadedScope = useRef<Scope | null>(null)

  const load = async (): Promise<void> => {
    try {
      const next = await api.memory(project?.id)
      setData(next)
      setDraft(next.scopes[scope] ?? '')
      loadedScope.current = scope
      setSaved(true)
      await refreshMemory()
    } catch {
      /* 记忆读取失败时保持当前内容 */
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.id])

  useEffect(() => {
    if (!data || loadedScope.current === scope) return
    setDraft(data.scopes[scope] ?? '')
    loadedScope.current = scope
    setSaved(true)
  }, [scope, data])

  const save = async (): Promise<void> => {
    if (busy || saved) return
    setBusy(true)
    try {
      await api.saveMemory(scope, draft, project?.id)
      await load()
    } catch (error) {
      window.alert((error as Error).message)
    }
    setBusy(false)
  }

  const remove = async (entry: MemoryEntry): Promise<void> => {
    if (busy || !window.confirm('删除这条记忆？')) return
    setBusy(true)
    try {
      await api.deleteMemoryEntry(scope, entry.text, project?.id)
      await load()
    } catch (error) {
      window.alert((error as Error).message)
    }
    setBusy(false)
  }

  const entries = data?.entries?.[scope] ?? []
  const sources = data?.sources ?? {}
  const daily = data?.status.find((item) => item.scope === 'daily')
  const current = SCOPES.find((item) => item.key === scope)!

  return (
    <div className="memory-page">
      <div className="memory-head">
        <div className="memory-title">
          <Brain size={15} />
          记忆
        </div>
        <span className="memory-sub">文件是唯一事实来源，保存后立即影响下一轮上下文</span>
        <button className="small-btn" onClick={() => void load()} title="重新读取">
          <RefreshCw size={12} />
          刷新
        </button>
      </div>

      <div className="memory-grid">
        <aside className="memory-nav">
          {SCOPES.map((item) => {
            const count = data?.entries?.[item.key]?.length ?? 0
            return (
              <button
                key={item.key}
                className={`memory-nav-item ${scope === item.key ? 'active' : ''}`}
                onClick={() => setScope(item.key)}
              >
                <span>{item.title}</span>
                <span className="memory-nav-count">{count}</span>
              </button>
            )
          })}

          <div className="memory-nav-title">工作日志</div>
          {(daily?.files ?? []).length === 0 && <div className="memory-empty">暂无日志</div>}
          {(daily?.files ?? []).map((file) => (
            <div className="memory-daily" key={file}>
              {file}
            </div>
          ))}
        </aside>

        <section className="memory-main">
          <div className="memory-main-head">
            <div>
              <div className="memory-main-title">{current.title}</div>
              <div className="memory-main-hint">{current.hint}</div>
            </div>
            <span className="memory-chars">{draft.length} 字</span>
            <button
              className="primary-btn memory-save"
              disabled={saved || busy}
              onClick={() => void save()}
            >
              {busy ? '保存中…' : saved ? '已保存' : '保存'}
            </button>
          </div>

          <textarea
            className="memory-editor"
            value={draft}
            onChange={(event) => {
              setDraft(event.target.value)
              setSaved(false)
            }}
            spellCheck={false}
            placeholder="在这里维护记忆内容，支持 Markdown，条目以 - 开头"
          />

          <div className="memory-entries">
            <div className="memory-entries-head">
              条目 <span>{entries.length}</span>
            </div>
            {entries.length === 0 && <div className="memory-empty">还没有条目</div>}
            {entries.map((entry, index) => {
              const source = entry.source?.startsWith('session:')
                ? sources[entry.source.slice(8)] ?? entry.source.slice(8)
                : entry.source ?? ''
              return (
                <div className="memory-entry" key={`${entry.text}-${index}`}>
                  <div className="memory-entry-text">{entry.text}</div>
                  <div className="memory-entry-meta">
                    {entry.date && <span>{entry.date}</span>}
                    {source && <span className="memory-source">来自：{source}</span>}
                  </div>
                  <button
                    className="icon-btn memory-del"
                    title="删除条目"
                    onClick={() => void remove(entry)}
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              )
            })}
          </div>

          {saved && <div className="memory-saved-hint"><Check size={11} /> 已与磁盘同步</div>}
        </section>
      </div>
    </div>
  )
}
