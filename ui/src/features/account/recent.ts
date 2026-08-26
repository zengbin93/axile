/**
 * 「近期执行」的折叠/限量逻辑（纯函数，可测）。
 *
 * 原子视图的近期执行是「一瞥」，不是完整日志（那是 /history）。故：
 * - 连续的空跑（noop）折叠成一行；
 * - 连续的硬失败折叠成「连续 N 次执行失败」；
 * - 连续的部分成功自折，文案两面说（到位 + 未成），不与硬失败混折；
 * - 成交（fill）逐条保留；
 * - 整体限量到 cap 行，其余交给「完整回看」。
 */
import { formatMoney } from '@/lib/derive'
import type { AccountActivity } from '@/lib/api/accounts'
import type { ExecuteRecord } from '@/types/api'
import { executionReasonText } from '@/features/account/executionReason'
import { executionRecordError } from '@/features/account/executionRecordError'

type Kind = 'fill' | 'clear' | 'noop' | 'fail' | 'partial' | 'terminated' | 'blocked'

export type RecentRow =
  | { type: 'fill'; key: string; time: string; executionId: string | null; desc: string; amount: string }
  | { type: 'noop'; key: string; time: string; count: number }
  | { type: 'fail'; key: string; time: string; count: number; saturated: boolean; executionId: string | null; reason: string }
  | {
      type: 'partial'
      key: string
      time: string
      count: number
      saturated: boolean
      executionId: string | null
      reached: number | null
      failed: number | null
      reason: string
      amount: string
    }
  | { type: 'blocked'; key: string; time: string; count: number; executionId: string | null; reason: string }
  | { type: 'terminated'; key: string; time: string; count: number; executionId: string | null }
  | { type: 'skip'; key: string; time: string; count: number; reason: string }

const SUCCESS_STATUSES = new Set(['SUCCEEDED', 'NOOP'])
/** 顶层 error 里的品种计数句，部分成功行已有「N 只未成」，不再当原因复读。 */
const SYMBOL_COUNT_ERROR = /^\d+\s*个品种(执行未成功|被账户风控拦截)/

/** 本次执行相对上次改动了多少个品种的目标。 */
function changedCount(r: ExecuteRecord): number {
  const curr = r.raw_input?.curr_target ?? {}
  const last = r.raw_input?.last_target ?? {}
  const syms = new Set([...Object.keys(curr), ...Object.keys(last)])
  let changed = 0
  for (const s of syms) {
    if (Math.abs((curr[s] ?? 0) - (last[s] ?? 0)) > 1e-9) changed++
  }
  return changed
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null
}

/** 从顶层 error 解析「N 个品种执行未成功」的 N；对不上则 null。 */
function failedCountFromError(error: string): number | null {
  const match = error.match(/^(\d+)\s*个品种(执行未成功|被账户风控拦截)/)
  if (!match) return null
  const n = Number(match[1])
  return Number.isFinite(n) && n > 0 ? n : null
}

/**
 * 按品种终态数到位 / 未成。
 *
 * `SUCCEEDED`/`NOOP` 算到位；其余有 status 的算未成。没有 `symbol_results` 时
 * 从顶层计数句降级出未成数，到位未知。
 */
function symbolTally(r: ExecuteRecord): { reached: number | null; failed: number | null } {
  const results = asRecord(r.raw_result?.symbol_results)
  if (results) {
    let reached = 0
    let failed = 0
    for (const value of Object.values(results)) {
      const status = asRecord(value)?.status
      if (typeof status !== 'string') continue
      if (SUCCESS_STATUSES.has(status)) reached += 1
      else failed += 1
    }
    if (reached + failed > 0) return { reached, failed }
  }
  const error = executionRecordError(r)
  return { reached: null, failed: error ? failedCountFromError(error) : null }
}

function isPartial(r: ExecuteRecord): boolean {
  const { reached, failed } = symbolTally(r)
  if (reached === 0) return false
  if ((reached ?? 0) > 0 && (failed ?? 0) > 0) return true
  return r.raw_result?.status === 'PARTIAL'
}

function specificError(r: ExecuteRecord): string {
  const error = executionRecordError(r)
  if (!error || SYMBOL_COUNT_ERROR.test(error)) return ''
  return error
}

function assetAmount(r: ExecuteRecord): string {
  const total = r.raw_result?.account_assets?.total_asset
  return typeof total === 'number' ? formatMoney(total) : ''
}

/**
 * 记录分类：终止 / 约束跳过 / 部分成功 / 失败 / 清仓 / 空跑 / 成交。
 *
 * 先判 `task_status==='TERMINATED'`：终止是「人工/系统提前收尾」，非硬失败。
 * 再判执行器 `BLOCKED`：非交易时段等约束，不进「连续失败」。
 * 再判部分成功：有品种到位、有品种未成（或 `status==='PARTIAL'`），不进硬失败。
 * 再判成功清仓（`execution_kind==='clear_positions'`）：确有平仓成交，不应按调仓口径误判为「空跑」。
 */
function kindOf(r: ExecuteRecord): Kind {
  if (r.raw_result?.task_status === 'TERMINATED') return 'terminated'
  if (r.raw_result?.status === 'BLOCKED') return 'blocked'
  if (isPartial(r)) return 'partial'
  if (r.is_success !== 1) return 'fail'
  if (r.raw_result?.execution_kind === 'clear_positions') return 'clear'
  return changedCount(r) === 0 ? 'noop' : 'fill'
}

/** 成交/清仓行的描述与金额（两者都是「有成交的成功执行」，同一 ✓ 样式）。 */
function fillRow(r: ExecuteRecord, i: number, kind: 'fill' | 'clear'): RecentRow {
  const amount = assetAmount(r)
  return {
    type: 'fill',
    key: `${kind === 'clear' ? 'c' : 'f'}${r.id ?? r.execution_id ?? i}`,
    time: r.created_at,
    executionId: r.execution_id ?? null,
    desc: kind === 'clear' ? '清仓执行' : `调仓执行 · ${changedCount(r)} 处变动`,
    amount: amount || '—',
  }
}

function partialRow(latest: ExecuteRecord, i: number, count: number, saturated: boolean): RecentRow {
  const { reached, failed } = symbolTally(latest)
  return {
    type: 'partial',
    key: `p${i}`,
    time: latest.created_at,
    count,
    saturated,
    executionId: latest.execution_id ?? null,
    reached,
    failed,
    reason: specificError(latest),
    amount: assetAmount(latest),
  }
}

/** 一瞥行主文案；详情与执行记录页共用，避免两处各写一句。 */
export function recentRowText(row: RecentRow): string {
  if (row.type === 'fill') return row.desc
  if (row.type === 'noop') return `${row.count > 1 ? `${row.count} 次空跑` : '空跑'} · 目标未变`
  if (row.type === 'fail') {
    const head = row.count > 1 ? `连续 ${row.count}${row.saturated ? '+' : ''} 次执行失败` : '执行失败'
    return row.reason ? `${head} · 最近：${row.reason}` : head
  }
  if (row.type === 'partial') {
    const head = row.count > 1 ? `连续 ${row.count}${row.saturated ? '+' : ''} 次部分执行` : '部分执行'
    const latest = [
      row.reached != null ? `${row.reached} 只到位` : '',
      row.failed != null && row.failed > 0 ? `${row.failed} 只未成` : '',
      row.reason,
    ].filter(Boolean)
    if (latest.length === 0) return head
    return row.count > 1 ? `${head} · 最近：${latest.join(' · ')}` : `${head} · ${latest.join(' · ')}`
  }
  if (row.type === 'terminated') return row.count > 1 ? `已终止 · ${row.count} 次` : '已终止'
  if (row.type === 'skip') return row.count > 1 ? `连续 ${row.count} 次${row.reason}` : row.reason
  return `${row.count > 1 ? `${row.count} 次非交易时段` : '非交易时段，未下单'}${row.reason ? ` · ${row.reason}` : ''}`
}

export interface RecentResult {
  rows: RecentRow[]
  /** 折叠/限量后仍有更多，去完整回看看。 */
  truncated: boolean
}

/**
 * 把（按时间倒序的）执行记录折叠成近期执行行。
 *
 * Parameters
 * ----------
 * records : 按 created_at 倒序（最新在前）的执行记录。
 * cap : 最多展示的行数（成交行与折叠组各算一行）。
 * fetchLimit : 拉取时用的 limit；用于判断末尾的失败/空跑组是否「饱和」（窗口拉满、
 *              库里可能还有更多同类，展示为 N+）。
 */
/** 把统一账户活动流折叠为近期展示行。 */
export function buildRecentActivity(
  activity: AccountActivity[],
  opts: { cap?: number; fetchLimit?: number } = {},
): RecentResult {
  const cap = opts.cap ?? 6
  const fetchLimit = opts.fetchLimit ?? activity.length
  const windowFull = activity.length >= fetchLimit

  const all: RecentRow[] = []
  let i = 0
  while (i < activity.length) {
    const current = activity[i]
    if (current.kind === 'schedule_skip') {
      let j = i + 1
      while (j < activity.length && activity[j].kind === 'schedule_skip') j += 1
      all.push({
        type: 'skip',
        key: `s${current.id}`,
        time: current.occurred_at,
        count: j - i,
        reason: executionReasonText(current.reason_code, '排程已跳过'),
      })
      i = j
      continue
    }
    const k = kindOf(current.record)
    if (k === 'fill' || k === 'clear') {
      all.push(fillRow(current.record, i, k))
      i += 1
      continue
    }
    // 折叠一段连续的同类（noop / fail / partial / terminated / blocked）
    let j = i
    while (j < activity.length) {
      const candidate = activity[j]
      if (candidate.kind !== 'execution' || kindOf(candidate.record) !== k) break
      j += 1
    }
    const run = activity.slice(i, j).map((item) => item.kind === 'execution' ? item.record : null).filter((item): item is ExecuteRecord => item != null)
    const latest = run[0]
    const saturated = j === activity.length && windowFull
    if (k === 'noop') {
      all.push({ type: 'noop', key: `n${i}`, time: latest.created_at, count: run.length })
    } else if (k === 'terminated') {
      all.push({
        type: 'terminated',
        key: `t${i}`,
        time: latest.created_at,
        count: run.length,
        executionId: latest.execution_id ?? null,
      })
    } else if (k === 'blocked') {
      all.push({
        type: 'blocked',
        key: `b${i}`,
        time: latest.created_at,
        count: run.length,
        executionId: latest.execution_id ?? null,
        reason: executionRecordError(latest),
      })
    } else if (k === 'partial') {
      all.push(partialRow(latest, i, run.length, saturated))
    } else {
      all.push({
        type: 'fail',
        key: `x${i}`,
        time: latest.created_at,
        count: run.length,
        saturated,
        executionId: latest.execution_id ?? null,
        reason: executionRecordError(latest),
      })
    }
    i = j
  }

  return { rows: all.slice(0, cap), truncated: all.length > cap }
}
