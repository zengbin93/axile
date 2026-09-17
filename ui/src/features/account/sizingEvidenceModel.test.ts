import { describe, expect, it } from 'bun:test'

import {
  executableTargetFallbackText,
  isQuantizedZero,
  quantityText,
  sizingAvailabilityText,
  sizingReasonText,
  targetQuantityText,
  weightText,
} from './sizingEvidenceModel'
import type { TargetSizingRow } from '@/types/api'

function row(patch: Partial<TargetSizingRow> = {}): TargetSizingRow {
  return {
    symbol: 'm2701',
    sizing_mode: 'weight',
    status: 'SIZED',
    reason_code: 'COMMON.SIZING.BELOW_MIN_QUANTITY',
    strategy_weight: -0.0175,
    account_weight: -0.18,
    account_multiplier: 10.2857,
    weight_precision: 0.01,
    equity: 99_973.5875,
    reference_price: 3336,
    unit_multiplier: 10,
    unit_notional: 33_360,
    target_notional: 17_995.246,
    raw_quantity: -0.53943,
    target_quantity: 0,
    current_quantity: 0,
    quantity_step: 1,
    min_quantity: 1,
    min_notional: null,
    ...patch,
  }
}

describe('sizing evidence copy', () => {
  it('零手仍保留目标方向并直说不足一手', () => {
    const evidence = row()
    expect(weightText(evidence.account_weight)).toBe('空18%')
    expect(targetQuantityText(evidence.target_quantity, '手')).toBe('0手')
    expect(quantityText(evidence.current_quantity, '手')).toBe('0手')
    expect(sizingReasonText(evidence, '手')).toBe('不足1手')
    expect(isQuantizedZero(evidence)).toBe(true)
  })

  it('历史与待执行状态不伪造数量', () => {
    expect(sizingAvailabilityText('legacy')).toBe('当时未记录换算依据')
    expect(sizingAvailabilityText('pending_execution')).toContain('下次执行')
  })

  it('可执行目标缺手数时用状态词，不用空位符', () => {
    expect(executableTargetFallbackText('pending_execution')).toBe('待换算')
    expect(executableTargetFallbackText(null)).toBe('待换算')
    expect(executableTargetFallbackText('legacy')).toBe('当时未记')
    expect(executableTargetFallbackText('unavailable')).toBe('无法换算')
    expect(executableTargetFallbackText('available')).toBe('无法换算')
    expect(
      executableTargetFallbackText(
        'unavailable',
        row({ status: 'UNAVAILABLE', reason_code: 'COMMON.SIZING.MISSING_MARKET_DATA', target_quantity: null }),
      ),
    ).toBe('缺少当时行情')
    expect(
      executableTargetFallbackText(
        'unavailable',
        row({ status: 'UNAVAILABLE', reason_code: 'COMMON.SIZING.MISSING_UNIT_MULTIPLIER', target_quantity: null }),
      ),
    ).toBe('缺少合约乘数')
  })

  it('按渠道原因后缀解释最小名义金额，不让公共核心依赖渠道名', () => {
    expect(sizingReasonText(row({ reason_code: 'EXTERNAL.SIZING.BELOW_MIN_NOTIONAL' }), '')).toBe('不足最小名义金额')
    expect(sizingReasonText(row({ reason_code: 'EXTERNAL.SIZING.PURE_REDUCE_BELOW_MIN_NOTIONAL' }), '')).toBe('纯减仓例外')
  })
})
