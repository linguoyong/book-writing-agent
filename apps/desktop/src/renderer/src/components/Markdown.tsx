import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useAppStore } from '../store'

function nodeText(node: React.ReactNode): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(nodeText).join('')
  if (node && typeof node === 'object' && 'props' in node) {
    const props = (node as { props?: { children?: React.ReactNode } }).props
    return nodeText(props?.children)
  }
  return ''
}

export default function Markdown({ content }: { content: string }): React.JSX.Element {
  const showToast = useAppStore((state) => state.showToast)

  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => (
            <a
              href={href}
              onClick={(event) => {
                event.preventDefault()
                if (href) void window.desktop?.openExternal?.(href)
              }}
            >
              {children}
            </a>
          ),
          table: ({ children }) => (
            <div className="md-table">
              <table>{children}</table>
            </div>
          ),
          pre: ({ children }) => {
            const text = nodeText(children).replace(/\n$/, '')
            return (
              <div className="md-code">
                <button
                  className="md-copy"
                  onClick={() => {
                    void navigator.clipboard
                      .writeText(text)
                      .then(() => showToast('代码已复制'))
                      .catch(() => showToast('复制失败：当前环境不允许访问剪贴板'))
                  }}
                  title="复制代码"
                >
                  复制
                </button>
                <pre>{children}</pre>
              </div>
            )
          }
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}
