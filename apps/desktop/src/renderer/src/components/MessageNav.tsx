import { useEffect, useMemo, useRef, useState } from 'react'

export interface NavPoint {
  id: string
  label: string
}

interface Props {
  points: NavPoint[]
  scrollRef: React.RefObject<HTMLDivElement | null>
  /** 目标轮次可能被折叠起来了：交给调用方「先展开再滚」。 */
  onJump?: (id: string) => void
}

const MAX_TICKS = 32

/** 长会话的轮次刻度：悬停看首句，点击跳转。太少轮次时不渲染。 */
export default function MessageNav({
  points,
  scrollRef,
  onJump
}: Props): React.JSX.Element | null {
  const [active, setActive] = useState(-1)
  const [hover, setHover] = useState(-1)
  const raf = useRef(0)

  const sampled = useMemo(() => {
    if (points.length <= MAX_TICKS) return points.map((point, index) => ({ point, index }))
    const step = points.length / MAX_TICKS
    const picks: { point: NavPoint; index: number }[] = []
    for (let i = 0; i < MAX_TICKS; i += 1) {
      const index = Math.min(points.length - 1, Math.round(i * step))
      picks.push({ point: points[index], index })
    }
    return picks
  }, [points])

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const measure = (): void => {
      raf.current = 0
      const line = el.getBoundingClientRect().top + 48
      let current = -1
      // 只量抽样的 32 个刻度：2000 轮会话里逐个 getBoundingClientRect
      // 是滚动时最大的开销，刻度本身也不需要精确到轮。
      for (const { point, index } of sampled) {
        const node = document.getElementById(`turn-${point.id}`)
        if (!node) continue
        if (node.getBoundingClientRect().top <= line) current = index
        else break
      }
      setActive(current)
    }
    const onScroll = (): void => {
      if (raf.current) return
      raf.current = requestAnimationFrame(measure)
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    measure()
    return () => {
      el.removeEventListener('scroll', onScroll)
      if (raf.current) cancelAnimationFrame(raf.current)
    }
  }, [sampled, scrollRef])

  if (points.length < 4) return null

  const jump = (id: string): void => {
    if (onJump) {
      onJump(id)
      return
    }
    document.getElementById(`turn-${id}`)?.scrollIntoView({ block: 'start', behavior: 'smooth' })
  }

  return (
    <div className="chat-nav" aria-label="消息导航">
      {sampled.map(({ point, index }) => (
        <button
          key={point.id}
          className={`chat-nav-tick ${index === active ? 'active' : ''}`}
          onMouseEnter={() => setHover(index)}
          onMouseLeave={() => setHover(-1)}
          onClick={() => jump(point.id)}
          title={point.label}
        >
          <span className="chat-nav-bar" />
          {hover === index && <span className="chat-nav-tip">{point.label}</span>}
        </button>
      ))}
    </div>
  )
}
