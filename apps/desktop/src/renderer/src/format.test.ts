import { describe, expect, it } from 'vitest'
import { formatCost, formatRelativeTime, formatTokens } from './format'

describe('formatTokens', () => {
  it('小数量按原样显示', () => {
    expect(formatTokens(0)).toBe('0')
    expect(formatTokens(999)).toBe('999')
  })

  it('千级与万级分别保留一位小数与取整', () => {
    expect(formatTokens(1500)).toBe('1.5k')
    expect(formatTokens(9_400)).toBe('9.4k')
    expect(formatTokens(25_600)).toBe('26k')
  })

  it('百万级保留两位小数', () => {
    expect(formatTokens(1_234_567)).toBe('1.23M')
  })

  it('负数与非数字退回 0', () => {
    expect(formatTokens(-20)).toBe('0')
    expect(formatTokens(Number.NaN)).toBe('0')
  })
})

describe('formatCost', () => {
  it('零与小额按精度区分', () => {
    expect(formatCost(0)).toBe('¥0')
    expect(formatCost(0.0042)).toBe('¥0.0042')
    expect(formatCost(1.23456)).toBe('¥1.235')
  })

  it('十元以上只留两位', () => {
    expect(formatCost(12.345)).toBe('¥12.35')
  })
})

describe('formatRelativeTime', () => {
  const now = new Date(2026, 10, 5, 10, 0, 0).getTime() // 2026-11-05 10:00 本地时间
  const ago = (ms: number): number => now - ms
  const MIN = 60_000
  const HOUR = 60 * MIN
  const DAY = 24 * HOUR

  it('一分钟内算刚刚', () => {
    expect(formatRelativeTime(ago(30_000), now)).toBe('刚刚')
    expect(formatRelativeTime(now, now)).toBe('刚刚')
  })

  it('分钟与小时', () => {
    expect(formatRelativeTime(ago(5 * MIN), now)).toBe('5分钟前')
    expect(formatRelativeTime(ago(59 * MIN), now)).toBe('59分钟前')
    expect(formatRelativeTime(ago(3 * HOUR), now)).toBe('3小时前')
  })

  it('跨天但不足 24 小时仍按小时显示', () => {
    // 今天 10:00 看昨晚 23:00：差 11 小时
    expect(formatRelativeTime(new Date(2026, 10, 4, 23, 0, 0).getTime(), now)).toBe('11小时前')
  })

  it('昨天与几天前按自然日算', () => {
    expect(formatRelativeTime(new Date(2026, 10, 4, 9, 0, 0).getTime(), now)).toBe('昨天')
    expect(formatRelativeTime(new Date(2026, 10, 2, 9, 0, 0).getTime(), now)).toBe('3天前')
    expect(formatRelativeTime(new Date(2026, 9, 31, 9, 0, 0).getTime(), now)).toBe('5天前')
  })

  it('超过一周显示日期，跨年带年份', () => {
    expect(formatRelativeTime(new Date(2026, 9, 20, 9, 0, 0).getTime(), now)).toBe('10月20日')
    expect(formatRelativeTime(new Date(2025, 11, 31, 9, 0, 0).getTime(), now)).toBe(
      '2025年12月31日'
    )
  })

  it('未来时间与非法值', () => {
    expect(formatRelativeTime(now + 5 * MIN, now)).toBe('刚刚')
    expect(formatRelativeTime('不是时间', now)).toBe('')
  })
})
