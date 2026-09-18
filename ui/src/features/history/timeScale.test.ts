import { describe, expect, test } from 'bun:test'
import { closedDaysBetween, closedRangeLabel, createTimeScale } from './timeScale'

describe('performance time scale', () => {
  test('natural scale is identity', () => {
    const scale = createTimeScale('natural', [10, 20])
    expect(scale.project(15)).toBe(15)
    expect(scale.invert(15)).toBe(15)
  })

  test('observations are equidistant and mapping is reversible', () => {
    const scale = createTimeScale('observations', [100, 100, 200, 500])
    expect(scale.project(200) - scale.project(100)).toBe(86_400_000)
    expect(scale.project(500) - scale.project(200)).toBe(86_400_000)
    for (const time of [50, 100, 150, 200, 350, 500, 650]) expect(scale.invert(scale.project(time))).toBeCloseTo(time)
  })

  test('only complete authoritative closed days are counted', () => {
    const start = new Date('2026-09-18T15:00:00+08:00').getTime()
    const end = new Date('2026-09-21T09:00:00+08:00').getTime()
    expect(closedDaysBetween(start, end, [{ start: '2026-09-19', end: '2026-09-20' }])).toBe(2)
    expect(closedDaysBetween(start, end, [{ start: '2026-09-18', end: '2026-09-20' }])).toBe(2)
  })

  test('closed range labels degrade without symbolic slashes', () => {
    expect(closedRangeLabel(90, 7, 52, 22)).toBe('休市 7 日')
    expect(closedRangeLabel(40, 7, 52, 22)).toBe('休市')
    expect(closedRangeLabel(20, 7, 52, 22)).toBe('')
  })
})
