/** StepperNumberInput 的默认步进逻辑（纯函数，便于单测）。 */

/**
 * 默认步进：草稿为整数时 ±step 并夹在 [min, max]；非法/空草稿原样返回（按钮因此禁用）。
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
  options: { step: number; min: number; max?: number },
): string {
  const n = Number(value)
  if (value.trim() === '' || !Number.isInteger(n)) return value
  const next = n + direction * options.step
  return String(Math.max(options.min, options.max === undefined ? next : Math.min(options.max, next)))
}
