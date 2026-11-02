import { useEffect, useMemo, useState } from 'react'
import { BarChart3, Coins, Database, Loader2, RefreshCw, Wallet } from 'lucide-react'
import { api } from '../api'
import { formatCost, formatTokens } from '../format'
import { useAppStore } from '../store'
import type { ModelPrice, UsageSummary } from '../types'

const RANGES = [7, 14, 30, 90]
const KIND_LABEL: Record<string, string> = {
  chat: '对话',
  extract: '逐章抽取',
  rewrite: '选中改写'
}

const EMPTY_PRICE: ModelPrice = { input: 0, output: 0, cache_read: 0 }

export default function UsagePage(): React.JSX.Element {
  const project = useAppStore((state) => state.activeProject)
  const showToast = useAppStore((state) => state.showToast)

  const [days, setDays] = useState(14)
  const [summary, setSummary] = useState<UsageSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [prices, setPrices] = useState<Record<string, ModelPrice>>({})
  const [saving, setSaving] = useState(false)

  const load = async (range = days): Promise<void> => {
    if (!project) return
    setLoading(true)
    try {
      const result = await api.projectUsage(project.id, range)
      setSummary(result)
      setPrices((current) => {
        const next: Record<string, ModelPrice> = {}
        const names = new Set([
          ...result.by_model.map((row) => row.model).filter((name) => name !== '未回报'),
          ...Object.keys(result.pricing)
        ])
        names.forEach((name) => {
          next[name] = current[name] ?? result.pricing[name] ?? { ...EMPTY_PRICE }
        })
        return next
      })
    } catch (error) {
      showToast((error as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load(days)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.id, days])

  const maxTotal = useMemo(
    () => Math.max(1, ...(summary?.series ?? []).map((item) => item.total)),
    [summary]
  )

  const savePrices = async (): Promise<void> => {
    setSaving(true)
    try {
      const payload: Record<string, ModelPrice> = {}
      Object.entries(prices).forEach(([name, value]) => {
        if (value.input || value.output || value.cache_read) payload[name] = value
      })
      await api.saveUsagePricing(payload)
      showToast('单价已保存')
      await load(days)
    } catch (error) {
      showToast((error as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const projectName = project?.meta?.title || project?.name || ''
  const totals = summary?.totals
  const cost = summary?.cost

  return (
    <div className="page">
      <div className="page-header">
        <div className="page-title-block">
          <h1>用量统计</h1>
          <p>{projectName} · 对话、逐章抽取与选中改写的模型调用都记在这里</p>
        </div>
        <div className="page-actions">
          <div className="usage-range">
            {RANGES.map((range) => (
              <button
                key={range}
                className={`usage-range-btn ${range === days ? 'active' : ''}`}
                onClick={() => setDays(range)}
              >
                {range} 天
              </button>
            ))}
          </div>
          <button className="ghost-btn" onClick={() => void load(days)} disabled={loading}>
            {loading ? <Loader2 size={13} className="spin" /> : <RefreshCw size={13} />}
            刷新
          </button>
        </div>
      </div>

      <div className="page-scroll">
        {loading && !summary && <div className="panel-empty">统计中…</div>}

        {summary && (
          <>
            {summary.recorded === 0 && (
              <div className="kb-notice">
                还没有用量记录。开始一次对话（或跑一次抽取）后，每次模型调用都会在这里记账；
                旧版本产生的消息没有记录过 token，无法回溯补算。
              </div>
            )}

            <div className="usage-cards">
              <div className="usage-card">
                <div className="usage-card-head">
                  <BarChart3 size={14} />
                  近 {summary.days} 天
                </div>
                <div className="usage-card-value">{formatTokens(totals?.total ?? 0)}</div>
                <div className="usage-card-sub">
                  输入 {formatTokens(totals?.input ?? 0)} · 输出{' '}
                  {formatTokens(totals?.output ?? 0)} · 调用 {totals?.calls ?? 0} 次
                </div>
              </div>
              <div className="usage-card">
                <div className="usage-card-head">
                  <Coins size={14} />
                  今天
                </div>
                <div className="usage-card-value">{formatTokens(summary.today.total)}</div>
                <div className="usage-card-sub">
                  输入 {formatTokens(summary.today.input)} · 输出{' '}
                  {formatTokens(summary.today.output)}
                </div>
              </div>
              <div className="usage-card">
                <div className="usage-card-head">
                  <Database size={14} />
                  缓存命中
                </div>
                <div className="usage-card-value">{formatTokens(totals?.cache_read ?? 0)}</div>
                <div className="usage-card-sub">
                  {totals?.input
                    ? `占输入 ${((totals.cache_read / totals.input) * 100).toFixed(0)}%`
                    : '上游未回报缓存用量'}
                </div>
              </div>
              <div className="usage-card">
                <div className="usage-card-head">
                  <Wallet size={14} />
                  估算成本
                </div>
                <div className="usage-card-value">
                  {cost?.has_pricing ? formatCost(cost.total) : '—'}
                </div>
                <div className="usage-card-sub">
                  {cost?.has_pricing
                    ? `今天 ${formatCost(cost.today)} · 按下方单价折算`
                    : '填好模型单价后折算'}
                </div>
              </div>
            </div>

            <section className="usage-panel">
              <div className="usage-panel-head">
                <span>每日用量</span>
                <span className="usage-legend">
                  <i className="legend-in" /> 输入
                  <i className="legend-out" /> 输出
                </span>
              </div>
              <div className="usage-chart">
                {summary.series.map((item, index) => {
                  const percent = (item.total / maxTotal) * 100
                  const showLabel =
                    summary.series.length <= 14 ||
                    index === 0 ||
                    index === summary.series.length - 1 ||
                    index % Math.ceil(summary.series.length / 7) === 0
                  return (
                    <div
                      className="usage-col"
                      key={item.date}
                      title={`${item.date} · 输入 ${item.input.toLocaleString()} / 输出 ${item.output.toLocaleString()}${
                        item.cost ? ` · ${formatCost(item.cost)}` : ''
                      }`}
                    >
                      <div className="usage-bar-wrap">
                        <div className="usage-bar" style={{ height: `${percent}%` }}>
                          {item.output > 0 && (
                            <div
                              className="usage-seg out"
                              style={{ flexGrow: item.output }}
                            />
                          )}
                          {item.input > 0 && (
                            <div className="usage-seg in" style={{ flexGrow: item.input }} />
                          )}
                        </div>
                      </div>
                      <div className="usage-col-label">
                        {showLabel ? item.date.slice(5) : ''}
                      </div>
                    </div>
                  )
                })}
              </div>
            </section>

            <div className="usage-grid">
              <section className="usage-panel">
                <div className="usage-panel-head">
                  <span>按模型</span>
                  <span className="usage-dim">{summary.by_model.length} 个</span>
                </div>
                <table className="usage-table">
                  <thead>
                    <tr>
                      <th>模型</th>
                      <th className="num">输入</th>
                      <th className="num">输出</th>
                      <th className="num">成本</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.by_model.map((row) => (
                      <tr key={row.model}>
                        <td className="ellipsis" title={row.model}>
                          {row.model}
                        </td>
                        <td className="num">{formatTokens(row.input)}</td>
                        <td className="num">{formatTokens(row.output)}</td>
                        <td className="num">{row.cost ? formatCost(row.cost) : '—'}</td>
                      </tr>
                    ))}
                    {!summary.by_model.length && (
                      <tr>
                        <td colSpan={4} className="usage-empty">
                          暂无数据
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </section>

              <section className="usage-panel">
                <div className="usage-panel-head">
                  <span>按用途</span>
                </div>
                <div className="usage-kinds">
                  {summary.by_kind.map((row) => (
                    <div className="usage-kind" key={row.kind}>
                      <span className="usage-kind-name">{KIND_LABEL[row.kind] || row.kind}</span>
                      <span className="usage-kind-value">{formatTokens(row.total)}</span>
                      <span className="usage-kind-sub">
                        {row.turns} 次 · 输入 {formatTokens(row.input)} / 输出{' '}
                        {formatTokens(row.output)}
                      </span>
                    </div>
                  ))}
                  {!summary.by_kind.length && <div className="panel-empty">暂无数据</div>}
                </div>
              </section>
            </div>

            <section className="usage-panel">
              <div className="usage-panel-head">
                <span>按会话</span>
                <span className="usage-dim">最近 {summary.days} 天，前 20 个</span>
              </div>
              <table className="usage-table">
                <thead>
                  <tr>
                    <th>会话</th>
                    <th className="num">轮次</th>
                    <th className="num">输入</th>
                    <th className="num">输出</th>
                    <th className="num">成本</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.by_session.map((row) => (
                    <tr key={row.session_id}>
                      <td className="ellipsis" title={row.title}>
                        {row.title}
                      </td>
                      <td className="num">{row.turns}</td>
                      <td className="num">{formatTokens(row.input)}</td>
                      <td className="num">{formatTokens(row.output)}</td>
                      <td className="num">{row.cost ? formatCost(row.cost) : '—'}</td>
                    </tr>
                  ))}
                  {!summary.by_session.length && (
                    <tr>
                      <td colSpan={5} className="usage-empty">
                        还没有对话用量
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </section>

            <section className="usage-panel">
              <div className="usage-panel-head">
                <span>模型单价</span>
                <button className="small-btn primary" onClick={() => void savePrices()} disabled={saving}>
                  {saving ? <Loader2 size={12} className="spin" /> : null}
                  保存单价
                </button>
              </div>
              <p className="usage-hint">
                单位：元 / 百万 token，按你自己买的价填；留 0 表示不折算成本。
                缓存命中价一般比输入价低，没有单独计价就留 0，会按输入价算。
              </p>
              <div className="usage-prices">
                {Object.keys(prices).map((name) => (
                  <div className="usage-price-row" key={name}>
                    <span className="usage-price-name" title={name}>
                      {name}
                    </span>
                    <label>
                      输入
                      <input
                        type="number"
                        min={0}
                        step="0.1"
                        value={prices[name]?.input ?? 0}
                        onChange={(event) =>
                          setPrices((current) => ({
                            ...current,
                            [name]: {
                              ...(current[name] ?? EMPTY_PRICE),
                              input: Number(event.target.value) || 0
                            }
                          }))
                        }
                      />
                    </label>
                    <label>
                      输出
                      <input
                        type="number"
                        min={0}
                        step="0.1"
                        value={prices[name]?.output ?? 0}
                        onChange={(event) =>
                          setPrices((current) => ({
                            ...current,
                            [name]: {
                              ...(current[name] ?? EMPTY_PRICE),
                              output: Number(event.target.value) || 0
                            }
                          }))
                        }
                      />
                    </label>
                    <label>
                      缓存
                      <input
                        type="number"
                        min={0}
                        step="0.1"
                        value={prices[name]?.cache_read ?? 0}
                        onChange={(event) =>
                          setPrices((current) => ({
                            ...current,
                            [name]: {
                              ...(current[name] ?? EMPTY_PRICE),
                              cache_read: Number(event.target.value) || 0
                            }
                          }))
                        }
                      />
                    </label>
                  </div>
                ))}
                {!Object.keys(prices).length && (
                  <div className="panel-empty">先产生一次调用，这里会列出用过的模型名</div>
                )}
              </div>
            </section>
          </>
        )}
      </div>
    </div>
  )
}
