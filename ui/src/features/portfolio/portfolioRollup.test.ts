import { describe, expect, it } from 'bun:test'
import { portfolioRollup, PORTFOLIO_ROLLUP_ICON, PORTFOLIO_ROLLUP_TEXT_CLASS } from './portfolioRollup'
import { portfolioTargetSummary, type PortfolioTargetState } from './portfolioCardSummary'

function ready(stale = false): PortfolioTargetState {
  return {
    kind: 'ready',
    calculatedAt: '2026-08-27T09:03:26',
    stale,
    summary: portfolioTargetSummary({
      weights: { a: 0.5 },
      calculated_at: '2026-08-27T09:03:26',
      source: 'manual',
      execution_id: null,
      context_account_id: 1,
    }),
  }
}

describe('portfolioRollup', () => {
  it('总数为 0（含加载中）退回纯标题，不下判词', () => {
    expect(portfolioRollup({ total: 0, targetStates: [], unboundCount: null, targetsReady: false })).toEqual({
      key: 'aligned',
      text: '组合',
    })
  })

  it('快照未定前只报数量，弱中性，不报「全部到位」', () => {
    const rollup = portfolioRollup({ total: 2, targetStates: [ready()], unboundCount: 0, targetsReady: false })
    expect(rollup).toEqual({ key: 'todo', text: '2 个组合' })
  })

  it('目标更新失败优先，琥珀偏离档', () => {
    const states: PortfolioTargetState[] = [
      ready(true),
      { kind: 'unavailable' },
      ready(),
    ]
    const rollup = portfolioRollup({ total: 3, targetStates: states, unboundCount: 0, targetsReady: true })
    expect(rollup).toEqual({ key: 'attention', text: '3 个组合 · 2 个目标待更新' })
  })

  it('未绑定与尚无目标并列成待办，弱中性', () => {
    const states: PortfolioTargetState[] = [ready(), { kind: 'uncalculated' }, ready()]
    const rollup = portfolioRollup({ total: 3, targetStates: states, unboundCount: 2, targetsReady: true })
    expect(rollup).toEqual({ key: 'todo', text: '3 个组合 · 2 个未绑定 · 1 个尚无目标' })
  })

  it('绑定关系未知时不计入判词', () => {
    const states: PortfolioTargetState[] = [ready(), ready()]
    const rollup = portfolioRollup({ total: 2, targetStates: states, unboundCount: null, targetsReady: true })
    expect(rollup).toEqual({ key: 'aligned', text: '2 个组合 · 全部到位' })
  })

  it('全部正常时中性在位档，不表扬', () => {
    const rollup = portfolioRollup({ total: 2, targetStates: [ready(), ready()], unboundCount: 0, targetsReady: true })
    expect(rollup).toEqual({ key: 'aligned', text: '2 个组合 · 全部到位' })
  })

  it('空仓组合算在位，不报警', () => {
    const states: PortfolioTargetState[] = [{ kind: 'empty', calculatedAt: '2026-08-27T09:03:26', stale: false }]
    const rollup = portfolioRollup({ total: 1, targetStates: states, unboundCount: 0, targetsReady: true })
    expect(rollup.key).toBe('aligned')
  })
})

describe('PORTFOLIO_ROLLUP 常量与账户舰队同语义', () => {
  it('图标与颜色三态映射', () => {
    expect(PORTFOLIO_ROLLUP_ICON).toEqual({ aligned: '✓', attention: '⚠', todo: '–' })
    expect(PORTFOLIO_ROLLUP_TEXT_CLASS.attention).toBe('text-warn')
    expect(PORTFOLIO_ROLLUP_TEXT_CLASS.aligned).toBe('text-ink-1')
    expect(PORTFOLIO_ROLLUP_TEXT_CLASS.todo).toBe('text-ink-3')
  })
})
