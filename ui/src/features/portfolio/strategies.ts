/**
 * 策略列表的纯函数运算。
 *
 * 集中「定义策略」页里与策略池无关的可测逻辑：粘贴导入解析、等权/归一化、
 * 头部摘要。均为无副作用函数，供 `StrategyComposer` 与 `ImportModal` 复用。
 */
import type { DraftStrategy } from '@/features/portfolio/diff'

/**
 * 折叠阈值。
 *
 * 策略数超过此值时，权重条明细折叠为一句摘要，并显示过滤输入框。
 */
export const FOLD = 12

/**
 * 解析粘贴文本为策略名列表.

 * 按空白 / 逗号 / 分号 / 顿号任意组合切分，去除首尾空白，并在输入内部去重
 * （保持首次出现顺序）。不做任何对错校验——无策略池可依。

 * Parameters
 * ----------
 * raw : str
 *     用户粘贴的原始文本。

 * Returns
 * -------
 * list of str
 *     去重后的策略名列表。
 */
export function parseNames(raw: string): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const tk of raw.split(/[\s,;、]+/)) {
    const name = tk.trim()
    if (!name || seen.has(name)) continue
    seen.add(name)
    out.push(name)
  }
  return out
}

/** `mergeImport` 的返回：并入后列表 + 新增数 + 跳过（已存在）数。 */
export interface MergeResult {
  merged: DraftStrategy[]
  added: number
  dup: number
}

/**
 * 把导入的策略名并入现有列表.

 * 已存在（同名）的跳过，新名字以 ``weight: 0`` 追加。调用方通常随后 `equalize`。

 * Parameters
 * ----------
 * existing : list of DraftStrategy
 *     当前组合内的策略行。
 * names : list of str
 *     待并入的策略名（一般来自 `parseNames`）。

 * Returns
 * -------
 * MergeResult
 *     并入后的列表与新增 / 跳过计数。
 */
export function mergeImport(existing: DraftStrategy[], names: string[]): MergeResult {
  const have = new Set(existing.map((s) => s.name))
  const merged = [...existing]
  let added = 0
  let dup = 0
  for (const name of names) {
    if (have.has(name)) {
      dup += 1
      continue
    }
    have.add(name)
    merged.push({ name, weight: 0 })
    added += 1
  }
  return { merged, added, dup }
}

/**
 * 等权：把权重平均分配到每一行（四舍五入到 0.1）.

 * Parameters
 * ----------
 * rows : list of DraftStrategy
 *     待处理的策略行。

 * Returns
 * -------
 * list of DraftStrategy
 *     等权后的新列表；空列表原样返回。
 */
export function equalize(rows: DraftStrategy[]): DraftStrategy[] {
  const n = rows.length
  if (!n) return rows
  const w = Math.round((100 / n) * 10) / 10
  return rows.map((r) => ({ ...r, weight: w }))
}

/**
 * 归一化：按当前权重比例缩放到合计 100%（各行四舍五入到 0.1）.

 * Parameters
 * ----------
 * rows : list of DraftStrategy
 *     待处理的策略行。

 * Returns
 * -------
 * list of DraftStrategy
 *     归一后的新列表；合计 ``<= 0`` 时原样返回。
 */
export function normalize(rows: DraftStrategy[]): DraftStrategy[] {
  const total = rows.reduce((s, r) => s + (r.weight || 0), 0)
  if (total <= 0) return rows
  return rows.map((r) => ({ ...r, weight: Math.round((r.weight / total) * 1000) / 10 }))
}

/** 头部摘要指标。 */
export interface StrategySummary {
  count: number
  sum: number
  max: number
  min: number
}

/**
 * 计算策略列表的摘要（个数、合计、最大 / 最小权重）.

 * Parameters
 * ----------
 * rows : list of DraftStrategy
 *     策略行。

 * Returns
 * -------
 * StrategySummary
 *     空列表时 ``max`` 与 ``min`` 均为 0。
 */
export function summary(rows: DraftStrategy[]): StrategySummary {
  const count = rows.length
  if (!count) return { count: 0, sum: 0, max: 0, min: 0 }
  let sum = 0
  let max = -Infinity
  let min = Infinity
  for (const r of rows) {
    const w = r.weight || 0
    sum += w
    if (w > max) max = w
    if (w < min) min = w
  }
  return { count, sum, max, min }
}
