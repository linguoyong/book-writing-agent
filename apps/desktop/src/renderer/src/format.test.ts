import { describe, expect, it } from 'vitest'
import { formatCost, formatTokens } from './format'

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
