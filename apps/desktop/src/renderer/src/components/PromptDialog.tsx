import { useEffect, useRef, useState } from 'react'
import { useAppStore } from '../store'

/**
 * 应用内输入框：替代 `window.prompt`。
 *
 * Electron 不实现 `window.prompt`（调用会抛错），所以「提交」「新建文件 /
 * 文件夹」「重命名」「新建章节」这些入口在桌面端原本是失效的。
 */
export default function PromptDialog(): React.JSX.Element | null {
  const request = useAppStore((state) => state.promptRequest)
  const resolvePrompt = useAppStore((state) => state.resolvePrompt)
  const [value, setValue] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!request) return
    setValue(request.value)
    // 等弹层挂载后再聚焦，首帧拿不到 ref
    const timer = window.setTimeout(() => {
      inputRef.current?.focus()
      inputRef.current?.select()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [request])

  if (!request) return null

  const submit = (): void => {
    const text = value.trim()
    if (!text && !request.allowEmpty) return
    resolvePrompt(text)
  }

  return (
    <div
      className="modal-mask"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) resolvePrompt(null)
      }}
    >
      <div className="modal confirm-modal" role="dialog" aria-modal="true" aria-label={request.title}>
        <div className="confirm-head">{request.title}</div>
        <div className="prompt-body">
          <input
            ref={inputRef}
            className="prompt-input"
            value={value}
            placeholder={request.placeholder}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault()
                submit()
              } else if (event.key === 'Escape') {
                event.preventDefault()
                resolvePrompt(null)
              }
            }}
          />
        </div>
        <div className="modal-footer">
          <button className="small-btn" onClick={() => resolvePrompt(null)}>
            取消
          </button>
          <button
            className="small-btn primary"
            onClick={submit}
            disabled={!value.trim() && !request.allowEmpty}
          >
            确定
          </button>
        </div>
      </div>
    </div>
  )
}
