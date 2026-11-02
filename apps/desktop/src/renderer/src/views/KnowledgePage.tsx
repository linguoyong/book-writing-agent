import { useEffect, useState } from 'react'
import { AlertTriangle, ChevronRight, Database, RefreshCw, Upload } from 'lucide-react'
import { api } from '../api'
import { useAppStore } from '../store'
import type { IndexJob, KbKind, KnowledgeBaseSummary } from '../types'
import KnowledgeDetail from './KnowledgeDetail'
import ImportModal from '../components/ImportModal'

interface IndexInfo {
  chunks: number
  embedded: number
  provider?: string
  model?: string
  dim?: number
  expected_dim?: number
  backend?: string
  error?: string
}

export default function KnowledgePage(): React.JSX.Element {
  const project = useAppStore((state) => state.activeProject)
  const [items, setItems] = useState<KnowledgeBaseSummary[]>([])
  const [indexInfo, setIndexInfo] = useState<IndexInfo>({ chunks: 0, embedded: 0 })
  const [selected, setSelected] = useState<KbKind | null>(null)
  const [loading, setLoading] = useState(true)
  const [reindexing, setReindexing] = useState(false)
  const [job, setJob] = useState<IndexJob | null>(null)
  const [importOpen, setImportOpen] = useState(false)

  const load = async (): Promise<void> => {
    if (!project) {
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      const data = await api.knowledgeBases(project.id)
      setItems(data.items)
      setIndexInfo(data.index as IndexInfo)
    } catch {
      setItems([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [project?.id])

  const waitIndexJob = async (): Promise<void> => {
    if (!project) return
    // 后台建索引：本地向量要逐批编码，可能跑几分钟，轮询到结束为止
    for (let tick = 0; tick < 1800; tick += 1) {
      await new Promise((resolve) => setTimeout(resolve, 1000))
      const status = await api.indexStatus(project.id)
      setJob(status)
      if (!status.running) break
    }
    await load()
  }

  const reindexAll = async (): Promise<void> => {
    if (!project) return
    setReindexing(true)
    setJob(null)
    try {
      await api.reindex(project.id)
      await waitIndexJob()
    } finally {
      setReindexing(false)
    }
  }

  const afterImport = async (): Promise<void> => {
    setReindexing(true)
    try {
      await waitIndexJob()
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
  const vectorOn = (indexInfo.provider ?? 'none') !== 'none'
  const missingVectors = vectorOn && indexInfo.chunks > 0 && indexInfo.embedded < indexInfo.chunks
  const expectedDim = indexInfo.expected_dim ?? 0
  const dimMismatch =
    vectorOn &&
    expectedDim > 0 &&
    (indexInfo.dim ?? 0) > 0 &&
    expectedDim !== indexInfo.dim

  const subtitle = [
    `共 ${totalEntries} 个条目`,
    `${indexInfo.chunks} 个切片`,
    vectorOn
      ? `${indexInfo.embedded} 个向量${indexInfo.dim ? ` · ${indexInfo.dim} 维` : ''}`
      : '仅关键词检索',
    indexInfo.model ? indexInfo.model.split('/').pop() : ''
  ]
    .filter(Boolean)
    .join(' · ')

  return (
    <div className="page">
      <div className="page-header">
        <div className="page-title-block">
          <h1>知识库</h1>
          <p>{subtitle}</p>
        </div>
        <div className="page-actions">
          <button className="ghost-btn" onClick={() => setImportOpen(true)} disabled={reindexing}>
            <Upload size={13} />
            导入整本书
          </button>
          <button className="ghost-btn" onClick={() => void reindexAll()} disabled={reindexing}>
            <RefreshCw size={13} className={reindexing ? 'spin' : ''} />
            {reindexing
              ? job?.total
                ? `重建中 ${job.done ?? 0}/${job.total}${formatEta(job.eta_seconds)}`
                : '重建中…'
              : '重建索引'}
          </button>
        </div>
      </div>

      <div className="page-scroll">
        {loading && <div className="panel-empty">正在读取知识库…</div>}

        {!loading && dimMismatch && (
          <div className="kb-notice">
            <AlertTriangle size={13} />
            <span>
              索引里是 {indexInfo.dim} 维向量，当前模型输出 {expectedDim} 维。换过模型或维度后必须重建索引，
              否则语义检索会一直为空。
            </span>
          </div>
        )}
        {!loading && !dimMismatch && missingVectors && (
          <div className="kb-notice">
            <AlertTriangle size={13} />
            <span>
              {indexInfo.provider === 'local'
                ? '本地向量模型已启用，但索引里还没有向量'
                : '向量服务已启用，但索引里还没有向量'}
              （{indexInfo.embedded}/{indexInfo.chunks}）。点右上角「重建索引」补齐，否则语义检索为空。
            </span>
          </div>
        )}
        {!loading && indexInfo.error && !missingVectors && !dimMismatch && (
          <div className="kb-notice warn">
            <AlertTriangle size={13} />
            <span>{indexInfo.error}</span>
          </div>
        )}

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

      {importOpen && (
        <ImportModal onClose={() => setImportOpen(false)} onDone={() => void afterImport()} />
      )}
    </div>
  )
}

function formatEta(seconds?: number): string {
  if (!seconds || seconds <= 0) return ''
  if (seconds < 90) return ' · 约 1 分钟'
  return ` · 约 ${Math.round(seconds / 60)} 分钟`
}
