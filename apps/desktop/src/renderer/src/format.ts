/** token 与金额的显示格式：用量页与轮次摘要共用。 */

export function formatTokens(value: number): string {
  const n = Math.max(0, Math.round(value || 0))
  if (n < 1000) return `${n}`
  if (n < 10_000) return `${(n / 1000).toFixed(1)}k`
  if (n < 1_000_000) return `${Math.round(n / 1000)}k`
  return `${(n / 1_000_000).toFixed(2)}M`
}

export function formatCost(value: number): string {
  const n = Math.max(0, Number(value) || 0)
  if (n === 0) return '¥0'
  if (n < 0.01) return `¥${n.toFixed(4)}`
  if (n < 10) return `¥${n.toFixed(3)}`
  return `¥${n.toFixed(2)}`
}
