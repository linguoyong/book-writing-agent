import { useEffect, useMemo, useState } from 'react'
import { Loader2, RefreshCw, Share2 } from 'lucide-react'
import { api } from '../api'
import { useAppStore } from '../store'
import { KB_LABELS } from '../store'
import type { Entity, GraphData, GraphEdge, GraphNode, KbKind } from '../types'

const MAX_NODES = 300
const WIDTH = 880
const HEIGHT = 560

const KIND_COLOR: Record<string, string> = {
  characters: '#3c8c4e',
  factions: '#b45309',
  locations: '#3a66ac',
  items: '#7c5cbf'
}

interface Point {
  x: number
  y: number
  vx: number
  vy: number
}

/** 简易力导向布局：斥力 + 边弹簧 + 向心。节点数有上限，迭代几百次足够稳。 */
function computePositions(
  nodes: GraphNode[],
  edges: GraphEdge[],
  seedNo: number
): Map<string, Point> {
  const points = new Map<string, Point>()
  const count = Math.max(1, nodes.length)
  let seed = seedNo * 7919 + 104729
  const random = (): number => {
    seed = (seed * 1103515245 + 12345) % 2147483648
    return seed / 2147483648
  }

  nodes.forEach((node, index) => {
    const angle = (index / count) * Math.PI * 2
    const radius = Math.min(WIDTH, HEIGHT) * 0.33
    points.set(node.id, {
      x: WIDTH / 2 + Math.cos(angle) * radius + (random() - 0.5) * 24,
      y: HEIGHT / 2 + Math.sin(angle) * radius + (random() - 0.5) * 24,
      vx: 0,
      vy: 0
    })
  })

  const list = nodes.map((node) => points.get(node.id) as Point)
  const indexOf = new Map(nodes.map((node, index) => [node.id, index]))

  for (let iter = 0; iter < 320; iter += 1) {
    const cool = 1 - iter / 320
    for (let i = 0; i < list.length; i += 1) {
      for (let j = i + 1; j < list.length; j += 1) {
        let dx = list[i].x - list[j].x
        let dy = list[i].y - list[j].y
        let dist2 = dx * dx + dy * dy
        if (dist2 < 1) {
          dx = random() - 0.5
          dy = random() - 0.5
          dist2 = dx * dx + dy * dy + 1
        }
        const dist = Math.sqrt(dist2)
        const force = 2200 / dist2
        const fx = (dx / dist) * force
        const fy = (dy / dist) * force
        list[i].vx += fx
        list[i].vy += fy
        list[j].vx -= fx
        list[j].vy -= fy
      }
    }

    for (const edge of edges) {
      const a = list[indexOf.get(edge.source) ?? -1]
      const b = list[indexOf.get(edge.target) ?? -1]
      if (!a || !b) continue
      const dx = b.x - a.x
      const dy = b.y - a.y
      const dist = Math.sqrt(dx * dx + dy * dy) || 1
      const force = (dist - 120) * 0.02
      const fx = (dx / dist) * force
      const fy = (dy / dist) * force
      a.vx += fx
      a.vy += fy
      b.vx -= fx
      b.vy -= fy
    }

    for (const point of list) {
      point.vx += (WIDTH / 2 - point.x) * 0.004
      point.vy += (HEIGHT / 2 - point.y) * 0.006
      point.vx *= 0.85
      point.vy *= 0.85
      point.x = Math.min(WIDTH - 46, Math.max(46, point.x + point.vx * cool))
      point.y = Math.min(HEIGHT - 34, Math.max(30, point.y + point.vy * cool))
    }
  }

  // 力导向常常缩成中间一小团：最后按包围盒等比放大到画布 82%，
  // 小图（十来张卡）也能把版面撑开。
  if (list.length > 1) {
    let minX = Infinity
    let maxX = -Infinity
    let minY = Infinity
    let maxY = -Infinity
    list.forEach((point) => {
      minX = Math.min(minX, point.x)
      maxX = Math.max(maxX, point.x)
      minY = Math.min(minY, point.y)
      maxY = Math.max(maxY, point.y)
    })
    const spanX = Math.max(1, maxX - minX)
    const spanY = Math.max(1, maxY - minY)
    const scale = Math.min((WIDTH * 0.82) / spanX, (HEIGHT * 0.78) / spanY, 3)
    const centerX = (minX + maxX) / 2
    const centerY = (minY + maxY) / 2
    list.forEach((point) => {
      point.x = WIDTH / 2 + (point.x - centerX) * scale
      point.y = HEIGHT / 2 + (point.y - centerY) * scale
    })
  }
  return points
}

export default function KnowledgeGraph({
  onOpenKind
}: {
  onOpenKind: (kind: KbKind) => void
}): React.JSX.Element {
  const project = useAppStore((state) => state.activeProject)
  const showToast = useAppStore((state) => state.showToast)

  const [data, setData] = useState<GraphData | null>(null)
  const [loading, setLoading] = useState(true)
  const [mentions, setMentions] = useState(true)
  const [seed, setSeed] = useState(1)
  const [active, setActive] = useState<string | null>(null)
  const [detail, setDetail] = useState<Entity | null>(null)

  const load = async (withMentions = mentions): Promise<void> => {
    if (!project) return
    setLoading(true)
    try {
      setData(await api.projectGraph(project.id, withMentions))
    } catch (error) {
      showToast((error as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load(mentions)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.id, mentions])

  // 力导向是 O(n²)：几百个提及节点就能把主线程卡住几秒。
  // 超过上限时按连接度保留最重要的节点，其余不参与布局与渲染。
  const view = useMemo(() => {
    if (!data) return null
    if (data.nodes.length <= MAX_NODES) {
      return { nodes: data.nodes, edges: data.edges, trimmed: 0 }
    }
    const degree = new Map<string, number>()
    for (const edge of data.edges) {
      degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1)
      degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1)
    }
    const kept = [...data.nodes]
      .sort((a, b) => (degree.get(b.id) ?? 0) - (degree.get(a.id) ?? 0))
      .slice(0, MAX_NODES)
    const ids = new Set(kept.map((node) => node.id))
    return {
      nodes: kept,
      edges: data.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target)),
      trimmed: data.nodes.length - kept.length
    }
  }, [data])

  const positions = useMemo(
    () => (view ? computePositions(view.nodes, view.edges, seed) : new Map()),
    [view, seed]
  )

  const nodeById = useMemo(
    () => new Map((view?.nodes ?? []).map((node) => [node.id, node])),
    [view]
  )

  const neighbours = useMemo(() => {
    if (!view || !active) return new Set<string>()
    const set = new Set<string>([active])
    view.edges.forEach((edge) => {
      if (edge.source === active) set.add(edge.target)
      if (edge.target === active) set.add(edge.source)
    })
    return set
  }, [data, active])

  useEffect(() => {
    if (!project || !active) {
      setDetail(null)
      return
    }
    const node = nodeById.get(active)
    if (!node) return
    void api
      .entity(project.id, node.kind, node.entity_id)
      .then(setDetail)
      .catch(() => setDetail(null))
  }, [project?.id, active, nodeById])

  const selected = active ? nodeById.get(active) : null
  const linked = useMemo(() => {
    if (!view || !active) return []
    const grouped = new Map<
      string,
      { node: GraphNode; labels: string[]; hasRelation: boolean }
    >()
    view.edges
      .filter((edge) => edge.source === active || edge.target === active)
      .forEach((edge) => {
        const other = nodeById.get(edge.source === active ? edge.target : edge.source)
        if (!other) return
        const entry = grouped.get(other.id) ?? {
          node: other,
          labels: [],
          hasRelation: false
        }
        if (!entry.labels.includes(edge.label)) entry.labels.push(edge.label)
        if (edge.type === 'relation') entry.hasRelation = true
        grouped.set(other.id, entry)
      })
    return [...grouped.values()].sort(
      (a, b) => Number(b.hasRelation) - Number(a.hasRelation)
    )
  }, [view, active, nodeById])

  const stats = data?.stats

  return (
    <div className="graph-wrap">
      <div className="graph-toolbar">
        <div className="graph-stats">
          {stats ? (
            <>
              <span>{stats.nodes} 个节点</span>
              {view && view.trimmed > 0 && (
                <span className="graph-warn">（按连接度显示前 {MAX_NODES} 个）</span>
              )}
              <span className="graph-dot">·</span>
              <span>{stats.relations} 条关系</span>
              <span className="graph-dot">·</span>
              <span>{stats.mentions} 条提及</span>
              {stats.unresolved > 0 && (
                <>
                  <span className="graph-dot">·</span>
                  <span className="graph-warn">{stats.unresolved} 个目标没匹配上</span>
                </>
              )}
            </>
          ) : (
            '读取中…'
          )}
        </div>
        <div className="graph-actions">
          <label className="graph-toggle">
            <input
              type="checkbox"
              checked={mentions}
              onChange={(event) => setMentions(event.target.checked)}
            />
            自动「提及」边
          </label>
          <button className="ghost-btn" onClick={() => setSeed((value) => value + 1)}>
            <RefreshCw size={12} />
            重新排布
          </button>
        </div>
      </div>

      <div className="graph-body">
        <div className="graph-canvas">
          {loading && (
            <div className="graph-loading">
              <Loader2 size={16} className="spin" />
              读取关系…
            </div>
          )}
          {!loading && view && view.nodes.length === 0 && (
            <div className="empty-block">
              <Share2 size={20} />
              <div>还没有可画的条目</div>
              <p>先在「角色 / 势力 / 地点 / 物品」里建卡，或在卡片里写 relations。</p>
            </div>
          )}
          {!loading && view && view.nodes.length > 0 && (
            <svg
              className="graph-svg"
              viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
              onClick={() => setActive(null)}
            >
              <g>
                {view.edges.map((edge, index) => {
                  const from = positions.get(edge.source)
                  const to = positions.get(edge.target)
                  if (!from || !to) return null
                  const dim =
                    Boolean(active) && edge.source !== active && edge.target !== active
                  return (
                    <line
                      key={`${edge.source}-${edge.target}-${edge.label}-${index}`}
                      x1={from.x}
                      y1={from.y}
                      x2={to.x}
                      y2={to.y}
                      className={`graph-edge ${edge.type}${dim ? ' dim' : ''}`}
                      strokeWidth={edge.type === 'relation' ? 1.6 : 1}
                      strokeDasharray={edge.type === 'mention' ? '3 4' : undefined}
                    />
                  )
                })}
              </g>
              <g>
                {view.nodes.map((node) => {
                  const point = positions.get(node.id)
                  if (!point) return null
                  const radius = 7 + Math.min(node.degree, 8) * 1.7
                  const dim = Boolean(active) && !neighbours.has(node.id)
                  return (
                    <g
                      key={node.id}
                      className={`graph-node${dim ? ' dim' : ''}${
                        node.id === active ? ' active' : ''
                      }`}
                      onClick={(event) => {
                        event.stopPropagation()
                        setActive(node.id)
                      }}
                    >
                      <circle
                        cx={point.x}
                        cy={point.y}
                        r={radius}
                        fill={KIND_COLOR[node.kind] ?? '#6f8173'}
                      />
                      <text x={point.x} y={point.y + radius + 15} textAnchor="middle">
                        {node.name}
                      </text>
                    </g>
                  )
                })}
              </g>
            </svg>
          )}
          <div className="graph-legend">
            {Object.entries(KB_LABELS)
              .filter(([kind]) => KIND_COLOR[kind])
              .map(([kind, label]) => (
                <span key={kind}>
                  <i style={{ background: KIND_COLOR[kind] }} />
                  {label}
                </span>
              ))}
            <span>
              <i className="line-solid" />
              显式关系
            </span>
            <span>
              <i className="line-dash" />
              正文提及
            </span>
          </div>
        </div>

        <aside className="graph-side">
          {!selected && (
            <div className="graph-hint">
              点节点看它和谁有关系。虚线是「正文里提到过」自动推出来的，
              实线来自卡片里的 <code>relations</code>。
            </div>
          )}
          {selected && (
            <>
              <div className="graph-side-head">
                <span
                  className="graph-kind"
                  style={{ background: KIND_COLOR[selected.kind] ?? '#6f8173' }}
                >
                  {KB_LABELS[selected.kind] ?? selected.kind}
                </span>
                <h3>{selected.name}</h3>
                {selected.aliases.length > 0 && (
                  <p className="graph-aliases">别名：{selected.aliases.join(' / ')}</p>
                )}
              </div>
              <div className="graph-links">
                {linked.map((item) => (
                  <button
                    key={item.node.id}
                    className="graph-link"
                    onClick={() => setActive(item.node.id)}
                  >
                    <span
                      className={`graph-link-type ${item.hasRelation ? 'relation' : 'mention'}`}
                    >
                      {item.labels.join(' · ')}
                    </span>
                    <span className="graph-link-name">{item.node.name}</span>
                  </button>
                ))}
                {!linked.length && <div className="graph-empty">这个条目还没有连线</div>}
              </div>
              {detail && (
                <p className="graph-body-text">
                  {detail.body.replace(/^#.*$/gm, '').trim().slice(0, 220) || '（无正文）'}
                </p>
              )}
              <button className="ghost-btn" onClick={() => onOpenKind(selected.kind)}>
                在知识库里查看
              </button>
            </>
          )}
        </aside>
      </div>
    </div>
  )
}
