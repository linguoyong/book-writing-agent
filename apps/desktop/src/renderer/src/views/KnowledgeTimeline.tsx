import { useEffect, useMemo, useState } from 'react'
import { CalendarClock, Loader2, RefreshCw } from 'lucide-react'
import { api } from '../api'
import { KB_LABELS, useAppStore } from '../store'
import type { KbTimelineItem, TimelineData } from '../types'

type Axis = 'all' | 'chapter' | 'year'

const AXIS_LABEL: Record<Axis, string> = {
  all: '全部',
  chapter: '按章',
  year: '按年代'
}

interface Section {
  key: string
  label: string
  items: KbTimelineItem[]
}

function groupItems(items: KbTimelineItem[]): Section[] {
  const sections: Section[] = []
  const index = new Map<string, Section>()
  items.forEach((item) => {
    const key =
      item.axis === 'chapter'
        ? `c-${item.order}`
        : item.axis === 'year'
          ? `y-${item.year || item.order}`
          : 'x'
    let section = index.get(key)
    if (!section) {
      const label =
        item.axis === 'chapter'
          ? `第 ${item.order} 章`
          : item.axis === 'year'
            ? item.year || '年代未标'
            : '时间未标'
      section = { key, label, items: [] }
      index.set(key, section)
      sections.push(section)
    }
    section.items.push(item)
  })
  return sections
}

export default function KnowledgeTimeline(): React.JSX.Element {
  const project = useAppStore((state) => state.activeProject)
  const showToast = useAppStore((state) => state.showToast)

  const [data, setData] = useState<TimelineData | null>(null)
  const [loading, setLoading] = useState(true)
  const [axis, setAxis] = useState<Axis>('all')

  const load = async (): Promise<void> => {
    if (!project) return
    setLoading(true)
    try {
      setData(await api.projectTimeline(project.id))
    } catch (error) {
      showToast((error as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.id])

  const sections = useMemo(() => {
    const items = (data?.items ?? []).filter(
      (item) => axis === 'all' || item.axis === axis
    )
    return groupItems(items)
  }, [data, axis])

  const axes = data?.axes

  return (
    <div className="timeline-wrap">
      <div className="graph-toolbar">
        <div className="timeline-tabs">
          {(['all', 'chapter', 'year'] as Axis[]).map((key) => (
            <button
              key={key}
              className={`timeline-tab ${axis === key ? 'active' : ''}`}
              onClick={() => setAxis(key)}
            >
              {AXIS_LABEL[key]}
              <span className="timeline-count">
                {key === 'all'
                  ? data?.total ?? 0
                  : key === 'chapter'
                    ? axes?.chapter ?? 0
                    : axes?.year ?? 0}
              </span>
            </button>
          ))}
        </div>
        <button className="ghost-btn" onClick={() => void load()} disabled={loading}>
          {loading ? <Loader2 size={12} className="spin" /> : <RefreshCw size={12} />}
          刷新
        </button>
      </div>

      {loading && !data && <div className="panel-empty">读取时间线…</div>}

      {!loading && data && data.total === 0 && (
        <div className="empty-block">
          <CalendarClock size={20} />
          <div>还没有时间线</div>
          <p>
            在角色卡里写 <code>timeline: [{'{chapter: 3, state: "..."}'}]</code>，
            或跑一次「抽取设定」生成全书事件。
          </p>
        </div>
      )}

      {sections.length > 0 && (
        <div className="timeline-list">
          {sections.map((section) => (
            <section className="timeline-section" key={section.key}>
              <div className="timeline-head">
                <span className="timeline-label">{section.label}</span>
                <span className="timeline-line" />
                <span className="timeline-num">{section.items.length}</span>
              </div>
              {section.items.map((item) => (
                <div className="timeline-item" key={`${item.source_kind}-${item.source_id}-${item.seq}`}>
                  <span className="timeline-dot" />
                  <div className="timeline-text">{item.text}</div>
                  <span className="timeline-source">
                    {KB_LABELS[item.source_kind as keyof typeof KB_LABELS] ??
                      item.source_kind}
                    · {item.source_name}
                  </span>
                </div>
              ))}
            </section>
          ))}
        </div>
      )}
    </div>
  )
}
