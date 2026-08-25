/**
 * 把执行事件流 + 附件组合成「执行详情」视图模型（纯函数，与组件解耦、便于测试）。
 *
 * 详情页把这次执行的因果链路都用上：头条结论、目标变化（为什么调）、逐只子链
 * （意图→决策→下单→成交→到位）、外层生命周期脊柱、以及可下钻的原始证据。所有派生集中
 * 在此，组件只做渲染。
 */
import { eventError } from '@/features/account/executionRows'
import { executionReasonText, symbolSkipSummaryReason } from '@/features/account/executionReason'
import { describeFailure, describeFailureText, type FailureReason } from '@/features/account/failureReason'
import type {
  AccountSnapshotSource,
  ExecOrder,
  ExecutionArtifact,
  ExecutionEvent,
  ExecutionReconciliation,
  ExecutionStatus,
  SymbolTca,
} from '@/types/api'

/** 逐只动作分类（描述这次执行对该品种做了什么）。 */
export type ChainAction = 'reduce' | 'increase' | 'open' | 'close' | 'flip' | 'aligned' | 'skipped' | 'failed'

/** 单只执行子链：意图→决策→下单→成交→到位，附带浮盈与断点。 */
export interface SymbolChain {
  symbol: string
  action: ChainAction
  /** 执行前带号持仓。 */
  before: number
  /** 执行后带号持仓。 */
  after: number
  /** 意图带号目标量。 */
  target: number | null
  algorithm: string | null
  ordersCount: number | null
  side: 'buy' | 'sell' | 'none'
  /** 带号成交量（买正卖负）。 */
  filled: number
  /** 带号成交金额。 */
  filledValue: number
  avgPrice: number | null
  filledRatio: number | null
  /** 订单终态文案（已成交/已撤销/…）。 */
  terminalStatus: string | null
  clientOrderId: string | null
  /** 该只从触发到订单终态的耗时（秒）。 */
  legSeconds: number | null
  attainedRatio: number | null
  reached: boolean | null
  drift: number
  pnlBefore: number | null
  pnlAfter: number | null
  /** 逐只执行质量（TCA-lite）。 */
  tca: SymbolTca | null
  /** 订单→成交树。 */
  orders: ExecOrder[]
  /** 是否为断点（欠量/撤销/跳过/失败），供 UI 变红并默认展开。 */
  broken: boolean
  /** 断点原因（跳过/失败/撤销时的可读说明）。 */
  reason: string
}

/** 头条：整条链坍缩成的结论。 */
export interface ExecutionHeader {
  kind: string
  trigger: string
  durationSec: number | null
  reachedCount: number
  totalCount: number
  failedCount: number
  equityBefore: number | null
  equityAfter: number | null
  /** 敞口 = 持仓市值 / 总权益（%）。 */
  exposureBefore: number | null
  exposureAfter: number | null
  /**
   * 到位/持仓真相的来源标：只依赖执行后快照（after）。
   *
   * 到位度（``attainedRatio`` / ``reached``）由「after 持仓 vs target」派生，与执行前基线无关，
   * 故 before 缺失也不污染它——after 为 ``real`` 时到位度即可信。
   */
  sourcePosition: AccountSnapshotSource
  /**
   * 权益 / 敞口 / drift 的来源标：这些量是「后 − 前」的跨端差，取两端较差者。
   *
   * 只要有一端非 ``real``，权益变动与敞口对比即退化，故与 ``sourcePosition`` 分标：
   * before 单独缺失时，仅此标退化、到位度仍可信。
   */
  sourceEquity: AccountSnapshotSource
  success: boolean
}

/** 目标变化段：回答「为什么调仓」。 */
export interface TargetChange {
  rows: { symbol: string; last: number | null; curr: number }[]
  algorithm: string | null
  algoParams: string | null
  forbidden: string[]
  risk: string[]
}

/** 外层生命周期脊柱的一个节点。 */
export interface SpineNode {
  key: string
  label: string
  detail: string
  time: string
  status: 'INFO' | 'SUCCESS' | 'WARNING' | 'ERROR'
  broken: boolean
}

/** 账户前后书签：证据区用的结构化账户事实（替代裸 JSON）。 */
export interface AccountBookends {
  cashBefore: number | null
  cashAfter: number | null
  equityBefore: number | null
  equityAfter: number | null
  mvBefore: number | null
  mvAfter: number | null
  /** 冻结输入里的执行超时（秒）。 */
  timeoutSec: number | null
}

/** 执行详情完整视图模型。 */
export interface ExecutionDetailModel {
  header: ExecutionHeader
  targetChange: TargetChange | null
  symbols: SymbolChain[]
  spine: SpineNode[]
  bookends: AccountBookends
  artifacts: ExecutionArtifact[]
  hasReconciliation: boolean
  /** 执行级失败判词（-1021 等翻成人话）；无 execution_failed 事件时为 null。 */
  failure: FailureReason | null
  /** 执行任务状态真源；旧记录或接口不可用时为 null。 */
  task: ExecutionStatus | null
}

type Dict = Record<string, unknown>

const AT = {
  standardInput: 'standard_input',
  target: 'target_snapshot',
  before: 'account_snapshot_before',
  after: 'account_snapshot',
  summary: 'execution_summary',
} as const

const SOURCE_RANK: Record<string, number> = { real: 0, assumed: 1, error: 2, unavailable: 3 }

/** 取某类型附件的 content（无则 null）。 */
function artifactContent(artifacts: ExecutionArtifact[], type: string): Dict | null {
  const found = artifacts.find((a) => a.artifact_type === type)
  return found ? (found.content as Dict) : null
}

function asDict(v: unknown): Dict | null {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Dict) : null
}

function asNum(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

function asStr(v: unknown): string {
  return typeof v === 'string' ? v : ''
}

/** 秒级 ISO 本地时间戳 → `HH:MM:SS`。 */
function hhmmss(ts: string): string {
  const t = ts.includes('T') ? ts.split('T')[1] : ts
  return (t ?? '').slice(0, 8)
}

/** 两个本地 ISO 时间戳的秒差（后-前），无法解析时为 null。 */
function diffSeconds(from: string | null, to: string | null): number | null {
  if (!from || !to) return null
  const a = Date.parse(from)
  const b = Date.parse(to)
  if (Number.isNaN(a) || Number.isNaN(b)) return null
  return (b - a) / 1000
}

/** 账户快照 content → account_assets 字典。 */
function accountAssets(content: Dict | null): Dict | null {
  return content ? asDict(content.account_assets) : null
}

/** 账户快照来源标；无则按传入回退。 */
function snapshotSource(content: Dict | null, assets: Dict | null): AccountSnapshotSource {
  const s = asStr(content?.source) || asStr(assets?.source)
  return (s || 'unavailable') as AccountSnapshotSource
}

/** 敞口 = 持仓市值 / 总权益（%）。 */
function exposure(assets: Dict | null): number | null {
  const mv = asNum(assets?.market_value)
  const eq = asNum(assets?.total_asset)
  if (mv == null || eq == null || eq === 0) return null
  return (mv / eq) * 100
}

/** 从账户快照里取每只的未实现盈亏（`positions[].extra.unrealized_pnl`）。 */
function pnlBySymbol(assets: Dict | null): Map<string, number> {
  const out = new Map<string, number>()
  const positions = assets?.positions
  if (!Array.isArray(positions)) return out
  for (const p of positions) {
    const pd = asDict(p)
    const symbol = asStr(pd?.symbol)
    const extra = asDict(pd?.extra)
    const pnl = asNum(extra?.unrealized_pnl)
    if (symbol && pnl != null) out.set(symbol, pnl)
  }
  return out
}

/** 由前/后/目标（带号）派生逐只动作分类。 */
function classifyAction(before: number, after: number, target: number | null): ChainAction {
  const eps = 1e-9
  if (target == null) return Math.abs(after - before) < eps ? 'aligned' : 'reduce'
  if (Math.abs(before) < eps && Math.abs(target) >= eps) return 'open'
  if (Math.abs(target) < eps) return 'close'
  if (Math.sign(before) !== Math.sign(target) && Math.abs(before) >= eps) return 'flip'
  return Math.abs(target) < Math.abs(before) ? 'reduce' : 'increase'
}

/** 订单方向枚举串（`OrderDirection.SELL`）→ 买/卖。 */
function orderSide(direction: string): 'buy' | 'sell' | 'none' {
  const d = direction.toUpperCase()
  if (d.includes('SELL') || direction.includes('卖')) return 'sell'
  if (d.includes('BUY') || direction.includes('买')) return 'buy'
  return 'none'
}

interface OrderInfo {
  terminalStatus: string | null
  filledRatio: number | null
  clientOrderId: string | null
  side: 'buy' | 'sell' | 'none'
  ts: string | null
}

/** 逐只聚合 `order_terminal` 事件（取最后一条终态）。 */
function ordersBySymbol(events: ExecutionEvent[]): Map<string, OrderInfo> {
  const out = new Map<string, OrderInfo>()
  for (const e of events) {
    if (e.event_type !== 'order_terminal' || !e.symbol) continue
    const details = asDict(e.details)
    const order = asDict(details?.order)
    const exchange = asDict(details?.exchange)
    out.set(e.symbol, {
      terminalStatus: asStr(order?.terminal_status || order?.status) || null,
      filledRatio: asNum(order?.filled_ratio),
      clientOrderId: asStr(exchange?.client_order_id) || null,
      side: orderSide(asStr(order?.direction)),
      ts: e.ts_local_created || null,
    })
  }
  return out
}

interface DecisionInfo {
  algorithm: string | null
  ordersCount: number | null
  status: string | null
}

/** 逐只聚合 `symbol_decision_made` 事件。 */
function decisionsBySymbol(events: ExecutionEvent[]): Map<string, DecisionInfo> {
  const out = new Map<string, DecisionInfo>()
  for (const e of events) {
    if (e.event_type !== 'symbol_decision_made' || !e.symbol) continue
    const decision = asDict(asDict(e.details)?.decision)
    out.set(e.symbol, {
      algorithm: asStr(decision?.algorithm) || null,
      ordersCount: asNum(decision?.orders_count),
      status: asStr(decision?.status) || null,
    })
  }
  return out
}

/** 逐只聚合 `symbol_skipped` 事件的原因。 */
function skipsBySymbol(events: ExecutionEvent[]): Map<string, string> {
  const out = new Map<string, string>()
  for (const e of events) {
    if (e.event_type !== 'symbol_skipped' || !e.symbol) continue
    const reason = eventError(e) || symbolSkipSummaryReason(e.reason_code)
    if (reason) out.set(e.symbol, reason)
  }
  return out
}

/** 组装单只子链。 */
function buildSymbolChain(
  recon: Record<string, unknown>,
  startedAt: string | null,
  orders: Map<string, OrderInfo>,
  decisions: Map<string, DecisionInfo>,
  skips: Map<string, string>,
  pnlBefore: Map<string, number>,
  pnlAfter: Map<string, number>,
): SymbolChain {
  const symbol = asStr(recon.symbol)
  const before = asNum(recon.before) ?? 0
  const after = asNum(recon.after) ?? 0
  const target = asNum(recon.target)
  const reached = typeof recon.reached === 'boolean' ? recon.reached : null
  const order = orders.get(symbol)
  const decision = decisions.get(symbol)
  const skipReason = skips.get(symbol)

  let action = classifyAction(before, after, target)
  let reason = ''
  if (skipReason) {
    action = 'skipped'
    reason = skipReason
  } else if (decision?.status && decision.status !== 'SUCCEEDED') {
    // 订单腿非成功（FAILED/BLOCKED/NOOP…）：是否「失败」由仓位真相判定，而非订单枚举。
    // 仅「确认到位」（reached===true）免罪：受阻/空跑但仓位已在目标 → 保持原动作、不判失败；
    // 未到位或结果未知（reached 为 false/null）→ 真断点，标记失败。
    const raw = asStr(recon.status) || decision.status
    // FAILED 只是「失败」的同义反复，交给动作标签/未到位表达；受阻/空跑/撤单等才是有信息量的原因。
    if (raw !== 'FAILED') reason = STATUS_LABEL[raw] ?? raw
    if (reached !== true) action = 'failed'
  }

  const terminalStatus = order?.terminalStatus ?? null
  const canceled = terminalStatus != null && (terminalStatus.includes('撤') || terminalStatus.includes('拒'))
  if (canceled && !reason) reason = terminalStatus ?? ''

  // 断点＝主动跳过、订单腿失败、或仓位掉出目标；「受阻/空跑但已到位」不再算断点（安静即好）。
  const broken = action === 'skipped' || action === 'failed' || reached === false

  return {
    symbol,
    action,
    before,
    after,
    target,
    algorithm: decision?.algorithm ?? null,
    ordersCount: decision?.ordersCount ?? null,
    side: order?.side ?? 'none',
    filled: asNum(recon.filled) ?? 0,
    filledValue: asNum(recon.filled_value) ?? 0,
    avgPrice: asNum(recon.avg_price),
    filledRatio: order?.filledRatio ?? null,
    terminalStatus,
    clientOrderId: order?.clientOrderId ?? null,
    legSeconds: diffSeconds(startedAt, order?.ts ?? null),
    attainedRatio: asNum(recon.attained_ratio),
    reached,
    drift: asNum(recon.drift) ?? 0,
    pnlBefore: pnlBefore.get(symbol) ?? null,
    pnlAfter: pnlAfter.get(symbol) ?? null,
    tca: (asDict(recon.tca) as SymbolTca | null) ?? null,
    orders: Array.isArray(recon.orders) ? (recon.orders as ExecOrder[]) : [],
    broken,
    reason,
  }
}

/** 人读的算法参数摘要（PASSIVE 挂单 · 追价…）。 */
function algoParamsText(params: Dict | null): string | null {
  if (!params) return null
  const parts: string[] = []
  const strategy = asStr(params.price_strategy)
  if (strategy) parts.push(strategy)
  if (params.chase_enabled === true) {
    const n = asNum(params.max_chase_count)
    const iv = asNum(params.chase_interval)
    parts.push(n != null && iv != null ? `追价≤${n}×${iv}s` : '追价')
  }
  return parts.length ? parts.join(' · ') : null
}

/** 组装目标变化段。 */
function buildTargetChange(artifacts: ExecutionArtifact[]): TargetChange | null {
  const target = artifactContent(artifacts, AT.target)
  const stdInput = asDict(artifactContent(artifacts, AT.standardInput)?.input)
  const curr = asDict(target?.curr_target) ?? asDict(stdInput?.curr_target)
  if (!curr) return null
  const last = asDict(target?.last_target) ?? asDict(stdInput?.last_target)
  const rows = Object.keys(curr).map((symbol) => ({
    symbol,
    curr: asNum(curr[symbol]) ?? 0,
    last: last ? asNum(last[symbol]) : null,
  }))
  const algo = asDict(stdInput?.algorithm)
  const forbidden = Array.isArray(stdInput?.forbidden_symbols) ? (stdInput.forbidden_symbols as string[]) : []
  const risk = Array.isArray(stdInput?.risk_symbols) ? (stdInput.risk_symbols as string[]) : []
  return {
    rows,
    algorithm: asStr(algo?.method) || null,
    algoParams: algoParamsText(asDict(algo?.params)),
    forbidden,
    risk,
  }
}

/** 账户快照来源的降级人话（``real`` 为默认良好态、保持安静不显示）。 */
export const SOURCE_DEGRADED_LABEL: Record<string, string> = {
  assumed: '假设值',
  error: '读取失败',
  unavailable: '不可用',
}

/** 执行终态枚举 → 人话。 */
const STATUS_LABEL: Record<string, string> = {
  SUCCEEDED: '成功',
  FAILED: '失败',
  PARTIAL: '部分成功',
  BLOCKED: '受阻',
  NOOP: '空跑',
}

/**
 * 脊柱「算目标」的变更旗标：目标逐只独立，不塌成单一值，只报「变了没、往哪变」.
 *
 * 无上次目标 → 首次建目标；无一变化 → 目标未变；全下调/全上调/有增有减 → 下调/上调/调整。
 */
function targetSummary(tc: TargetChange | null): string {
  if (!tc || tc.rows.length === 0) return ''
  const hasLast = tc.rows.some((r) => r.last != null)
  if (!hasLast) return '首次建目标'
  const changed = tc.rows.filter((r) => r.last != null && r.last !== r.curr)
  if (changed.length === 0) return '目标未变'
  const allDown = changed.every((r) => r.curr < (r.last ?? r.curr))
  const allUp = changed.every((r) => r.curr > (r.last ?? r.curr))
  if (allDown) return '目标下调'
  if (allUp) return '目标上调'
  return '目标调整'
}

/** 逐只归入「减仓(阶段1)」或「开仓(阶段2)」，翻向两阶段都占。 */
function symbolPhase(s: SymbolChain): 'reduce' | 'increase' | 'both' | 'none' {
  switch (s.action) {
    case 'reduce':
    case 'close':
      return 'reduce'
    case 'increase':
    case 'open':
      return 'increase'
    case 'flip':
      return 'both'
    case 'aligned':
      return 'none'
    default:
      if (s.target == null) return 'none'
      return Math.abs(s.target) < Math.abs(s.before) ? 'reduce' : 'increase'
  }
}

/** 构造一个阶段脊柱节点（并行调度、带到位与断点）。 */
function phaseNode(key: string, label: string, group: SymbolChain[], gateHint: string): SpineNode {
  const reached = group.filter((s) => s.reached === true).length
  const anyBroken = group.some((s) => s.broken)
  const detail = `并行 ${group.length} 只 · ${reached}/${group.length} 到位${gateHint}`
  return { key, label, detail, time: '', status: anyBroken ? 'WARNING' : 'SUCCESS', broken: anyBroken }
}

/** 由一条生命周期事件取时间与状态。 */
function eventAt(events: ExecutionEvent[], type: string): ExecutionEvent | undefined {
  return events.find((e) => e.event_type === type)
}

/** 组装外层生命周期脊柱。 */
function buildSpine(
  events: ExecutionEvent[],
  artifacts: ExecutionArtifact[],
  symbols: SymbolChain[],
  targetChange: TargetChange | null,
  failure: FailureReason | null,
): SpineNode[] {
  const nodes: SpineNode[] = []
  const started = eventAt(events, 'execution_started')
  const input = eventAt(events, 'input_snapshotted')
  const target = eventAt(events, 'target_computed')
  const completed = eventAt(events, 'execution_completed')
  const failed = eventAt(events, 'execution_failed')

  const beforeContent = artifactContent(artifacts, AT.before)
  const beforeAssets = accountAssets(beforeContent)
  const afterContent = artifactContent(artifacts, AT.after)
  const afterAssets = accountAssets(afterContent)

  if (started) {
    nodes.push({
      key: 'started',
      label: '触发',
      detail: '',
      time: hhmmss(started.ts_local_created),
      status: 'INFO',
      broken: false,
    })
  }
  if (input) {
    const symbolCount = asNum(asDict(asDict(input.details)?.debug)?.symbol_count)
    nodes.push({
      key: 'input',
      label: '冻结输入',
      detail: symbolCount != null ? `${symbolCount} 品种` : '',
      time: hhmmss(input.ts_local_created),
      status: 'INFO',
      broken: false,
    })
  }
  if (beforeContent) {
    const src = snapshotSource(beforeContent, beforeAssets)
    nodes.push({
      key: 'before',
      label: '读执行前账户',
      detail: SOURCE_DEGRADED_LABEL[src] ?? '',
      time: hhmmss(asStr(beforeAssets?.update_time)),
      status: src === 'real' ? 'INFO' : 'WARNING',
      broken: src !== 'real',
    })
  }
  if (target) {
    nodes.push({
      key: 'target',
      label: '算目标',
      detail: targetSummary(targetChange),
      time: hhmmss(target.ts_local_created),
      status: 'INFO',
      broken: false,
    })
  }
  if (symbols.length > 0) {
    const phase1 = symbols.filter((s) => {
      const p = symbolPhase(s)
      return p === 'reduce' || p === 'both'
    })
    const phase2 = symbols.filter((s) => {
      const p = symbolPhase(s)
      return p === 'increase' || p === 'both'
    })
    if (phase1.length > 0) nodes.push(phaseNode('phase1', '阶段1 减仓', phase1, ''))
    if (phase2.length > 0) {
      nodes.push(phaseNode('phase2', '阶段2 开仓', phase2, phase1.length > 0 ? ' · 阶段1 全成才跑' : ''))
    }
    // 全部到位无动作（aligned）时也给一个标记，别让脊柱在此断档。
    if (phase1.length === 0 && phase2.length === 0) {
      nodes.push({ key: 'phase', label: '逐只执行', detail: `${symbols.length} 只无变动`, time: '', status: 'INFO', broken: false })
    }
  }
  if (afterContent) {
    const src = snapshotSource(afterContent, afterAssets)
    nodes.push({
      key: 'after',
      label: '读执行后账户',
      detail: SOURCE_DEGRADED_LABEL[src] ?? '',
      time: hhmmss(asStr(afterAssets?.update_time)),
      status: src === 'real' ? 'INFO' : 'WARNING',
      broken: src !== 'real',
    })
  }
  if (failed) {
    nodes.push({
      key: 'failed',
      label: '执行失败',
      detail: failure?.human || eventError(failed) || executionReasonText(failed.reason_code, '执行失败'),
      time: hhmmss(failed.ts_local_created),
      status: 'ERROR',
      broken: true,
    })
  } else if (completed) {
    const debug = asDict(asDict(completed.details)?.debug)
    const st = asStr(debug?.execution_status)
    nodes.push({
      key: 'completed',
      label: '对账',
      detail: STATUS_LABEL[st] ?? '完成',
      time: hhmmss(completed.ts_local_created),
      status: completed.status,
      broken: false,
    })
  }
  return nodes
}

/** 取整条执行的对账块（execution_summary.content.reconciliation）。 */
function reconciliationOf(artifacts: ExecutionArtifact[]): ExecutionReconciliation | null {
  const summary = artifactContent(artifacts, AT.summary)
  const recon = asDict(summary?.reconciliation)
  return recon ? (recon as unknown as ExecutionReconciliation) : null
}

/**
 * 由事件流与附件组合出执行详情视图模型.
 *
 * @param events - 执行事件流（`GET .../events`）。
 * @param artifacts - 执行附件（`GET .../artifacts`）。
 */
export function buildExecutionDetail(
  events: ExecutionEvent[],
  artifacts: ExecutionArtifact[],
  task: ExecutionStatus | null = null,
): ExecutionDetailModel {
  const started = eventAt(events, 'execution_started')
  const startedAt = started?.ts_local_created ?? null
  const startedDebug = asDict(asDict(started?.details)?.debug)

  const summary = artifactContent(artifacts, AT.summary)
  const recon = reconciliationOf(artifacts)
  const beforeAssets = accountAssets(artifactContent(artifacts, AT.before))
  const afterAssets = accountAssets(artifactContent(artifacts, AT.after))

  const orders = ordersBySymbol(events)
  const decisions = decisionsBySymbol(events)
  const skips = skipsBySymbol(events)
  const pnlBefore = pnlBySymbol(beforeAssets)
  const pnlAfter = pnlBySymbol(afterAssets)

  const symbols: SymbolChain[] = (recon?.symbols ?? []).map((s) =>
    buildSymbolChain(s as unknown as Record<string, unknown>, startedAt, orders, decisions, skips, pnlBefore, pnlAfter),
  )

  const reachedCount = symbols.filter((s) => s.reached === true).length
  // 「项失败」是逐只成交结果口径：真正判失败的品种数，而非 ERROR 事件数。对账失败等
  // 生命周期 ERROR 只是逐只失败的回声，重复计入会虚增（交给脊柱表达即可）。
  const failedCount = symbols.filter((s) => s.action === 'failed').length

  const srcBefore = (recon?.account.source_before ?? 'unavailable') as AccountSnapshotSource
  const srcAfter = (recon?.account.source_after ?? 'unavailable') as AccountSnapshotSource
  // 到位度只依赖执行后快照，故持仓族直接取 after；权益/敞口/drift 是跨端差，取两端较差。
  const sourcePosition = srcAfter
  const sourceEquity = (SOURCE_RANK[srcBefore] ?? 3) >= (SOURCE_RANK[srcAfter] ?? 3) ? srcBefore : srcAfter

  const header: ExecutionHeader = {
    kind: asStr(startedDebug?.execution_kind) || task?.execution_kind || 'rebalance',
    trigger: asStr(startedDebug?.trigger_source) || '',
    durationSec: asNum(summary?.execution_time) ?? diffSeconds(task?.started_at ?? null, task?.finished_at ?? null),
    reachedCount,
    totalCount: symbols.length,
    failedCount,
    equityBefore: recon?.account.equity_before ?? asNum(beforeAssets?.total_asset),
    equityAfter: recon?.account.equity_after ?? asNum(afterAssets?.total_asset),
    exposureBefore: exposure(beforeAssets),
    exposureAfter: exposure(afterAssets),
    sourcePosition,
    sourceEquity,
    success: summary?.success === true || (summary?.success == null && failedCount === 0 && symbols.length > 0),
  }

  const stdInput = asDict(artifactContent(artifacts, AT.standardInput)?.input)
  const bookends: AccountBookends = {
    cashBefore: asNum(beforeAssets?.available_cash),
    cashAfter: asNum(afterAssets?.available_cash),
    equityBefore: asNum(beforeAssets?.total_asset),
    equityAfter: asNum(afterAssets?.total_asset),
    mvBefore: asNum(beforeAssets?.market_value),
    mvAfter: asNum(afterAssets?.market_value),
    timeoutSec: asNum(stdInput?.execution_timeout),
  }

  const targetChange = buildTargetChange(artifacts)
  const failure = describeFailure(eventAt(events, 'execution_failed'))
    ?? (task?.status === 'FAILED' ? describeFailureText(task.error ?? '') : null)

  return {
    header,
    targetChange,
    symbols,
    spine: buildSpine(events, artifacts, symbols, targetChange, failure),
    bookends,
    artifacts,
    hasReconciliation: recon != null,
    failure,
    task,
  }
}
