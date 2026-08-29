import type { PortfolioTargetState } from './portfolioCardSummary'

/**
 * 组合页头判词的三态键。
 *
 * 与账户舰队同一套注意力预算：琥珀只给「偏离」（目标更新失败），待办走弱中性，
 * 全到位是「没消息」不是「好消息」，不烧颜色。
 */
export type PortfolioRollupKey = 'attention' | 'todo' | 'aligned'

export interface PortfolioRollup {
  key: PortfolioRollupKey
  text: string
}

export const PORTFOLIO_ROLLUP_ICON: Record<PortfolioRollupKey, string> = {
  aligned: '✓',
  attention: '⚠',
  todo: '–',
}

export const PORTFOLIO_ROLLUP_TEXT_CLASS: Record<PortfolioRollupKey, string> = {
  aligned: 'text-ink-1',
  attention: 'text-warn',
  todo: 'text-ink-3',
}

export interface PortfolioRollupInput {
  /** 组合总数；为 0（含加载中/加载失败）时页头退回纯标题，不下判词。 */
  total: number
  /** 每个组合的目标态（与卡片同一份派生结果）。 */
  targetStates: PortfolioTargetState[]
  /** 未绑定账户的组合数；null 表示绑定关系未知（账户未就绪/不可用），不计入判词。 */
  unboundCount: number | null
  /** 全部目标快照请求已落定；未定前的判词是缺证据，不报「全部到位」。 */
  targetsReady: boolean
}

/**
 * 派生组合页头判词：偏离（琥珀）> 待办（弱中性）> 在位（中性）。
 *
 * 待办并列呈现两类来源：未绑定账户（组合闲置）与尚无目标（从未计算）。
 */
export function portfolioRollup({ total, targetStates, unboundCount, targetsReady }: PortfolioRollupInput): PortfolioRollup {
  if (total === 0) return { key: 'aligned', text: '组合' }
  if (!targetsReady) return { key: 'todo', text: `${total} 个组合` }

  const attention = targetStates.filter(
    (state) => state.kind === 'unavailable' || ((state.kind === 'ready' || state.kind === 'empty') && state.stale),
  ).length
  if (attention > 0) {
    return { key: 'attention', text: `${total} 个组合 · ${attention} 个目标待更新` }
  }

  const todos: string[] = []
  if (unboundCount != null && unboundCount > 0) todos.push(`${unboundCount} 个未绑定`)
  const uncalculated = targetStates.filter((state) => state.kind === 'uncalculated').length
  if (uncalculated > 0) todos.push(`${uncalculated} 个尚无目标`)
  if (todos.length > 0) return { key: 'todo', text: `${total} 个组合 · ${todos.join(' · ')}` }

  return { key: 'aligned', text: `${total} 个组合 · 全部到位` }
}
