import { useState } from 'react'
import FileViewer from './FileViewer'
import FileTree from './FileTree'

export default function FilesPanel(): React.JSX.Element {
  const [treeOpen, setTreeOpen] = useState(true)

  return (
    <div className={`files-panel ${treeOpen ? 'with-tree' : ''}`}>
      <FileViewer treeOpen={treeOpen} onToggleTree={() => setTreeOpen((value) => !value)} />
      {treeOpen && (
        <aside className="files-tree">
          <FileTree />
        </aside>
      )}
    </div>
  )
}
