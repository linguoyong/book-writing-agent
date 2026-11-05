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

/**
 * 相对时间：刚刚 / N 分钟前 / N 小时前 / 昨天 / N 天前 / M月D日 / YYYY年M月D日
 *
 * 「几天前」按自然日算，不是按 24 小时整除：昨晚 23:50 和今天 00:10 差 20 分钟，
 * 应该是「20分钟前」；而前天 23:00 到现在 25 小时，应该算「2天前」。
 */
export function formatRelativeTime(
  value: string | number | Date,
  now: number = Date.now()
): string {
  const time =
    value instanceof Date
      ? value.getTime()
      : typeof value === 'number'
        ? value
        : new Date(value).getTime()
  if (!Number.isFinite(time)) return ''

  const diff = now - time
  // 时钟偏差导致的「未来时间」也按刚刚处理，不显示负数
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}小时前`

  const startOfToday = new Date(now)
  startOfToday.setHours(0, 0, 0, 0)
  const startOfThen = new Date(time)
  startOfThen.setHours(0, 0, 0, 0)
  const days = Math.round((startOfToday.getTime() - startOfThen.getTime()) / 86_400_000)

  if (days <= 1) return '昨天'
  if (days < 7) return `${days}天前`

  const date = new Date(time)
  const monthDay = `${date.getMonth() + 1}月${date.getDate()}日`
  return date.getFullYear() === new Date(now).getFullYear()
    ? monthDay
    : `${date.getFullYear()}年${monthDay}`
}
