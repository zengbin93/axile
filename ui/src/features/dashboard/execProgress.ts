/**
 * 执行阶段进度模型 —— 与后端 `axile.server.execution.live.PHASE_ORDER` 一一对应。
 *
 * 五步确定态阶段条：触发 → 冻结输入 → 算目标 → 下单 → 对账。后端事件流按此推进
 * （单调不回退），前端据 phase 键渲染阶段条与文案。
 */

/** 阶段键 → 中文短标签，顺序即进度顺序。 */
export const PHASES = [
  { key: 'triggered', label: '触发' },
  { key: 'snapshot', label: '冻结输入' },
  { key: 'planning', label: '算目标' },
  { key: 'executing', label: '下单' },
  // 后端 key 沿用 `settling`，但这步实质是「对账」（核对实际仓位 vs 目标、产出
  // reconciliation），永续调仓无 T+n 交收/CCP 清算，故标签用机构口径的「对账」而非「结算」。
  { key: 'settling', label: '对账' },
] as const

export type PhaseKey = (typeof PHASES)[number]['key']

/** 阶段键 → 索引；未知/空阶段回落到 0（触发）。 */
export function phaseIndex(phase: string | null | undefined): number {
  const i = PHASES.findIndex((p) => p.key === phase)
  return i < 0 ? 0 : i
}

/** 阶段键 → 进行时文案（用于「正在执行 · X」）。 */
export function phaseLabel(phase: string | null | undefined): string {
  return PHASES[phaseIndex(phase)]?.label ?? '触发'
}

/** 执行种类 → 动词（区分「执行 / 清仓」的进行态标题）。 */
export function runVerb(kind: string | null | undefined): string {
  return kind === 'clear_positions' || kind === 'clear' ? '清仓' : '执行'
}
