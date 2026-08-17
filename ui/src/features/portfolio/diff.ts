/**
 * 组合演化的差分计算。
 *
 * - 规格 diff（策略权重）：完全前端可算、干净归因到「你改了什么」。
 * - 目标 diff（symbol 权重）：由后端 preview_weights 对旧/新配置背靠背取值后比对，
 *   仅作「生效后果」参考。
 */
import type { LatestWeights } from '@/types/api'

/** 一行草稿策略（权重以 % 表示，编辑态用）。 */
export interface DraftStrategy {
  name: string
  /** 百分比（如 40 表示 40%）。 */
  weight: number
}

/** 集中度指标（基于权重绝对值归一）。 */
export function concentration(weights: number[]): { max: number; eff: number; count: number } {
  const ws = weights.map(Math.abs).filter((w) => w > 0)
  const total = ws.reduce((s, w) => s + w, 0) || 1
  const norm = ws.map((w) => w / total)
  const max = (Math.max(0, ...norm)) * 100
  const eff = norm.length ? 1 / norm.reduce((s, w) => s + w * w, 0) : 0
  return { max, eff, count: ws.length }
}

export interface SpecDiff {
  added: DraftStrategy[]
  removed: { name: string; weight: number }[]
  changed: { name: string; from: number; to: number }[]
  /** 是否有任何实质改动。 */
  dirty: boolean
}

/** 规格 diff：草稿 vs 原配置（均为 % 权重）。 */
export function specDiff(original: DraftStrategy[], draft: DraftStrategy[]): SpecDiff {
  const origMap = new Map(original.map((s) => [s.name, s.weight]))
  const draftMap = new Map(draft.map((s) => [s.name, s.weight]))

  const added = draft.filter((s) => s.name.trim() && !origMap.has(s.name))
  const removed = original.filter((s) => !draftMap.has(s.name)).map((s) => ({ name: s.name, weight: s.weight }))
  const changed: { name: string; from: number; to: number }[] = []
  for (const s of draft) {
    if (!s.name.trim()) continue
    const from = origMap.get(s.name)
    if (from != null && Math.abs(from - s.weight) > 1e-9) {
      changed.push({ name: s.name, from, to: s.weight })
    }
  }
  return { added, removed, changed, dirty: added.length + removed.length + changed.length > 0 }
}

export interface TargetChange {
  symbol: string
  before: number // %
  after: number // %
  kind: 'entered' | 'exited' | 'increased' | 'decreased'
}

/** 目标 diff：before/after 均为 symbol→权重（小数）。输出按变化幅度降序。 */
export function targetDiff(before: LatestWeights, after: LatestWeights): TargetChange[] {
  const syms = new Set([...Object.keys(before), ...Object.keys(after)])
  const rows: TargetChange[] = []
  for (const s of syms) {
    const b = (before[s] ?? 0) * 100
    const a = (after[s] ?? 0) * 100
    if (Math.abs(a - b) < 0.05) continue
    const kind =
      Math.abs(b) < 1e-9 ? 'entered' : Math.abs(a) < 1e-9 ? 'exited' : a > b ? 'increased' : 'decreased'
    rows.push({ symbol: s, before: b, after: a, kind })
  }
  return rows.sort((x, y) => Math.abs(y.after - y.before) - Math.abs(x.after - x.before))
}
