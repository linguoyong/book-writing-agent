import { memo, useEffect, useState } from 'react'
import { AlertTriangle, Check, ChevronRight, Copy, CornerUpLeft, Loader2, Pencil, RotateCcw, Wrench } from 'lucide-react'
import { formatTokens } from '../format'
import { useAppStore } from '../store'
import type { TimelineItem } from '../types'
import type { TurnView } from './conversation'
import Markdown from './Markdown'
import { executionProgress, toolProgress } from './progress'

function TurnBlock({
  turn,
  live,
  isLast,
  startedAt,
  side = false,
  onEdit,
  onRetry,
  onBring
}: {
  turn: TurnView
  live: boolean
  isLast?: boolean
  startedAt: number | null
  side?: boolean
  onEdit?: (text: string) => void
  onRetry?: () => void
  onBring?: (text: string) => void
}): React.JSX.Element {
  const regenerate = useAppStore((state) => state.regenerate)
  const approval = useAppStore((state) => state.approval)
  const retryLastTurn = useAppStore((state) => state.retryLastTurn)
  const setPendingComposer = useAppStore((state) => state.setPendingComposer)
  const showToast = useAppStore((state) => state.showToast)
  const streaming = useAppStore((state) => state.streaming)
  const [now, setNow] = useState(Date.now())

  const copy = (text: string): void => {
    void navigator.clipboard
      .writeText(text)
      .then(() => showToast('已复制'))
      .catch(() => showToast('复制失败：当前环境不允许访问剪贴板'))
  }

  useEffect(() => {
    if (!live) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [live])

  const running = live
  const origin = turn.meta?.started_at ?? startedAt
  const elapsed = running && origin
    ? Math.max(turn.meta?.elapsed_ms ?? 0, now - origin)
    : turn.meta?.elapsed_ms ?? 0
  const steering = turn.process.filter((item) => item.type === 'user')
  const process = turn.process.filter((item) => item.type !== 'user')
  const steps = process.filter((item) => item.type === 'tool')
  // 折叠时也要能看出「现在在干什么」，否则只剩一个计时器像卡住了
  const lastStep = steps[steps.length - 1]
  const progress = executionProgress(process, Boolean(turn.conclusion))
  const status = turn.meta?.status === 'awaiting_approval' ? '等待审批'
    : turn.meta?.status === 'interrupted' || process.some((item) => item.type === 'error') ? '已中断'
    : turn.conclusion ? '已完成' : '执行未完成'

  return (
    <div className="turn" data-turn-id={turn.id} id={`${side ? "side-" : ""}turn-${turn.id}`}>
      {turn.user && (
        <div className="msg user">
          <div className="user-stack">
            {turn.user.references && turn.user.references.length > 0 && (
              <div className="msg-refs">
                {turn.user.references.map((ref, index) => (
                  <span
                    className="msg-ref-chip"
                    key={`${ref.type}-${ref.path}-${index}`}
                    title={ref.path}
                  >
                    <span className="ref-hint">{ref.hint}</span>
                    {ref.name}
                  </span>
                ))}
              </div>
            )}
            <div className="bubble">{turn.user.content}</div>
            {!running && (
              <div className="msg-actions">
                <button onClick={() => copy(turn.user?.content ?? '')} title="复制">
                  <Copy size={11} />
                </button>
                <button
                  onClick={() => {
                    (onEdit ?? setPendingComposer)(turn.user?.content ?? '')
                    showToast('已填入输入框，修改后可直接发送')
                  }}
                  title="编辑后重发"
                >
                  <Pencil size={11} />
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {steering.map((item) => (
        <div className="msg user" key={item.id}>
          <div className="user-stack">
            <div className="bubble"><span className="step-steer-label">执行中补充</span>{item.content}</div>
          </div>
        </div>
      ))}

      {(process.length > 0 || turn.conclusion || turn.meta) && (
        <div className="msg assistant">
          <div className="avatar">文</div>
          <div className="assistant-body">
            {running && (
              <div className="turn-progress" role="status">
                <div className="turn-progress-current">{progress.current}</div>
                {progress.recent && <div className="turn-progress-recent">{progress.recent}</div>}
              </div>
            )}
            {(process.length > 0 || turn.meta) &&
              (running ? (
                <details className="turn-live turn-live-running">
                  <summary>
                    <Loader2 size={12} className="spin" />
                    <span>处理中 · {formatDuration(elapsed)}</span>
                    {steps.length > 0 && (
                      <>
                        <span className="turn-dot">·</span>
                        <span>{steps.length} 步</span>
                      </>
                    )}
                    {lastStep && (
                      <>
                        <span className="turn-dot">·</span>
                        <span className="turn-now" title={lastStep.name}>
                          {lastStep.status === 'running' ? toolProgress(lastStep) : '继续处理中'}
                        </span>
                      </>
                    )}
                    <ChevronRight size={12} className="turn-chev" />
                  </summary>
                  <div className="turn-live-steps">
                    {process.map((item) => (
                      <StepRow key={item.id} item={item} />
                    ))}
                  </div>
                </details>
              ) : (
                <details className="turn-fold">
                  <summary>
                    {status === '已完成' ? <Check size={12} /> : <AlertTriangle size={12} />}
                    <span>{status}</span>
                    {elapsed > 0 && (
                      <>
                        <span className="turn-dot">·</span>
                        <span>{formatDuration(elapsed)}</span>
                      </>
                    )}
                    {steps.length > 0 && (
                      <>
                        <span className="turn-dot">·</span>
                        <span>{steps.length} 步</span>
                      </>
                    )}
                    {turn.meta?.usage && turn.meta.usage.total > 0 && (
                      <>
                        <span className="turn-dot">·</span>
                        <span
                          title={`输入 ${turn.meta.usage.input.toLocaleString()} · 输出 ${turn.meta.usage.output.toLocaleString()}`}
                        >
                          {formatTokens(turn.meta.usage.total)} tokens
                        </span>
                      </>
                    )}
                    <ChevronRight size={12} className="turn-chev" />
                  </summary>
                  <div className="turn-live">
                    {process.map((item) => (
                      <StepRow key={item.id} item={item} />
                    ))}
                  </div>
                </details>
              ))}

            {turn.conclusion && (
              <div className={`content md-content ${live ? 'streaming' : ''}`}>
                <Markdown content={turn.conclusion.content} />
                {turn.conclusion.interrupted && (
                  <div className="turn-interrupted">生成已中断，以上为已生成的内容</div>
                )}
                {!running && (
                  <div className="msg-actions">
                    <button onClick={() => copy(turn.conclusion?.content ?? '')} title="复制">
                      <Copy size={11} />
                    </button>
                    {onBring && isLast && !live && (
                      <button onClick={() => onBring(turn.conclusion?.content ?? '')} title="带入主对话">
                        <CornerUpLeft size={11} /> 带入主对话
                      </button>
                    )}
                    {isLast && !live && turn.user && (
                      <button
                        onClick={() => onRetry ? onRetry() : void retryLastTurn()}
                        disabled={side ? live : streaming}
                        title="重试：把这条消息再发一次，原回答保留"
                      >
                        <RotateCcw size={11} />
                      </button>
                    )}
                  </div>
                )}
              </div>
            )}
            {!running && !turn.conclusion && (
              <div className="turn-interrupted">
                <span>{status === '等待审批'
                  ? '本轮等待写入审批，通过后继续执行。'
                  : '本轮尚未生成最终总结，请继续执行或重试。'}</span>
                {isLast && !side && !approval && (
                  <button className="link-btn" disabled={streaming} onClick={() => void regenerate()}>重新生成</button>
                )}
              </div>
            )}
          </div>
        </div>
      )}

    </div>
  )
}

/** 等待模型首字时的占位，带秒数，避免用户以为卡死。 */
export function PendingBubble({ startedAt }: { startedAt: number | null }): React.JSX.Element {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])
  const seconds = startedAt ? Math.max(0, Math.floor((now - startedAt) / 1000)) : 0
  return (
    <div className="msg assistant pending-msg">
      <div className="avatar">文</div>
      <div className="assistant-body">
        <div className="turn-live-head">
          <Loader2 size={12} className="spin" />
          正在思考
          {seconds > 0 && <span className="pending-seconds"> · {seconds} 秒</span>}
        </div>
      </div>
    </div>
  )
}

function StepRow({ item }: { item: TimelineItem }): React.JSX.Element | null {
  if (item.type === 'tool') {
    return (
      <details className="step-tool">
        <summary>
          <Wrench size={11} />
          <span className="step-name" title={item.name}>{toolProgress(item)}</span>
          <span className={`status ${item.status === 'running' ? 'running' : ''}`}>
            {item.status === 'running'
              ? '执行中'
              : item.status === 'cancelled'
                ? '已停止'
                : '完成'}
          </span>
        </summary>
        <div className="tool-body">
          {item.input}
          {item.output ? `\n\n${item.output}` : ''}
        </div>
      </details>
    )
  }
  if (item.type === 'assistant') {
    return <div className="step-text">{item.content}</div>
  }
  if (item.type === 'error') {
    return (
      <div className="step-error">
        <AlertTriangle size={12} />
        <span>{item.content}</span>
      </div>
    )
  }
  return null
}

function sameTurn(a: TurnView, b: TurnView): boolean {
  // 未变化的轮次在 groupTurns 里沿用同一批对象引用，逐项比引用就够
  return (
    a.id === b.id &&
    a.user === b.user &&
    a.conclusion === b.conclusion &&
    a.meta === b.meta &&
    a.process.length === b.process.length &&
    a.process.every((item, index) => item === b.process[index])
  )
}

export const ConversationTurn = memo(
  TurnBlock,
  (prev, next) =>
    sameTurn(prev.turn, next.turn) &&
    prev.live === next.live &&
    prev.isLast === next.isLast &&
    prev.startedAt === next.startedAt &&
    prev.side === next.side &&
    prev.onEdit === next.onEdit &&
    prev.onRetry === next.onRetry &&
    prev.onBring === next.onBring
)

function formatDuration(ms: number): string {
  if (!ms || ms < 1000) return '1 秒内'
  const seconds = Math.round(ms / 1000)
  if (seconds < 60) return `${seconds} 秒`
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return rest ? `${minutes} 分 ${rest} 秒` : `${minutes} 分`
}
