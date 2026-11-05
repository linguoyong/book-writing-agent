import { useEffect, useMemo, useRef, useState } from 'react'
import { Check, FileText, RefreshCw, RotateCcw, Save } from 'lucide-react'
import { api } from '../api'
import { useAppStore } from '../store'
import type { PromptDetail, PromptLayerInfo } from '../types'
import ConfirmDialog, { type ConfirmRequest } from '../components/ConfirmDialog'

/** 系统提示词编辑：左边是层清单，右边是编辑器（文件式布局）。 */
export default function PromptsPage(): React.JSX.Element {
  const project = useAppStore((state) => state.activeProject)
  const focus = useAppStore((state) => state.promptFocus)
  const setPromptFocus = useAppStore((state) => state.setPromptFocus)
  const showToast = useAppStore((state) => state.showToast)

  const [items, setItems] = useState<PromptLayerInfo[]>([])
  const [layer, setLayer] = useState('identity')
  const [detail, setDetail] = useState<PromptDetail | null>(null)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null)
  const loading = useRef(false)

  const dirty = detail ? draft !== detail.content : false

  const loadList = async (): Promise<void> => {
    try {
      const data = await api.prompts(project?.id)
      setItems(data.items)
      return
    } catch {
      setItems([])
    }
  }

  const loadLayer = async (name: string): Promise<void> => {
    loading.current = true
    try {
      const data = await api.prompt(name, project?.id)
      setDetail(data)
      setDraft(data.content)
    } catch (error) {
      showToast((error as Error).message)
    } finally {
      loading.current = false
    }
  }

  useEffect(() => {
    void (async () => {
      await loadList()
      const next = focus ?? 'identity'
      setLayer(next)
      setPromptFocus(null)
      await loadLayer(next)
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.id])

  useEffect(() => {
    if (loading.current) return
    if (!items.some((item) => item.layer === layer)) return
    void loadLayer(layer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layer])

  const current = useMemo(
    () => items.find((item) => item.layer === layer) ?? null,
    [items, layer]
  )

  const save = async (): Promise<void> => {
    if (!detail) return
    setBusy(true)
    try {
      await api.savePrompt(layer, draft, project?.id)
      await loadLayer(layer)
      await loadList()
      showToast('已保存，下一轮对话生效')
    } catch (error) {
      showToast((error as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const reset = (): void => {
    if (!current) return
    setConfirm({
      title: `恢复默认「${current.label}」`,
      message: '会删掉自定义内容，回到内置文案。',
      confirmLabel: '恢复默认',
      danger: true,
      onConfirm: () => {
        void (async () => {
          try {
            await api.resetPrompt(layer, project?.id)
            await loadLayer(layer)
            await loadList()
            showToast('已恢复默认')
          } catch (error) {
            showToast((error as Error).message)
          }
        })()
      }
    })
  }

  const over = current ? current.chars > current.limit : false

  return (
    <div className="prompts-page">
      <header className="prompts-head">
        <div>
          <span className="prompts-title">
            <FileText size={14} />
            系统提示词
          </span>
          <span className="prompts-sub">
            每一层都会在每轮对话里注入；技能索引与运行态由程序生成，不可编辑
          </span>
        </div>
        <button className="small-btn" onClick={() => void loadList()} title="重新读取">
          <RefreshCw size={12} />
          刷新
        </button>
      </header>

      <div className="prompts-body">
        <div className="prompts-list">
          {items.map((item) => (
            <button
              key={item.layer}
              className={`prompts-item ${item.layer === layer ? 'active' : ''}`}
              onClick={() => setLayer(item.layer)}
              title={item.path}
            >
              <span className="prompts-item-name">
                {item.label}
                {item.customized && <span className="prompts-badge">已改</span>}
              </span>
              <span className={`prompts-item-size ${item.chars > item.limit ? 'over' : ''}`}>
                {item.chars} / {item.limit}
              </span>
            </button>
          ))}
        </div>

        <div className="prompts-editor">
          {detail ? (
            <>
              <div className="prompts-editor-head">
                <span className="prompts-path" title={detail.path}>
                  {detail.path}
                </span>
                <span className={`prompts-count ${over ? 'over' : ''}`}>
                  {draft.length} 字
                  {over && ` · 超出 ${current?.limit ?? 0} 的预算，超出的部分会被截断`}
                </span>
                {detail.overridable && (
                  <button className="small-btn" onClick={reset} title="删掉自定义内容">
                    <RotateCcw size={12} />
                    恢复默认
                  </button>
                )}
              </div>
              <textarea
                className="prompts-textarea"
                value={draft}
                spellCheck={false}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="这一层要注入的内容…"
              />
              <div className="prompts-foot">
                <span className="prompts-hint">
                  {dirty ? '有未保存的修改' : '已保存'}
                  {detail.overridable ? ' · 留空即不注入' : ' · 这是记忆文件，会被 Agent 追加内容'}
                </span>
                <button
                  className="primary-btn"
                  onClick={() => void save()}
                  disabled={!dirty || busy}
                >
                  {busy ? <RefreshCw size={12} className="spin" /> : <Save size={12} />}
                  保存
                </button>
              </div>
            </>
          ) : (
            <div className="panel-empty">选择左侧的一层开始编辑</div>
          )}
        </div>
      </div>

      {confirm && <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />}
    </div>
  )
}
