import { useEffect, useState } from 'react'
import { Database, Plus, RefreshCw, Search, Trash2, X } from 'lucide-react'
import { KB_LABELS, useAppStore } from '../store'
import type { KbKind, SearchHit } from '../types'
import Markdown from './Markdown'

const KINDS: KbKind[] = [
  'characters',
  'factions',
  'items',
  'locations',
  'world',
  'outline',
  'materials',
  'styles'
]

export default function KnowledgePanel(): React.JSX.Element {
  const kbKind = useAppStore((state) => state.kbKind)
  const kbItems = useAppStore((state) => state.kbItems)
  const counts = useAppStore((state) => state.overview?.kb_counts)
  const kbActive = useAppStore((state) => state.kbActive)
  const kbSearch = useAppStore((state) => state.kbSearch)
  const loadKb = useAppStore((state) => state.loadKb)
  const selectKbEntity = useAppStore((state) => state.selectKbEntity)
  const createKbEntity = useAppStore((state) => state.createKbEntity)
  const patchKbActive = useAppStore((state) => state.patchKbActive)
  const saveKbActive = useAppStore((state) => state.saveKbActive)
  const deleteKbActive = useAppStore((state) => state.deleteKbActive)
  const searchKb = useAppStore((state) => state.searchKb)
  const reindexKb = useAppStore((state) => state.reindexKb)
  const openFileByPath = useAppStore((state) => state.openFileByPath)

  const [query, setQuery] = useState('')
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [mode, setMode] = useState<'preview' | 'edit'>('preview')

  useEffect(() => {
    setMode('preview')
  }, [kbActive?.id])

  const runSearch = (): void => {
    if (!query.trim()) {
      void searchKb('')
      return
    }
    void searchKb(query)
  }

  const openHit = async (hit: SearchHit): Promise<void> => {
    if (hit.kind === 'chapters') {
      await openFileByPath(hit.source)
      return
    }
    await loadKb(hit.kind as KbKind)
    const item = useAppStore.getState().kbItems.find((entry) => entry.id === hit.ref)
    if (item) selectKbEntity(item)
  }

  const create = async (): Promise<void> => {
    await createKbEntity(newName)
    setCreating(false)
    setNewName('')
  }

  return (
    <>
      <div className="kb-kind-bar">
        {KINDS.map((kind) => (
          <button
            key={kind}
            className={`kind-chip ${kind === kbKind ? 'active' : ''}`}
            onClick={() => void loadKb(kind)}
          >
            {KB_LABELS[kind]}
            {counts ? ` ${counts[kind] ?? 0}` : ''}
          </button>
        ))}
      </div>

      <div className="kb-toolbar">
        <input
          placeholder="检索知识库与原文…"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value)
            if (!event.target.value) void searchKb('')
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter') runSearch()
          }}
        />
        <button className="small-btn" onClick={runSearch} title="检索">
          <Search size={12} />
        </button>
        <button className="small-btn" onClick={() => void reindexKb()} title="重建索引">
          <Database size={12} />
        </button>
        <button
          className="small-btn primary"
          onClick={() => setCreating(true)}
          title="新建条目"
        >
          <Plus size={12} />
        </button>
      </div>

      <div className="kb-workspace">
        <div className="kb-detail">
          {kbActive ? (
            <>
              <div className="kb-detail-head">
                <input
                  value={kbActive.title}
                  onChange={(event) =>
                    patchKbActive({
                      title: event.target.value,
                      meta: { ...kbActive.meta, name: event.target.value }
                    })
                  }
                />
                <button
                  className="small-btn"
                  onClick={() => setMode(mode === 'preview' ? 'edit' : 'preview')}
                  title={mode === 'preview' ? '编辑 Markdown' : '预览'}
                >
                  {mode === 'preview' ? '编辑' : '预览'}
                </button>
                <button className="small-btn" onClick={() => void saveKbActive()} title="保存">
                  保存
                </button>
                <button
                  className="icon-btn"
                  onClick={() => {
                    if (window.confirm(`删除「${kbActive.title}」？`)) void deleteKbActive()
                  }}
                  title="删除"
                >
                  <Trash2 size={13} />
                </button>
              </div>

              <div className="kb-detail-body">
                {mode === 'preview' ? (
                  <div className="kb-md">
                    <Markdown content={kbActive.body || '（暂无正文）'} />
                  </div>
                ) : (
                  <textarea
                    className="kb-source"
                    value={kbActive.body}
                    placeholder="正文内容（Markdown）"
                    onChange={(event) => patchKbActive({ body: event.target.value })}
                  />
                )}
                <details className="kb-meta-fold">
                  <summary>元数据</summary>
                  <pre className="kb-meta">{JSON.stringify(kbActive.meta, null, 2)}</pre>
                </details>
              </div>
            </>
          ) : (
            <div className="editor-empty">
              <div className="editor-empty-hint">
                从右侧选择条目；正文默认 Markdown 预览，可切换编辑
              </div>
            </div>
          )}
        </div>

        <aside className="kb-side-list">
          <div className="kb-side-title">
            条目 · {query && kbSearch.length > 0 ? kbSearch.length : kbItems.length}
            <button className="ft-icon" onClick={() => void loadKb(kbKind)} title="刷新列表">
              <RefreshCw size={11} />
            </button>
          </div>
          <div className="kb-list">
            {query && kbSearch.length > 0
              ? kbSearch.map((hit) => (
                  <div
                    key={`${hit.id}-${hit.source}`}
                    className="search-hit"
                    onClick={() => void openHit(hit)}
                  >
                    <div className="hit-title">
                      <span className="hit-kind">
                        {KB_LABELS[hit.kind as KbKind] ?? '原文'}
                      </span>
                      {hit.title}
                    </div>
                    <div className="hit-text">{hit.text.slice(0, 120)}</div>
                  </div>
                ))
              : kbItems.map((item) => (
                  <div
                    key={item.id}
                    className={`kb-item ${item.id === kbActive?.id ? 'active' : ''}`}
                    onClick={() => selectKbEntity(item)}
                  >
                    <div className="title">{item.title}</div>
                    <div className="meta-line">
                      {String(
                        item.meta.aliases ?? item.meta.status ?? item.meta.type ?? item.id
                      )}
                    </div>
                  </div>
                ))}

            {kbItems.length === 0 && !query && (
              <div className="panel-empty">还没有{KB_LABELS[kbKind]}条目</div>
            )}
            {query && kbSearch.length === 0 && (
              <div className="panel-empty">没有检索结果</div>
            )}
          </div>
        </aside>
      </div>

      {creating && (
        <div className="modal-mask" onClick={() => setCreating(false)}>
          <div className="modal" style={{ width: 360 }} onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <span>新建{KB_LABELS[kbKind]}条目</span>
              <button className="icon-btn" onClick={() => setCreating(false)}>
                <X size={14} />
              </button>
            </div>
            <div className="modal-body">
              <div className="field">
                <label>名称（同时作为条目 id）</label>
                <input
                  autoFocus
                  value={newName}
                  onChange={(event) => setNewName(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') void create()
                  }}
                  placeholder="例如：林昭"
                />
              </div>
            </div>
            <div className="modal-footer">
              <button className="ghost-btn" onClick={() => setCreating(false)}>
                取消
              </button>
              <button className="primary-btn" disabled={!newName.trim()} onClick={() => void create()}>
                创建
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
