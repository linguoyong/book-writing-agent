import { useEffect, useMemo, useRef, useState } from 'react'
import CodeMirror, { type ReactCodeMirrorRef } from '@uiw/react-codemirror'
import { markdown } from '@codemirror/lang-markdown'
import {
  Check,
  Clipboard,
  Eye,
  FileCode2,
  FolderOpen,
  Loader2,
  PanelRight,
  Save,
  Sparkles,
  X
} from 'lucide-react'
import { api } from '../api'
import { useAppStore } from '../store'
import Markdown from './Markdown'

function stripFrontMatter(text: string): string {
  // 章节文件带 front-matter，预览时别把它当正文显示出来
  const match = /^---\r?\n[\s\S]*?\r?\n---\r?\n?/.exec(text)
  return match ? text.slice(match[0].length) : text
}

export default function FileViewer({
  treeOpen = true,
  onToggleTree
}: {
  treeOpen?: boolean
  onToggleTree?: () => void
}): React.JSX.Element {
  const project = useAppStore((state) => state.activeProject)
  const openFile = useAppStore((state) => state.openFile)
  const updateOpenFile = useAppStore((state) => state.updateOpenFile)
  const saveOpenFile = useAppStore((state) => state.saveOpenFile)
  const openFileByPath = useAppStore((state) => state.openFileByPath)
  const showToast = useAppStore((state) => state.showToast)

  const [mode, setMode] = useState<'preview' | 'source'>('preview')
  const [selection, setSelection] = useState<{ from: number; to: number } | null>(null)
  const [rewriting, setRewriting] = useState(false)
  const [rewriteBusy, setRewriteBusy] = useState('')
  const [rewriteResult, setRewriteResult] = useState('')
  const [rewriteAction, setRewriteAction] = useState('')
  const [materialBusy, setMaterialBusy] = useState(false)
  const cmRef = useRef<ReactCodeMirrorRef>(null)
  const isText = !openFile || openFile.kind === 'text'
  const isMarkdown =
    isText && Boolean(openFile?.path.toLowerCase().endsWith('.md'))

  useEffect(() => {
    const markdownFile =
      openFile?.kind === 'text' && openFile.path.toLowerCase().endsWith('.md')
    setMode(markdownFile ? 'preview' : 'source')
  }, [openFile?.path, openFile?.kind])

  const frontMatterEnd = (text: string): number => {
    const match = /^---\r?\n[\s\S]*?\r?\n---\r?\n?/.exec(text)
    return match ? match[0].length : 0
  }

  const runRewrite = async (action: string): Promise<void> => {
    const view = cmRef.current?.view
    if (!project || !view || !selection) return
    // 选中范围压到文件头上时直接拦住：改写会把 title/chapter 一起换掉
    const head = frontMatterEnd(view.state.doc.toString())
    if (head && selection.from < head) {
      showToast('选中范围包含了文件头（front-matter），请从正文开始选择')
      return
    }
    const doc = view.state.doc
    const text = doc.sliceString(selection.from, selection.to)
    setRewriteBusy(action)
    setRewriteResult('')
    setRewriting(true)
    try {
      const result = await api.rewriteText(project.id, {
        text,
        action,
        before: doc.sliceString(Math.max(0, selection.from - 600), selection.from),
        after: doc.sliceString(selection.to, Math.min(doc.length, selection.to + 600))
      })
      setRewriteResult(result.text)
      setRewriteAction(action)
    } catch (error) {
      showToast((error as Error).message)
      setRewriting(false)
    } finally {
      setRewriteBusy('')
    }
  }

  const saveSelectionAsMaterial = async (): Promise<void> => {
    const view = cmRef.current?.view
    if (!project || !view || !selection) return
    const doc = view.state.doc
    const text = doc.sliceString(selection.from, selection.to).trim()
    if (!text) {
      showToast('先选中一段文字')
      return
    }
    const head = frontMatterEnd(doc.toString())
    if (head && selection.from < head) {
      showToast('选中范围包含了文件头（front-matter），请从正文开始选择')
      return
    }
    const line = doc.lineAt(selection.from).number
    setMaterialBusy(true)
    try {
      const result = await api.saveMaterial(project.id, {
        text,
        source: `${openFile?.path ?? ''} · 第 ${line} 行`
      })
      showToast(
        result.duplicate ? '这段已经在素材库里了' : `已收入素材库：${result.title}`
      )
    } catch (error) {
      showToast((error as Error).message)
    } finally {
      setMaterialBusy(false)
    }
  }

  const adoptRewrite = async (): Promise<void> => {
    const view = cmRef.current?.view
    if (!view || !selection || !rewriteResult) return
    view.dispatch({
      changes: { from: selection.from, to: selection.to, insert: rewriteResult }
    })
    // dispatch 是同步的，直接读当前文档并写回 store；
    // 不能等 onChange 或 setTimeout —— 那一拍里 saveOpenFile 可能拿到旧内容
    useAppStore.getState().updateOpenFile(view.state.doc.toString())
    setRewriting(false)
    setRewriteResult('')
    await useAppStore.getState().saveOpenFile()
    showToast('已替换选中内容并保存')
  }

  useEffect(() => {
    const handler = (event: KeyboardEvent): void => {
      if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 's') return
      const target = event.target as HTMLElement | null
      // 在设置/搜索的输入框里按 Ctrl+S 不该落盘当前章节
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA')) return
      event.preventDefault()
      void useAppStore.getState().saveOpenFile()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  const copyPath = async (): Promise<void> => {
    if (!openFile) return
    try {
      await navigator.clipboard.writeText(openFile.path)
      showToast('已复制相对路径')
    } catch {
      showToast('复制失败：当前环境不允许访问剪贴板')
    }
  }

  const reveal = (): void => {
    if (!project || !openFile) return
    void window.desktop?.showItemInFolder?.(project.path, openFile.path)
  }

  const segments = openFile?.path.split('/') ?? []

  return (
    <section className="file-viewer">
      <div className="fv-head">
        <div className="fv-crumbs" title={openFile?.path}>
          {openFile ? (
            segments.map((part, index) => (
              <span
                key={`${part}-${index}`}
                className={index === segments.length - 1 ? 'cur' : ''}
              >
                {index > 0 && <span className="fv-sep">/</span>}
                {part}
              </span>
            ))
          ) : (
            <span className="fv-idle">未打开文件</span>
          )}
        </div>
        <div className="fv-actions">
          <button
            className={`fv-icon ${treeOpen ? 'on' : ''}`}
            onClick={onToggleTree}
            title={treeOpen ? '收起文件树' : '展开文件树'}
          >
            <PanelRight size={12} />
          </button>
          {openFile?.dirty && <span className="fv-dirty">未保存</span>}
          {openFile?.truncated && <span className="fv-dirty">只读预览</span>}
          {isMarkdown && (
            <button
              className={`fv-btn ${mode === 'preview' ? 'on' : ''}`}
              onClick={() => setMode(mode === 'preview' ? 'source' : 'preview')}
              title={mode === 'preview' ? '查看源代码' : '预览 Markdown'}
            >
              {mode === 'preview' ? <FileCode2 size={12} /> : <Eye size={12} />}
              {mode === 'preview' ? '源码' : '预览'}
            </button>
          )}
          <button
            className="fv-icon"
            onClick={() => void copyPath()}
            disabled={!openFile}
            title="复制相对路径"
          >
            <Clipboard size={12} />
          </button>
          <button
            className="fv-icon"
            onClick={reveal}
            disabled={!openFile}
            title="在文件夹中打开"
          >
            <FolderOpen size={12} />
          </button>
          <button
            className="fv-icon"
            onClick={() => void saveOpenFile()}
            disabled={!openFile?.dirty || openFile?.truncated}
            title="保存（Ctrl+S）"
          >
            {openFile?.dirty ? <Save size={12} /> : <Check size={12} />}
          </button>
        </div>
      </div>

      {!rewriting && selection && mode === 'source' && openFile && !openFile.truncated && (
        <div className="fv-rewrite-bar">
          <span className="fv-rewrite-label">
            <Sparkles size={12} />
            选中 {selection.to - selection.from} 字
          </span>
          {[
            ['polish', '润色'],
            ['expand', '扩写'],
            ['shorten', '压缩']
          ].map(([action, label]) => (
            <button
              key={action}
              className="fv-rewrite-btn"
              disabled={Boolean(rewriteBusy)}
              onClick={() => void runRewrite(action)}
            >
              {rewriteBusy === action ? <Loader2 size={11} className="spin" /> : label}
            </button>
          ))}
          <span className="fv-rewrite-sep" />
          <button
            className="fv-rewrite-btn"
            disabled={materialBusy}
            onClick={() => void saveSelectionAsMaterial()}
            title="把选中内容收进知识库的素材库"
          >
            {materialBusy ? <Loader2 size={11} className="spin" /> : '收入素材'}
          </button>
        </div>
      )}

      {rewriting && (
        <div className="fv-rewrite-panel">
          <div className="fv-rewrite-head">
            <span>
              改写预览 ·
              {rewriteAction === 'polish' ? ' 润色' : rewriteAction === 'expand' ? ' 扩写' : ' 压缩'}
            </span>
            <button
              className="icon-btn"
              onClick={() => {
                setRewriting(false)
                setRewriteResult('')
              }}
              title="关闭"
            >
              <X size={13} />
            </button>
          </div>
          <div className="fv-rewrite-body">
            {rewriteBusy ? (
              <div className="panel-empty">
                <Loader2 size={14} className="spin" /> 模型改写中…
              </div>
            ) : (
              <>
                <div className="fv-rewrite-original">
                  {cmRef.current?.view && selection
                    ? cmRef.current.view.state.doc.sliceString(selection.from, selection.to)
                    : ''}
                </div>
                <div className="fv-rewrite-result">{rewriteResult}</div>
              </>
            )}
          </div>
          <div className="fv-rewrite-actions">
            <button
              className="ghost-btn"
              onClick={() => {
                setRewriting(false)
                setRewriteResult('')
              }}
            >
              放弃
            </button>
            <button className="primary-btn" disabled={!rewriteResult} onClick={() => void adoptRewrite()}>
              <Check size={12} />
              采用并保存
            </button>
          </div>
        </div>
      )}

      <div className="fv-body">
        {openFile ? (
          openFile.kind === 'image' && openFile.dataUrl ? (
            <div className="fv-image">
              <img src={openFile.dataUrl} alt={openFile.path} />
            </div>
          ) : openFile.kind === 'large' ? (
            <div className="editor-empty">
              <div>文件较大（{formatSize(openFile.size)}），未直接加载</div>
              <div className="fv-size">整份打开可能让编辑器卡顿，可只读预览前 200 KB</div>
              <button
                className="small-btn primary"
                onClick={() => void openFileByPath(openFile.path, true, 200_000)}
              >
                只读预览
              </button>
              <button className="small-btn" onClick={reveal}>
                <FolderOpen size={13} />
                在文件夹中打开
              </button>
            </div>
          ) : openFile.kind === 'binary' ? (
            <div className="editor-empty">
              <div>该文件不支持预览</div>
              <div className="fv-size">{formatSize(openFile.size)}</div>
              <button className="small-btn" onClick={reveal}>
                <FolderOpen size={13} />
                在文件夹中打开
              </button>
            </div>
          ) : mode === 'preview' && isMarkdown ? (
            <div className="fv-preview">
              <Markdown content={stripFrontMatter(openFile.content)} />
            </div>
          ) : (
            <CodeMirror
              ref={cmRef}
              value={openFile.content}
              height="100%"
              extensions={[markdown()]}
              editable={!openFile.truncated}
              basicSetup={{
                lineNumbers: true,
                foldGutter: false,
                highlightActiveLine: true,
                autocompletion: false,
                indentOnInput: false
              }}
              onUpdate={(update) => {
                if (!update.selectionSet && !update.docChanged) return
                const range = update.state.selection.main
                setSelection(range.empty ? null : { from: range.from, to: range.to })
              }}
              onChange={(value) => updateOpenFile(value)}
            />
          )
        ) : (
          <div className="editor-empty">
            <div className="editor-empty-hint">
              从右侧文件树选择文件，Markdown 默认预览、Ctrl+S 保存修改
            </div>
          </div>
        )}
      </div>
    </section>
  )
}

function formatSize(size?: number): string {
  if (!size) return ''
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}
