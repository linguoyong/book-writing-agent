import { useRef, useState } from 'react'
import EditorPane from './EditorPane'
import ChatPane from './ChatPane'

export default function CenterPane(): React.JSX.Element {
  const [editorHeight, setEditorHeight] = useState(52)
  const containerRef = useRef<HTMLDivElement>(null)

  const startDrag = (): void => {
    const container = containerRef.current
    if (!container) return
    const rect = container.getBoundingClientRect()

    const onMove = (event: MouseEvent): void => {
      const percent = ((event.clientY - rect.top) / rect.height) * 100
      setEditorHeight(Math.min(80, Math.max(18, percent)))
    }
    const onUp = (): void => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
      document.body.style.cursor = ''
    }
    document.body.style.cursor = 'row-resize'
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }

  return (
    <main className="center" ref={containerRef}>
      <div className="editor-pane" style={{ height: `${editorHeight}%`, flex: 'none' }}>
        <EditorPane />
      </div>
      <div className="splitter" onMouseDown={startDrag} />
      <ChatPane />
    </main>
  )
}
