import type { TargetSizingAvailability, TargetSizingRow } from '@/types/api'

const EPS = 1e-9

export function sizingNumber(value: number, maximumFractionDigits = 4): string {
  return Math.abs(value).toLocaleString('zh-CN', { maximumFractionDigits })
}

export function weightText(value: number | null | undefined): string {
  if (value == null) return '—'
  if (Math.abs(value) <= EPS) return '空仓'
  return `${value > 0 ? '多' : '空'}${sizingNumber(value * 100, 2)}%`
}

export function quantityText(
  value: number | null | undefined,
  quantityLabel = '',
): string {
  if (value == null) return '—'
  const direction = Math.abs(value) > EPS ? Math.sign(value) : 0
  const prefix = direction < 0 ? '空' : direction > 0 ? '多' : ''
  return `${prefix}${sizingNumber(value, 6)}${quantityLabel}`
}

export function targetQuantityText(value: number | null | undefined, quantityLabel = ''): string {
  return value == null ? '—' : `${sizingNumber(value, 6)}${quantityLabel}`
}

export function isQuantizedZero(row: TargetSizingRow | null | undefined): boolean {
  return Boolean(
    row
      && row.reason_code === 'COMMON.SIZING.BELOW_MIN_QUANTITY'
      && row.raw_quantity != null
      && Math.abs(row.raw_quantity) > EPS
      && row.target_quantity != null
      && Math.abs(row.target_quantity) <= EPS,
  )
}

export function sizingReasonText(row: TargetSizingRow, quantityLabel = ''): string {
  if (isQuantizedZero(row)) return quantityLabel === '手' ? '不足1手' : '不足最小单位'
  if (row.reason_code.endsWith('.SIZING.BELOW_MIN_NOTIONAL')) return '不足最小名义金额'
  if (row.reason_code.endsWith('.SIZING.PURE_REDUCE_BELOW_MIN_NOTIONAL')) return '纯减仓例外'
  if (row.reason_code === 'COMMON.SIZING.MISSING_MARKET_DATA') return '缺少当时行情'
  if (row.reason_code === 'COMMON.SIZING.INVALID_PRICE') return '当时价格无效'
  if (row.reason_code === 'COMMON.SIZING.MISSING_UNIT_MULTIPLIER') return '缺少合约乘数'
  if (row.reason_code === 'COMMON.SIZING.QUANTIZED') {
    return row.quantity_step != null
      ? `按${sizingNumber(row.quantity_step)}${quantityLabel || '单位'}取整`
      : '按交易单位取整'
  }
  if (row.reason_code === 'COMMON.SIZING.ZERO_TARGET') return '目标为空'
  return row.status === 'UNAVAILABLE' ? '换算不可用' : '精确换算'
}

export function sizingAvailabilityText(status: TargetSizingAvailability): string {
  if (status === 'pending_execution') return '可执行数量将在下次执行时按当时行情生成'
  if (status === 'legacy') return '当时未记录换算依据'
  if (status === 'unavailable') return '当次换算依据不完整'
  return ''
}
