import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, Circle, Loader2, RefreshCw, X } from 'lucide-react'
import { api } from '../api'
import { useAppStore } from '../store'
import type { ReviewChapter, ReviewDetail, ReviewIssue } from '../types'

const STATUS_LABEL: Record<string, string> = {
  pass: '已通过',
  fail: '未通过',
  stale: '待重审',
  draft: '未审'
}

const DIMENSION_LABEL: Record<string, string> = {
  consistency: '设定一致性',
  structure: '结构完整性',
  pacing: '节奏',
  voice: '人物声音',
  hook: '钩子与爽点',
  redundancy: '文字冗余'
}

function statusIcon(status?: string): React.JSX.Element {
  if (status === 'pass') return <CheckCircle2 size={12} className="rv-pass" />
  if (status === 'fail') return <AlertTriangle size={12} className="rv-fail" />
  return <Circle size={12} className="rv-draft" />
}

function IssueList({ issues }: { issues: ReviewIssue[] }): React.JSX.Element {
  if (!issues.length) return <div className="rv-empty">这一轮没有记录到可定位的问题。</div>
  return (
    <div className="rv-issues">
      {issues.map((issue, index) => (
        <div key={`${issue.severity}-${index}`} className={`rv-issue ${issue.severity.toLowerCase()}`}>
          <div className="rv-issue-head">
            <span className={`rv-badge ${issue.severity.toLowerCase()}`}>{issue.severity}</span>
            <span className="rv-dim">{DIMENSION_LABEL[issue.dimension] ?? issue.dimension}</span>
          </div>
          <div className="rv-problem">{issue.problem}</div>
          {issue.quote && <blockquote className="rv-quote">{issue.quote}</blockquote>}
          {issue.suggestion && <div className="rv-suggestion">建议：{issue.suggestion}</div>}
        </div>
      ))}
    </div>
  )
}

export default function ReviewPanel({ onClose }: { onClose: () => void }): React.JSX.Element {
  const project = useAppStore((state) => state.activeProject)
  const showToast = useAppStore((state) => state.showToast)
  const [items, setItems] = useState<ReviewChapter[]>([])
  const [active, setActive] = useState('')
  const [detail, setDetail] = useState<ReviewDetail | null>(null)
  const [running, setRunning] = useState('')
  const [loading, setLoading] = useState(true)
  const [note, setNote] = useState('')

  const load = useCallback(async () => {
    if (!project) return
    setLoading(true)
    try {
      const list = await api.reviews(project.id)
      setItems(list)
      setActive((current) => current || list[0]?.chapter || '')
    } catch (error) {
      showToast((error as Error).message)
    } finally {
      setLoading(false)
    }
  }, [project, showToast])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!project || !active) return
    let alive = true
    void api
      .review(project.id, active)
      .then((data) => {
        if (!alive) return
        setDetail(data && Object.keys(data).length ? data : null)
      })
      .catch(() => {
        if (alive) setDetail(null)
      })
    return () => {
      alive = false
    }
  }, [project, active])

  const run = async (chapter: string): Promise<void> => {
    if (!project || running) return
    setRunning(chapter)
    try {
      const result = await api.runReview(project.id, chapter, note)
      setDetail(result)
      await load()
      const p0 = (result.issues ?? []).filter((item) => item.severity === 'P0').length
      showToast(
        result.status === 'pass'
          ? `审稿通过（${result.score ?? '-'} 分）`
          : `审稿未通过：P0 ${p0} 条，共 ${result.issues?.length ?? 0} 条`
      )
    } catch (error) {
      showToast((error as Error).message)
    } finally {
      setRunning('')
    }
  }

  const passed = items.filter((item) => item.status === 'pass').length
  const failed = items.filter((item) => item.status === 'fail').length
  const draft = items.length - passed - failed

  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal review-modal" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <div>
            审稿
            <span className="rv-count">
              共 {items.length} 章 · 通过 {passed} · 未通过 {failed} · 待审 {draft}
            </span>
          </div>
          <div className="rv-head-actions">
            <button className="icon-btn" onClick={() => void load()} title="刷新">
              <RefreshCw size={13} />
            </button>
            <button className="icon-btn" onClick={onClose} title="关闭">
              <X size={14} />
            </button>
          </div>
        </div>

        <div className="review-body">
          <aside className="review-list">
            {loading && <div className="panel-empty">读取章节…</div>}
            {!loading && !items.length && (
              <div className="panel-empty">还没有正文章节，先在 manuscript 里写一章。</div>
            )}
            {items.map((item) => (
              <button
                key={item.chapter}
                className={`rv-row ${active === item.chapter ? 'active' : ''}`}
                onClick={() => setActive(item.chapter)}
              >
                <span className="rv-row-title">
                  {statusIcon(item.status)}
                  {item.title}
                </span>
                <span className="rv-row-meta">
                  {STATUS_LABEL[item.status] ?? item.status}
                  {item.score ? ` · ${item.score} 分` : ''}
                  {item.round ? ` · 第 ${item.round} 轮` : ''}
                </span>
              </button>
            ))}
          </aside>

          <section className="review-detail">
            {!active && <div className="panel-empty">选一章查看审稿结果</div>}
            {active && (
              <>
                <div className="rv-detail-head">
                  <div>
                    <div className="rv-title">{detail?.title || active}</div>
                    <div className="rv-sub">
                      {detail?.status ? STATUS_LABEL[detail.status] ?? detail.status : '未审'}
                      {detail?.score ? ` · ${detail.score} 分` : ''}
                      {detail?.round ? ` · 第 ${detail.round} 轮` : ''}
                      {detail?.model ? ` · ${detail.model}` : ''}
                    </div>
                  </div>
                  <button
                    className="primary-btn"
                    disabled={Boolean(running)}
                    onClick={() => void run(active)}
                  >
                    {running === active ? (
                      <>
                        <Loader2 size={12} className="spin" /> 审稿中…
                      </>
                    ) : (
                      '审这一章'
                    )}
                  </button>
                </div>

                <input
                  className="rv-note"
                  value={note}
                  placeholder="这次重点关注什么？（可选，例如：只看节奏与钩子）"
                  onChange={(event) => setNote(event.target.value)}
                />

                {detail?.summary && <div className="rv-summary">{detail.summary}</div>}

                {detail?.dimensions && (
                  <div className="rv-dims">
                    {Object.entries(detail.dimensions).map(([key, value]) => (
                      <div key={key} className="rv-dim-row">
                        <span>{DIMENSION_LABEL[key] ?? key}</span>
                        <span className="rv-dim-bar">
                          <span style={{ width: `${Math.max(0, Math.min(5, Number(value))) * 20}%` }} />
                        </span>
                        <span className="rv-dim-score">{value}</span>
                      </div>
                    ))}
                  </div>
                )}

                {detail?.issues?.length ? (
                  <IssueList issues={detail.issues} />
                ) : (
                  <div className="rv-empty">
                    {detail?.status === 'pass' ? '这一轮没有问题。' : '还没有审稿记录，点右上角开始。'}
                  </div>
                )}

                {detail?.dropped ? (
                  <div className="rv-dropped">
                    另有 {detail.dropped} 条因引用无法在正文定位而丢弃。
                  </div>
                ) : null}
              </>
            )}
          </section>
        </div>
      </div>
    </div>
  )
}
