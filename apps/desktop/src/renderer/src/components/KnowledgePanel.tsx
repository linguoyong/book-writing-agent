import { useState } from 'react'
import { Plus, RefreshCw, Search, Trash2, X } from 'lucide-react'
import { KB_LABELS, useAppStore } from '../store'
import type { KbKind, SearchHit } from '../types'

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
  const kbActive = useAppStore((state) => state.kbActive)
  const kbSearch = useAppStore((state) => state.kbSearch)
  const loadKb = useAppStore((state) => state.loadKb)
  const selectKbEntity = useAppStore((state) => state.selectKbEntity)
  const createKbEntity = useAppStore((state) => state.createKbEntity)
  const patchKbActive = useAppStore((state) => state.patchKbActive)
  const saveKbActive = useAppStore((state) => state.saveKbActive)
  const deleteKbActive = useAppStore((state) => state.deleteKbActive)
  const searchKb = useAppStore((state) => state.searchKb)
  const openFileByPath = useAppStore((state) => state.openFileByPath)

  const [query, setQuery] = useState('')
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')

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
            {kind === kbKind && kbItems.length > 0 ? ` ${kbItems.length}` : ''}
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
        <button
          className="small-btn primary"
          onClick={() => setCreating(true)}
          title="新建条目"
        >
          <Plus size={12} />
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
                <div className="hit-text">{hit.text.slice(0, 160)}</div>
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
                  {String(item.meta.aliases ?? item.meta.status ?? item.meta.type ?? item.id)}
                </div>
              </div>
            ))}

        {kbItems.length === 0 && !query && (
          <div className="panel-empty">还没有{KB_LABELS[kbKind]}条目</div>
        )}
        {query && kbSearch.length === 0 && <div className="panel-empty">没有检索结果</div>}
      </div>

      {kbActive && (
        <div className="kb-editor">
          <div className="kb-editor-header">
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
              onClick={() => void saveKbActive()}
              title="保存"
            >
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
          <div className="kb-editor-body">
            <pre className="kb-meta">{JSON.stringify(kbActive.meta, null, 2)}</pre>
            <textarea
              value={kbActive.body}
              placeholder="正文内容（Markdown）"
              onChange={(event) => patchKbActive({ body: event.target.value })}
            />
            <div className="kb-editor-actions">
              <button className="small-btn" onClick={() => void loadKb(kbKind)} title="刷新列表">
                <RefreshCw size={12} />
                刷新
              </button>
            </div>
          </div>
        </div>
      )}

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
