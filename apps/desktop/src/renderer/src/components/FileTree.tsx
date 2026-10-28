import { useState } from 'react'
import { FileText, Folder, FolderOpen } from 'lucide-react'
import { useAppStore } from '../store'
import type { TreeNode } from '../types'

export default function FileTree(): React.JSX.Element {
  const tree = useAppStore((state) => state.tree)

  if (tree.length === 0) {
    return <div className="panel-empty">项目目录为空</div>
  }

  return (
    <div className="file-tree">
      {tree.map((node) => (
        <Node key={node.path} node={node} depth={0} />
      ))}
    </div>
  )
}

function Node({ node, depth }: { node: TreeNode; depth: number }): React.JSX.Element {
  const currentPath = useAppStore((state) => state.openFile?.path)
  const openFileByPath = useAppStore((state) => state.openFileByPath)
  const [open, setOpen] = useState(depth === 0)

  if (node.type === 'file') {
    return (
      <div
        className={`tree-node ${currentPath === node.path ? 'active' : ''}`}
        style={{ paddingLeft: 8 + depth * 12 }}
        onClick={() => void openFileByPath(node.path)}
        title={node.path}
      >
        <FileText size={12} />
        {node.name}
      </div>
    )
  }

  return (
    <>
      <div
        className="tree-node"
        style={{ paddingLeft: 8 + depth * 12 }}
        onClick={() => setOpen(!open)}
      >
        {open ? <FolderOpen size={12} /> : <Folder size={12} />}
        {node.name}
      </div>
      {open &&
        node.children?.map((child) => (
          <Node key={child.path} node={child} depth={depth + 1} />
        ))}
    </>
  )
}
