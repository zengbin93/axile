/** StepperNumberInput 的默认步进逻辑（纯函数，便于单测）。 */

/**
 * 默认步进：默认整数步进；decimal 开启后允许小数。仅主动步进夹区间，非法/空草稿不变。
 *
 * Parameters
 * ----------
 * value : string
 *     当前草稿（字符串，输入态可能非法）。
 * direction : -1 | 1
 *     步进方向。
 * options : { step: number; min: number; max?: number }
 *     步长与区间，全部由使用方决定；max 缺省表示无上限。
 */
export function stepNumericValue(
  value: string,
  direction: -1 | 1,
  options: { step: number; min?: number; max?: number; decimal?: boolean; exclusiveMin?: boolean; exclusiveMax?: boolean },
): string {
  const n = Number(value)
  if (value.trim() === '' || !Number.isFinite(n) || (!options.decimal && !Number.isInteger(n))) return value
  if (!Number.isFinite(options.step) || options.step <= 0) return value
  const next = Number((n + direction * options.step).toPrecision(15))
  const bounded = Math.max(options.min ?? -Infinity, options.max === undefined ? next : Math.min(options.max, next))
  if ((options.exclusiveMin && bounded === options.min) || (options.exclusiveMax && bounded === options.max)) return value
  return String(bounded)
}
