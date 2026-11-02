import { useEffect, useState } from 'react'
import { ArrowLeft, RefreshCw, Search } from 'lucide-react'
import { api } from '../api'
import { KB_LABELS, useAppStore } from '../store'
import type { ChunkItem, Entity, KbConfig, KbKind, SearchHit } from '../types'

type TabKey = 'docs' | 'chunks' | 'test' | 'settings'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'docs', label: '文档' },
  { key: 'chunks', label: '切片' },
  { key: 'test', label: '召回测试' },
  { key: 'settings', label: '设置' }
]

const DEFAULT_CONFIG: KbConfig = {
  top_k: 8,
  threshold: 0,
  mode: 'hybrid',
  alpha: 0.4,
  chapter_limit: null
}

export default function KnowledgeDetail({
  kind,
  onBack
}: {
  kind: KbKind
  onBack: () => void
}): React.JSX.Element {
  const project = useAppStore((state) => state.activeProject)

  const [tab, setTab] = useState<TabKey>('docs')
  const [entities, setEntities] = useState<Entity[]>([])
  const [activeEntity, setActiveEntity] = useState<Entity | null>(null)
  const [chunks, setChunks] = useState<ChunkItem[]>([])
  const [chunkTotal, setChunkTotal] = useState(0)
  const [config, setConfig] = useState<KbConfig>(DEFAULT_CONFIG)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchHit[]>([])
  const [searching, setSearching] = useState(false)
  const [saving, setSaving] = useState(false)
  const [reindexing, setReindexing] = useState(false)

  useEffect(() => {
    if (!project) return
    void (async () => {
      try {
        const [entityList, chunkData, cfg] = await Promise.all([
          api.entities(project.id, kind),
          api.chunks(project.id, kind, 80, 0),
          api.kbConfig(project.id)
        ])
        setEntities(entityList)
        setActiveEntity(entityList[0] ?? null)
        setChunks(chunkData.items)
        setChunkTotal(chunkData.total)
        setConfig(cfg)
      } catch {
        /* 保持空状态 */
      }
    })()
  }, [project?.id, kind])

  const runSearch = async (): Promise<void> => {
    if (!project || !query.trim()) return
    setSearching(true)
    try {
      const result = await api.search(project.id, query, {
        kinds: [kind],
        top_k: config.top_k,
        threshold: config.threshold,
        mode: config.mode,
        alpha: config.alpha,
        chapter_limit: config.chapter_limit
      })
      setResults(result.results)
    } finally {
      setSearching(false)
    }
  }

  const saveConfig = async (): Promise<void> => {
    if (!project) return
    setSaving(true)
    try {
      setConfig(await api.saveKbConfig(project.id, config))
    } finally {
      setSaving(false)
    }
  }

  const reindex = async (): Promise<void> => {
    if (!project) return
    setReindexing(true)
    try {
      await api.reindex(project.id)
      const chunkData = await api.chunks(project.id, kind, 80, 0)
      setChunks(chunkData.items)
      setChunkTotal(chunkData.total)
    } finally {
      setReindexing(false)
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <div className="page-title-block">
          <button className="back-link" onClick={onBack}>
            <ArrowLeft size={13} />
            知识库
          </button>
          <h1>{KB_LABELS[kind]}</h1>
          <p>
            {entities.length} 个条目 · {chunkTotal} 个切片
          </p>
        </div>
        <div className="page-actions">
          <button className="ghost-btn" onClick={() => void reindex()} disabled={reindexing}>
            <RefreshCw size={13} />
            {reindexing ? '重建中…' : '重建索引'}
          </button>
        </div>
      </div>

      <div className="page-tabs">
        {TABS.map((item) => (
          <button
            key={item.key}
            className={`page-tab ${tab === item.key ? 'active' : ''}`}
            onClick={() => setTab(item.key)}
          >
            {item.label}
          </button>
        ))}
      </div>

      {tab === 'docs' && (
        <div className="kb-doc-layout">
          <div className="kb-doc-list">
            {entities.map((entity) => (
              <div
                key={entity.id}
                className={`kb-doc-item ${activeEntity?.id === entity.id ? 'active' : ''}`}
                onClick={() => setActiveEntity(entity)}
              >
                <div className="kb-doc-title">{entity.title}</div>
                <div className="kb-doc-meta">{entity.file}</div>
              </div>
            ))}
            {entities.length === 0 && <div className="panel-empty">还没有条目</div>}
          </div>

          <div className="kb-doc-preview">
            {activeEntity ? (
              <>
                <div className="kb-doc-preview-head">
                  <span>{activeEntity.title}</span>
                  <span className="kb-doc-meta">{activeEntity.file}</span>
                </div>
                <pre className="kb-doc-text">{formatEntity(activeEntity)}</pre>
              </>
            ) : (
              <div className="panel-empty">选择左侧条目查看内容</div>
            )}
          </div>
        </div>
      )}

      {tab === 'chunks' && (
        <div className="page-scroll">
          <div className="chunk-list">
            {chunks.map((chunk) => (
              <div key={chunk.id} className="chunk-card">
                <div className="chunk-head">
                  <span className="chunk-title">{chunk.title}</span>
                  <span className="chunk-source">
                    {chunk.source}
                    {chunk.chapter ? ` · 第${chunk.chapter}章` : ''}
                  </span>
                </div>
                <div className="chunk-text">{chunk.text}</div>
              </div>
            ))}
            {chunks.length === 0 && (
              <div className="panel-empty">暂无切片，点右上角「重建索引」</div>
            )}
          </div>
        </div>
      )}

      {tab === 'test' && (
        <div className="test-layout">
          <aside className="test-params">
            <div className="test-params-title">检索参数</div>
            <ConfigFields config={config} onChange={(patch) => setConfig({ ...config, ...patch })} />
          </aside>

          <div className="test-main">
            <div className="test-search">
              <div className="search-box" style={{ flex: 1 }}>
                <Search size={14} />
                <input
                  value={query}
                  placeholder="输入一个问题，测试能召回什么"
                  onChange={(event) => setQuery(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') void runSearch()
                  }}
                />
              </div>
              <button
                className="primary-btn"
                onClick={() => void runSearch()}
                disabled={searching || !query.trim()}
              >
                {searching ? '检索中…' : '测试'}
              </button>
            </div>

            <div className="test-results">
              {results.map((hit) => (
                <div key={`${hit.id}-${hit.source}`} className="hit-card">
                  <div className="hit-head">
                    <span className="hit-title">{hit.title}</span>
                    <span className="hit-tags">
                      {hit.routed && (
                        <span className="hit-tag routed" title="查询里点名了该实体，已按实体路由置顶">
                          命中实体
                        </span>
                      )}
                      {hit.lexical_rank !== undefined && (
                        <span className="hit-tag kw" title="BM25 关键词检索中的名次">
                          关键词 #{hit.lexical_rank}
                        </span>
                      )}
                      {hit.vector_score !== undefined && (
                        <span className="hit-tag vec" title="余弦相似度（1 − distance）">
                          向量 {hit.vector_score.toFixed(3)}
                        </span>
                      )}
                      <span
                        className="hit-score"
                        title={
                          hit.raw_score !== undefined ? `融合后原始分 ${hit.raw_score}` : undefined
                        }
                      >
                        {hit.score.toFixed(3)}
                      </span>
                    </span>
                  </div>
                  <div className="hit-source">
                    {hit.source}
                    {hit.chapter ? ` · 第${hit.chapter}章` : ''}
                  </div>
                  <div className="hit-text">{hit.text.slice(0, 400)}</div>
                </div>
              ))}
              {results.length === 0 && (
                <div className="panel-empty">
                  输入查询后点击测试
                  <br />
                  混合检索会同时跑关键词与向量，按相关度融合
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {tab === 'settings' && (
        <div className="page-scroll">
          <div className="settings-panel">
            <div className="test-params-title">检索配置（保存后作为默认参数）</div>
            <ConfigFields
              config={config}
              onChange={(patch) => setConfig({ ...config, ...patch })}
            />
            <div className="settings-actions">
              <button className="primary-btn" onClick={() => void saveConfig()} disabled={saving}>
                {saving ? '保存中…' : '保存配置'}
              </button>
            </div>
            <p className="settings-hint">
              返回数量控制注入上下文的最大条数；最低相对分 = 命中分 ÷ 本轮最高分，
              0 表示不过滤；关键词权重仅在混合检索下生效；章节上限用于写作时避免剧透。
            </p>
          </div>
        </div>
      )}
    </div>
  )
}

function ConfigFields({
  config,
  onChange
}: {
  config: KbConfig
  onChange: (patch: Partial<KbConfig>) => void
}): React.JSX.Element {
  return (
    <div className="config-fields">
      <div className="field">
        <label>检索模式</label>
        <select
          value={config.mode}
          onChange={(event) => onChange({ mode: event.target.value as KbConfig['mode'] })}
        >
          <option value="hybrid">混合检索</option>
          <option value="keyword">关键词（BM25）</option>
          <option value="vector">向量</option>
        </select>
      </div>

      <div className="field">
        <label>返回数量</label>
        <input
          type="number"
          min={1}
          max={20}
          value={config.top_k}
          onChange={(event) => onChange({ top_k: Number(event.target.value) || 8 })}
        />
      </div>

      <div className="field">
        <label>最低相对分：{config.threshold.toFixed(2)}</label>
        <input
          type="range"
          min={0}
          max={0.95}
          step={0.05}
          value={config.threshold}
          onChange={(event) => onChange({ threshold: Number(event.target.value) })}
        />
      </div>

      <div className="field">
        <label>关键词权重：{config.alpha.toFixed(2)}</label>
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={config.alpha}
          disabled={config.mode !== 'hybrid'}
          onChange={(event) => onChange({ alpha: Number(event.target.value) })}
        />
      </div>

      <div className="field">
        <label>章节上限（防剧透）</label>
        <input
          type="number"
          min={0}
          placeholder="不限"
          value={config.chapter_limit ?? ''}
          onChange={(event) =>
            onChange({ chapter_limit: event.target.value ? Number(event.target.value) : null })
          }
        />
      </div>
    </div>
  )
}

function formatEntity(entity: Entity): string {
  const metaLines = Object.entries(entity.meta).map(([key, value]) => {
    const text = typeof value === 'string' ? value : JSON.stringify(value)
    return `${key}: ${text}`
  })
  return `---\n${metaLines.join('\n')}\n---\n\n${entity.body}`
}
