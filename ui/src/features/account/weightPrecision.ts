const POWER_TOLERANCE = 1e-9

/** 校验权重精度：必须为 10 的非正整数次幂。 */
export function weightPrecisionError(value: string, options: { allowEmpty?: boolean } = {}): string | null {
  if (value.trim() === '') return options.allowEmpty ? null : '请输入权重精度'
  const precision = Number(value)
  if (!Number.isFinite(precision) || precision <= 0) return '需为正数'
  const exponent = Math.log10(precision)
  if (exponent > POWER_TOLERANCE || Math.abs(exponent - Math.round(exponent)) > POWER_TOLERANCE) {
    return '需为 1、0.1、0.01…'
  }
  return null
}

/** 按十倍数量级调整权重精度；数值越小，精度越高。 */
export function stepWeightPrecision(value: string, direction: -1 | 1): string {
  if (weightPrecisionError(value) !== null) return value
  const precision = Number(value)
  const next = direction === -1 ? precision / 10 : precision * 10
  if (!Number.isFinite(next) || next > 1 || next <= 0) return value
  const exponent = Math.round(Math.log10(next))
  return exponent >= 0 ? '1' : `0.${'0'.repeat(-exponent - 1)}1`
}

/** 将小数权重精度翻译为用户更容易理解的百分比。 */
export function weightPrecisionPercent(value: string): string | null {
  if (weightPrecisionError(value) !== null) return null
  return `${Number(value) * 100}%`
}
