export interface LeverageLimits {
  min: number
  max: number
  step: number
}

const DEFAULT_LIMITS: LeverageLimits = {
  min: 0,
  max: Number.POSITIVE_INFINITY,
  step: 0.1,
}

function limitsOf(limits?: Partial<LeverageLimits>): LeverageLimits {
  return {
    min: limits?.min ?? DEFAULT_LIMITS.min,
    max: limits?.max ?? DEFAULT_LIMITS.max,
    step: limits?.step && limits.step > 0 ? limits.step : DEFAULT_LIMITS.step,
  }
}

function decimals(step: number): number {
  const text = String(step)
  if (text.includes('e-')) return Number(text.split('e-')[1])
  return text.split('.')[1]?.length ?? 0
}

/** 将合法杠杆文本解析为数值；非法、越界或精度过细时返回 null。 */
export function leverageValue(value: string, limits?: Partial<LeverageLimits>): number | null {
  if (value.trim() === '') return null
  const leverage = Number(value)
  const resolved = limitsOf(limits)
  if (!Number.isFinite(leverage) || leverage < resolved.min || leverage > resolved.max) return null
  const steps = (leverage - resolved.min) / resolved.step
  if (Math.abs(steps - Math.round(steps)) > 1e-9) return null
  return leverage
}

/** 按运行时渠道约束校验账户杠杆。 */
export function leverageError(
  value: string,
  options: { allowEmpty?: boolean } & Partial<LeverageLimits> = {},
): string | null {
  if (value.trim() === '') return options.allowEmpty ? null : '请输入杠杆'
  const leverage = Number(value)
  const limits = limitsOf(options)
  if (!Number.isFinite(leverage)) return '需为数字'
  if (leverage < limits.min) return limits.min === 0 ? '需为非负数' : `需 ≥ ${limits.min}`
  if (leverage > limits.max) return `需 ≤ ${limits.max}`
  if (leverageValue(value, limits) === null) return `最小步进为 ${limits.step}`
  return null
}

/** 将合法杠杆按指定增量前后调整，并夹在渠道边界内。 */
export function stepLeverage(
  value: string,
  direction: -1 | 1,
  limits?: Partial<LeverageLimits>,
  increment?: number,
): string {
  const resolved = limitsOf(limits)
  const leverage = leverageValue(value, resolved)
  if (leverage === null) return value
  const next = Math.min(resolved.max, Math.max(resolved.min, leverage + direction * (increment ?? resolved.step)))
  return next.toFixed(decimals(resolved.step))
}

/** 将合法杠杆统一显示为一位小数。 */
export function formatLeverage(value: number, step = DEFAULT_LIMITS.step): string {
  return value.toFixed(decimals(step))
}
