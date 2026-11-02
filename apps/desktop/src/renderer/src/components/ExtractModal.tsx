import { useEffect, useRef, useState } from 'react'
import { Loader2, Sparkles, Square, X } from 'lucide-react'
import { api } from '../api'
import { useAppStore } from '../store'
import type { ExtractCandidate, ExtractStats, ExtractStatus } from '../types'

const EMPTY: ExtractStats = {
  chapters: 0,
  characters: 0,
  locations: 0,
  factions: 0,
  items: 0,
  aliases: 0,
  events: 0,
  foreshadowing: 0,
  failed: 0,
  candidates: 0,
  details: [],
  samples: []
}

export default function ExtractModal({
  onClose,
  onDone
}: {
  onClose: () => void
  onDone: () => void
}): React.JSX.Element {
  const project = useAppStore((state) => state.activeProject)
  const showToast = useAppStore((state) => state.showToast)

  const [status, setStatus] = useState<ExtractStatus | null>(null)
  const [preview, setPreview] = useState<ExtractStats | null>(null)
  const [candidates, setCandidates] = useState<ExtractCandidate[]>([])
  const [deciding, setDeciding] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const timer = useRef<number | null>(null)

  const refresh = async (): Promise<ExtractStatus | null> => {
    if (!project) return null
    try {
      const next = await api.extractStatus(project.id)
      setStatus(next)
      return next
    } catch (err) {
      setError((err as Error).message)
      return null
    }
  }

  const loadCandidates = async (): Promise<void> => {
    if (!project) return
    try {
      const result = await api.extractCandidates(project.id)
      setCandidates(result.items)
    } catch {
      /* 队列读不到不影响抽取本身 */
    }
  }

  useEffect(() => {
    void refresh()
    void loadCandidates()
    return () => {
      if (timer.current) window.clearInterval(timer.current)
    }
  }, [project?.id])

  const poll = (): void => {
    if (timer.current) window.clearInterval(timer.current)
    timer.current = window.setInterval(async () => {
      const next = await refresh()
      if (next && !next.running) {
        if (timer.current) window.clearInterval(timer.current)
        timer.current = null
        void loadCandidates()
        onDone()
      }
    }, 2000)
  }

  const runPreview = async (): Promise<void> => {
    if (!project || busy) return
    setBusy(true)
    setError('')
    try {
      const result = await api.extractPreview(project.id, 3)
      setPreview(result.preview)
      void loadCandidates()
      setStatus((prev) => (prev ? { ...prev, state: result.state } : prev))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const start = async (): Promise<void> => {
    if (!project || busy) return
    setBusy(true)
    setError('')
    try {
      await api.extractStart(project.id, 0)
      await refresh()
      poll()
      showToast('已开始逐章抽取，可以关掉窗口继续写作')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const stop = async (): Promise<void> => {
    if (!project) return
    await api.extractStop(project.id)
    await refresh()
    if (timer.current) window.clearInterval(timer.current)
    timer.current = null
  }

  const decide = async (candidateId: string, accept: boolean): Promise<void> => {
    if (!project) return
    setDeciding(candidateId)
    try {
      if (accept) await api.acceptCandidate(project.id, candidateId)
      else await api.rejectCandidate(project.id, candidateId)
      await loadCandidates()
      await refresh()
      onDone()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setDeciding('')
    }
  }

  const done = status?.state.done ?? 0
  const total = status?.state.total ?? 0
  const remaining = Math.max(0, total - done)
  const running = status?.running ?? false
  const live = status?.run?.stats ?? EMPTY
  const settled = (status?.state.stats ?? {}) as Partial<ExtractStats>
  const stats: ExtractStats = running ? { ...EMPTY, ...live } : { ...EMPTY, ...settled, samples: preview?.samples ?? settled.samples ?? [] }
  const shown = preview && !running ? preview : stats

  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal extract-modal" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <span>逐章抽取设定</span>
          <button className="icon-btn" onClick={onClose} title="关闭">
            <X size={14} />
          </button>
        </div>

        <div className="modal-body">
          <div className="field-hint" style={{ lineHeight: 1.8 }}>
            用抽取模型逐章读出角色、地点、势力、物品、事件与伏笔，自动并入知识库：
            已有实体只补别名与「自动摘要」小节，新实体直接建卡；置信度偏低或别名冲突的
            进下面的待确认队列。事件与伏笔追加到《自动抽取时间线》。可随时停止，
            已抽过的章节不会重复消耗。
          </div>

          <div className="extract-progress">
            <div className="extract-bar">
              <span style={{ width: `${total ? Math.round((done / total) * 100) : 0}%` }} />
            </div>
            <div className="extract-meta">
              <span>
                已抽取 {done}/{total} 章
                {remaining > 0 ? ` · 剩余 ${remaining} 章` : ''}
              </span>
              {running && (
                <span className="extract-live">
                  第 {status?.run.chapter} 章 · {status?.run.done}/{status?.run.total}
                </span>
              )}
            </div>
          </div>

          {error && (
            <div className="kb-notice warn">
              <span>{error}</span>
            </div>
          )}

          <div className="extract-grid">
            {[
              ['新角色', shown.characters],
              ['新地点', shown.locations],
              ['新势力', shown.factions],
              ['新物品', shown.items],
              ['合并别名', shown.aliases],
              ['事件', shown.events],
              ['伏笔', shown.foreshadowing]
            ].map(([label, value]) => (
              <div className="extract-stat" key={String(label)}>
                <span>{label}</span>
                <strong>{Number(value) || 0}</strong>
              </div>
            ))}
          </div>

          {!!shown.samples.length && (
            <div className="extract-samples">
              {shown.samples.slice(0, 10).map((sample) => (
                <span key={sample}>{sample}</span>
              ))}
            </div>
          )}

          <div className="extract-extra">
            自动摘要 {shown.notes || 0} 条 · 事件去重 {shown.duplicates || 0} 条 · 待确认{' '}
            {shown.queued || 0} 条
          </div>

          {candidates.length > 0 && (
            <div className="extract-candidates">
              <div className="extract-cand-head">待确认 {candidates.length} 条</div>
              <div className="extract-cand-list">
                {candidates.map((item) => (
                  <div className="extract-cand" key={item.id}>
                    <div className="extract-cand-main">
                      <div className="extract-cand-title">
                        <span className="extract-cand-name">{item.name}</span>
                        <span className="extract-cand-meta">
                          第{item.chapter}章 · {item.reason}
                        </span>
                      </div>
                      {item.note && <div className="extract-cand-note">{item.note}</div>}
                    </div>
                    <div className="extract-cand-actions">
                      <button
                        className="link-btn"
                        disabled={deciding === item.id}
                        onClick={() => void decide(item.id, true)}
                      >
                        {deciding === item.id ? '处理中…' : '采纳'}
                      </button>
                      <button
                        className="link-btn"
                        disabled={deciding === item.id}
                        onClick={() => void decide(item.id, false)}
                      >
                        忽略
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {!!shown.failed && (
            <div className="field-hint" style={{ color: 'var(--red)' }}>
              {shown.failed} 章抽取失败（多为模型返回格式异常），再次点击会重试这些章节。
            </div>
          )}
        </div>

        <div className="modal-footer">
          <span className="import-count">
            {running ? '抽取中，可以关闭窗口，任务会在后台继续' : '建议先试抽取 3 章，确认字段质量再跑全书'}
          </span>
          {running ? (
            <button className="ghost-btn" onClick={() => void stop()}>
              <Square size={12} />
              停止
            </button>
          ) : (
            <>
              <button className="ghost-btn" onClick={() => void runPreview()} disabled={busy}>
                {busy ? <Loader2 size={13} className="spin" /> : <Sparkles size={13} />}
                试抽取 3 章
              </button>
              <button className="primary-btn" onClick={() => void start()} disabled={busy || !remaining}>
                {remaining ? `开始抽取（剩余 ${remaining} 章）` : '已全部抽取'}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
