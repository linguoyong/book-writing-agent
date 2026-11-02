import { useEffect, useRef, useState } from 'react'
import {
  ChevronDown,
  ChevronRight,
  BookPlus,
  Download,
  FilePlus2,
  FileText,
  Folder,
  FolderOpen,
  Search
} from 'lucide-react'
import { api } from '../api'
import { useAppStore } from '../store'
import type { TreeNode } from '../types'
import ConfirmDialog, { type ConfirmRequest } from './ConfirmDialog'

interface MenuState {
  x: number
  y: number
  node: TreeNode
}

const GIT_LABEL: Record<string, string> = {
  untracked: 'U',
  added: 'A',
  modified: 'M',
  deleted: 'D'
}

function shortChapterTitle(title: string): string {
  // 「第4章 雾中来客」已经带了章号，副标题里只留标题本身
  const stripped = title.replace(/^第\s*[0-9零一二三四五六七八九十百千两]+\s*[章回节]\s*/, '').trim()
  return stripped ? ` · ${stripped}` : ''
}

function formatWords(value: number): string {
  if (!value) return '0 字'
  if (value < 10000) return `${value.toLocaleString()} 字`
  return `${(value / 10000).toFixed(1)} 万字`
}

export default function FileTree(): React.JSX.Element {
  const tree = useAppStore((state) => state.tree)
  const stats = useAppStore((state) => state.overview?.stats)
  const project = useAppStore((state) => state.activeProject)
  const currentPath = useAppStore((state) => state.openFile?.path)
  const openFileByPath = useAppStore((state) => state.openFileByPath)
  const refreshTree = useAppStore((state) => state.refreshTree)
  const showToast = useAppStore((state) => state.showToast)

  const [query, setQuery] = useState('')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [menu, setMenu] = useState<MenuState | null>(null)
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null)
  const initialized = useRef(false)

  useEffect(() => {
    if (initialized.current || !tree.length) return
    initialized.current = true
    setExpanded(new Set(collectDirs(tree[0], 1)))
  }, [tree])

  const toggle = (path: string): void => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  const expandAll = (): void => setExpanded(new Set(collectDirs(tree[0], Number.MAX_SAFE_INTEGER)))
  const collapseAll = (): void => setExpanded(new Set(tree[0] ? [tree[0].path] : []))

  const openContext = (event: React.MouseEvent, node: TreeNode): void => {
    event.preventDefault()
    event.stopPropagation()
    setMenu({
      x: Math.min(event.clientX, window.innerWidth - 200),
      y: Math.min(event.clientY, window.innerHeight - 220),
      node
    })
  }

  const create = async (node: TreeNode, kind: 'file' | 'dir'): Promise<void> => {
    if (!project) return
    setMenu(null)
    const name = window.prompt(kind === 'dir' ? '新建文件夹名' : '新建文件名（可含 .md）')
    if (!name?.trim()) return
    const base = node.type === 'dir' ? node.path : parentPath(node.path)
    const relative = base && base !== '.' ? `${base}/${name.trim()}` : name.trim()
    try {
      await api.fsCreate(project.id, relative, kind)
      await refreshTree()
      if (kind === 'file') await openFileByPath(relative, true)
      showToast(`已创建 ${relative}`)
    } catch (error) {
      showToast((error as Error).message)
    }
  }

  const rename = async (node: TreeNode): Promise<void> => {
    if (!project) return
    setMenu(null)
    const next = window.prompt('重命名', node.name)
    if (!next?.trim() || next.trim() === node.name) return
    const base = parentPath(node.path)
    const target = base ? `${base}/${next.trim()}` : next.trim()
    try {
      await api.fsRename(project.id, node.path, target)
      await refreshTree()
      const opened = useAppStore.getState().openFile?.path
      if (opened === node.path) await openFileByPath(target, true)
      else if (opened?.startsWith(`${node.path}/`)) useAppStore.setState({ openFile: null })
      showToast(`已重命名为 ${next.trim()}`)
    } catch (error) {
      showToast((error as Error).message)
    }
  }

  const remove = (node: TreeNode): void => {
    if (!project) return
    setMenu(null)
    setConfirm({
      title: node.type === 'dir' ? '删除文件夹' : '删除文件',
      message: `${node.path}\n${node.type === 'dir' ? '文件夹会连同内部文件一起删除' : '文件将被删除'}，此操作不可恢复。`,
      danger: true,
      confirmLabel: '删除',
      onConfirm: () => {
        void (async () => {
          if (!project) return
          try {
            await api.fsDelete(project.id, node.path)
            await refreshTree()
            const opened = useAppStore.getState().openFile?.path
            if (opened === node.path || opened?.startsWith(`${node.path}/`)) {
              useAppStore.setState({ openFile: null })
            }
            showToast(`已删除 ${node.path}`)
          } catch (error) {
            showToast((error as Error).message)
          }
        })()
      }
    })
  }

  const copy = async (node: TreeNode): Promise<void> => {
    setMenu(null)
    try {
      await navigator.clipboard.writeText(node.path)
      showToast('已复制相对路径')
    } catch {
      showToast('复制失败：当前环境不允许访问剪贴板')
    }
  }

  const reveal = (node: TreeNode): void => {
    setMenu(null)
    if (!project) return
    void window.desktop?.showItemInFolder?.(project.path, node.path)
  }

  const newChapter = async (): Promise<void> => {
    if (!project) return
    const title = window.prompt('新章节标题（留空则自动用「第N章」）', '')
    if (title === null) return
    try {
      const result = await api.newChapter(project.id, title.trim())
      await refreshTree()
      await openFileByPath(result.path, true)
      void useAppStore.getState().refreshOverview?.()
      showToast(`已新建 ${result.title}（${result.path}）`)
    } catch (error) {
      showToast((error as Error).message)
    }
  }

  const exportBook = async (): Promise<void> => {
    if (!project) return
    const title = project.meta?.title || project.name || '成稿'
    const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, '')
    const target = await window.desktop?.saveTextFile?.(`${title}-${stamp}.txt`)
    if (!target) return
    try {
      const result = await api.exportTxt(project.id, target)
      showToast(`已导出 ${result.chapters} 章 · ${result.chars.toLocaleString()} 字 → ${result.path}`)
    } catch (error) {
      showToast((error as Error).message)
    }
  }

  const visible = query.trim() ? filterTree(tree, query.trim()) : tree
  const forceOpen = Boolean(query.trim())

  return (
    <div className="file-tree-panel">
      {stats && stats.chapters > 0 && (
        <div className="ft-stats">
          <div className="ft-stats-chapter">
            第 {stats.chapter} 章{shortChapterTitle(stats.chapter_title)}
          </div>
          <div className="ft-stats-line">
            <span>{formatWords(stats.words)}</span>
            <span className="ft-stats-today">今日 {formatWords(stats.today_words)}</span>
          </div>
          {stats.target_words > 0 && (
            <div className="ft-stats-bar" title={`目标 ${formatWords(stats.target_words)}`}>
              <span style={{ width: `${Math.min(100, Math.round(stats.progress * 100))}%` }} />
            </div>
          )}
        </div>
      )}
      <div className="ft-toolbar">
        <div className="ft-search">
          <Search size={12} />
          <input
            value={query}
            placeholder="筛选文件…"
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <button
          className="ft-icon"
          onClick={() => tree[0] && void create(tree[0], 'file')}
          disabled={!tree.length}
          title="新建文件"
        >
          <FilePlus2 size={12} />
        </button>
        <button className="ft-icon" onClick={() => void newChapter()} title="新建章节">
          <BookPlus size={12} />
        </button>
        <button className="ft-icon" onClick={() => void exportBook()} title="导出成稿（TXT）">
          <Download size={12} />
        </button>
        <button className="ft-icon" onClick={expandAll} title="全部展开">
          <ChevronDown size={12} />
        </button>
        <button className="ft-icon" onClick={collapseAll} title="全部收起">
          <ChevronRight size={12} />
        </button>
      </div>

      <div className="ft-scroll">
        {visible.length === 0 ? (
          <div className="panel-empty">{query ? '没有匹配的文件' : '项目目录为空'}</div>
        ) : (
          visible.map((node) => (
            <TreeNodeRow
              key={node.path}
              node={node}
              depth={0}
              expanded={expanded}
              forceOpen={forceOpen}
              currentPath={currentPath}
              onToggle={toggle}
              onOpen={(path) => void openFileByPath(path)}
              onContext={openContext}
            />
          ))
        )}
      </div>

      {menu && (
        <>
          <div className="ft-menu-mask" onClick={() => setMenu(null)} />
          <div className="ft-menu" style={{ left: menu.x, top: menu.y }}>
            {menu.node.type === 'dir' && (
              <>
                <button onClick={() => void create(menu.node, 'file')}>新建文件</button>
                <button onClick={() => void create(menu.node, 'dir')}>新建文件夹</button>
              </>
            )}
            <button onClick={() => void rename(menu.node)}>重命名</button>
            <button className="danger" onClick={() => remove(menu.node)}>
              删除
            </button>
            <button onClick={() => void copy(menu.node)}>复制路径</button>
            {menu.node.type === 'file' && (
              <button onClick={() => reveal(menu.node)}>在文件夹中打开</button>
            )}
          </div>
        </>
      )}
      <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />
    </div>
  )
}

function TreeNodeRow({
  node,
  depth,
  expanded,
  forceOpen,
  currentPath,
  onToggle,
  onOpen,
  onContext
}: {
  node: TreeNode
  depth: number
  expanded: Set<string>
  forceOpen: boolean
  currentPath?: string
  onToggle: (path: string) => void
  onOpen: (path: string) => void
  onContext: (event: React.MouseEvent, node: TreeNode) => void
}): React.JSX.Element {
  const isDir = node.type === 'dir'
  const open = isDir && (forceOpen || expanded.has(node.path))

  return (
    <>
      <div
        className={`ft-row ${!isDir && currentPath === node.path ? 'active' : ''}`}
        style={{ paddingLeft: 6 + depth * 12 }}
        title={node.path === '.' ? node.name : node.path}
        onClick={() => (isDir ? onToggle(node.path) : onOpen(node.path))}
        onContextMenu={(event) => onContext(event, node)}
      >
        {isDir ? (
          <>
            {open ? <ChevronDown size={11} className="ft-chev" /> : <ChevronRight size={11} className="ft-chev" />}
            {open ? <FolderOpen size={12} className="ft-dir" /> : <Folder size={12} className="ft-dir" />}
          </>
        ) : (
          <>
            <span className="ft-chev-space" />
            <FileText size={12} className="ft-file" />
          </>
        )}
        <span className="ft-name">{node.name}</span>
        {node.git &&
          (isDir ? (
            <span className="ft-dot" title="目录内有改动" />
          ) : (
            <span className={`ft-git ${node.git}`} title={`git: ${node.git}`}>
              {GIT_LABEL[node.git] ?? '•'}
            </span>
          ))}
      </div>
      {open &&
        node.children?.map((child) => (
          <TreeNodeRow
            key={child.path}
            node={child}
            depth={depth + 1}
            expanded={expanded}
            forceOpen={forceOpen}
            currentPath={currentPath}
            onToggle={onToggle}
            onOpen={onOpen}
            onContext={onContext}
          />
        ))}
    </>
  )
}

function parentPath(path: string): string {
  const index = path.lastIndexOf('/')
  return index < 0 ? '' : path.slice(0, index)
}

function collectDirs(node: TreeNode | undefined, maxDepth: number, depth = 0): string[] {
  if (!node || node.type !== 'dir') return []
  const result = [node.path]
  if (depth >= maxDepth) return result
  for (const child of node.children ?? []) {
    result.push(...collectDirs(child, maxDepth, depth + 1))
  }
  return result
}

function filterTree(nodes: TreeNode[], query: string): TreeNode[] {
  const keyword = query.toLowerCase()
  const walk = (list: TreeNode[]): TreeNode[] => {
    const result: TreeNode[] = []
    for (const node of list) {
      if (node.type === 'file') {
        if (node.name.toLowerCase().includes(keyword) || node.path.toLowerCase().includes(keyword)) {
          result.push(node)
        }
        continue
      }
      const children = walk(node.children ?? [])
      if (children.length) result.push({ ...node, children })
      else if (node.name.toLowerCase().includes(keyword)) result.push(node)
    }
    return result
  }
  return walk(nodes)
}
