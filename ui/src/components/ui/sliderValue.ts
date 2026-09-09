/** 将轨道比例吸附到从最小值起算的刻度；端点始终可达。 */
export function sliderValueAt(ratio: number, min: number, max: number, step: number): number {
  if (ratio <= 0) return min
  if (ratio >= 1) return max
  const value = min + Math.round(ratio * (max - min) / step) * step
  return Number(Math.max(min, Math.min(max, value)).toPrecision(15))
}
