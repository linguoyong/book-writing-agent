import { useEffect, useState } from 'react'
import { ChevronRight, Database, RefreshCw } from 'lucide-react'
import { api } from '../api'
import { useAppStore } from '../store'
import type { KbKind, KnowledgeBaseSummary } from '../types'
import KnowledgeDetail from './KnowledgeDetail'

export default function KnowledgePage(): React.JSX.Element {
  const project = useAppStore((state) => state.activeProject)
  const [items, setItems] = useState<KnowledgeBaseSummary[]>([])
  const [indexInfo, setIndexInfo] = useState<{ chunks: number; embedded: number }>({
    chunks: 0,
    embedded: 0
  })
  const [selected, setSelected] = useState<KbKind | null>(null)
  const [loading, setLoading] = useState(true)
  const [reindexing, setReindexing] = useState(false)

  const load = async (): Promise<void> => {
    if (!project) {
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      const data = await api.knowledgeBases(project.id)
      setItems(data.items)
      setIndexInfo(data.index)
    } catch {
      setItems([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [project?.id])

  const reindexAll = async (): Promise<void> => {
    if (!project) return
    setReindexing(true)
    try {
      await api.reindex(project.id)
      await load()
    } finally {
      setReindexing(false)
    }
  }

  if (selected) {
    return (
      <KnowledgeDetail
        kind={selected}
        onBack={() => {
          setSelected(null)
          void load()
        }}
      />
    )
  }

  const totalEntries = items.reduce((sum, item) => sum + item.count, 0)

  return (
    <div className="page">
      <div className="page-header">
        <div className="page-title-block">
          <h1>知识库</h1>
          <p>
            共 {totalEntries} 个条目 · {indexInfo.chunks} 个切片
            {indexInfo.embedded > 0 ? ` · ${indexInfo.embedded} 个向量` : ''}
          </p>
        </div>
        <div className="page-actions">
          <button className="ghost-btn" onClick={() => void reindexAll()} disabled={reindexing}>
            <RefreshCw size={13} />
            {reindexing ? '重建中…' : '重建索引'}
          </button>
        </div>
      </div>

      <div className="page-scroll">
        {loading && <div className="panel-empty">正在读取知识库…</div>}

        <div className="kb-page-grid">
          {items.map((item) => (
            <div key={item.kind} className="kb-card" onClick={() => setSelected(item.kind)}>
              <div className="kb-card-icon">
                <Database size={16} />
              </div>
              <div className="kb-card-body">
                <div className="kb-card-title">{item.name}</div>
                <div className="kb-card-stats">
                  {item.count} 条目 · {item.chunks} 切片
                </div>
              </div>
              <ChevronRight size={15} className="kb-card-arrow" />
            </div>
          ))}
        </div>

        {!loading && items.every((item) => item.count === 0) && (
          <div className="empty-block" style={{ marginTop: 16 }}>
            <Database size={20} />
            <div>知识库还是空的</div>
            <p>可以导入整本书，或在右栏知识库面板里新建条目，Agent 也能直接写入。</p>
          </div>
        )}
      </div>
    </div>
  )
}
