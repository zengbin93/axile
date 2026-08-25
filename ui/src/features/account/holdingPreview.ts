import type { RebalancePlan, RebalanceRow } from '@/lib/derive'

export interface HoldingAdjustmentPreview {
  row: RebalanceRow
  value: number | null
}

/** 取待调整幅度最大的前几项，并按账户权益换算调整金额。 */
export function topHoldingAdjustments(
  plan: RebalancePlan,
  equity: number,
  limit = 3,
): HoldingAdjustmentPreview[] {
  return plan.rows
    .filter((row) => row.action !== 'aligned')
    .toSorted((left, right) => right.amount - left.amount)
    .slice(0, limit)
    .map((row) => ({
      row,
      value: equity > 0 ? (row.amount / 100) * equity : null,
    }))
}

/** 预计总换手为所有待调整品种绝对权重差之和。 */
export function rebalanceTurnover(plan: RebalancePlan): number {
  return plan.rows
    .filter((row) => row.action !== 'aligned')
    .reduce((sum, row) => sum + row.amount, 0)
}
