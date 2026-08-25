import { useCallback, useState } from 'react'
import { useParams } from 'react-router'
import { Breadcrumb } from '@/components/ui/Breadcrumb'
import { Card } from '@/components/ui/Card'
import { SkeletonLines } from '@/components/ui/Skeleton'
import { NumberTicker } from '@/components/ui/NumberTicker'
import { usePolling } from '@/lib/hooks/usePolling'
import { getExecutionArtifacts, getExecutionEvents } from '@/lib/api/executions'
import { currencyOf } from '@/lib/derive'
import { displayCurrencyUnit, fmtMoney, withCurrency } from '@/lib/format'
import {
  buildExecutionDetail,
  SOURCE_DEGRADED_LABEL,
  type ChainAction,
  type ExecutionDetailModel,
  type SymbolChain,
} from '@/features/account/executionDetail'
import { buildSymbolActionStream, type ActionLine } from '@/features/account/actionStream'
import { BLAME_LABEL, type FailureReason } from '@/features/account/failureReason'
import { PhaseBar } from '@/features/dashboard/PhaseBar'
import { accountAssetTerms } from '@/features/dashboard/display'
import { useDomainStore } from '@/stores/domain'
import { useChannelDescriptor } from '@/stores/channels'
import { useRunning } from '@/stores/liveExec'
import type { ChannelCapability, ExecOrder, ExecutionArtifact, ExecutionEvent } from '@/types/api'

/** 触发来源文案。 */
const TRIGGER_LABEL: Record<string, string> = { manual: '手动', scheduler: '定时', empty_positions: '清仓' }
/** 主/被动成交文案。 */
const LIQUIDITY_LABEL: Record<string, string> = { passive: '被动', aggressive: '主动', mixed: '混合' }
/** 订单类型文案。 */
const ORDER_TYPE_LABEL: Record<string, string> = { LIMIT: '限价', MARKET: '市价' }
/** 执行类型文案。 */
const KIND_LABEL: Record<string, string> = { rebalance: '调仓', clear_positions: '清仓' }
/** 逐只动作标签。 */
const ACTION_LABEL: Record<ChainAction, string> = {
  reduce: '减仓',
  increase: '加仓',
  open: '建仓',
  close: '清仓',
  flip: '翻向',
  aligned: '到位',
  skipped: '跳过',
  failed: '失败',
}
/**
 * 脊柱节点圆点着色。
 *
 * 三族分明、皆不碰红绿（红绿专供行情涨跌）：过程步=中性弱点，正向里程碑（到位/对账成功）
 * =accent 蓝给一个从容的确认，注意/错误=同一琥珀——错误的严重度改由断点行的填充/标签承载，
 * 不借「失败红」。蓝只标「干得好」，琥珀只标「要看看」，二者互不遮蔽。
 */
const DOT_CLASS: Record<string, string> = {
  INFO: 'bg-border-strong',
  SUCCESS: 'bg-accent',
  WARNING: 'bg-warn',
  ERROR: 'bg-warn',
}

type DisplayUnits = ChannelCapability['units']

const DEFAULT_UNITS: DisplayUnits = {
  quantity_kind: 'custom',
  quantity_label: '',
  quantity_max_decimals: 6,
  price_label: '',
  notional_label: '',
}

/** 持仓/成交量按渠道精度格式化，并在需要时追加单位。 */
function fmtQty(v: number, units: DisplayUnits, withUnit = true): string {
  const value = Math.abs(v).toLocaleString('zh-CN', {
    maximumFractionDigits: units.quantity_max_decimals,
  })
  return withUnit && units.quantity_label ? `${value} ${units.quantity_label}` : value
}

/** 价格按通用精度格式化，并追加渠道报价单位。 */
function fmtPrice(v: number, units: DisplayUnits, currency: string): string {
  const value = Math.abs(v).toLocaleString('zh-CN', { maximumFractionDigits: 6 })
  const label = displayCurrencyUnit(units.price_label || currency)
  return label ? `${value} ${label}` : value
}

/** 基础资产数量按品种派生实际单位；无法可靠拆分时保留插件提供的兜底标签。 */
function unitsForSymbol(units: DisplayUnits, symbol: string, currency: string): DisplayUnits {
  if (units.quantity_kind !== 'base_asset') return units
  const normalizedSymbol = symbol.toUpperCase()
  const normalizedCurrency = currency.toUpperCase()
  if (!normalizedCurrency || !normalizedSymbol.endsWith(normalizedCurrency)) return units
  const baseAsset = normalizedSymbol.slice(0, -normalizedCurrency.length)
  return baseAsset ? { ...units, quantity_label: baseAsset } : units
}

/** 权益金额：两位小数、千分位。 */
function fmtEquity(v: number | null): string {
  return v == null ? '—' : v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** 带符号权益差。 */
function fmtDelta(before: number | null, after: number | null): string {
  if (before == null || after == null) return ''
  const d = after - before
  return `${d >= 0 ? '+' : '−'}${Math.abs(d).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

/** 耗时秒 → `41.2s` / `1m5s`。 */
function fmtDuration(sec: number | null): string {
  if (sec == null) return ''
  if (sec < 60) return `${sec.toFixed(1)}s`
  const m = Math.floor(sec / 60)
  return `${m}m${Math.round(sec % 60)}s`
}

/** 敞口整数百分数。 */
function expPct(v: number | null): string {
  return v == null ? '—' : `${Math.round(v)}%`
}

/** 滑点 bps：带号、有利为正。 */
function fmtBps(v: number): string {
  return `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(2)}bps`
}

/**
 * 滑点着色（三态，红绿只留给行情涨跌，故用 accent/ink/warn 表执行质量）。
 *
 * 有利为正：``> +0.05`` 吃到价格改善＝accent 蓝「表扬极」；``< -0.05`` 付出成本＝琥珀「报警极」；
 * 其间视作持平＝中性，安静。补上「表扬极」后，好成交不再和平庸成交同为一片灰。
 */
function bpsCls(v: number): string {
  if (v > 0.05) return 'text-accent'
  if (v < -0.05) return 'text-warn'
  return 'text-ink-3'
}

/** 头条判词（成交结果口径，非事件计数）。 */
function verdict(m: ExecutionDetailModel): { icon: string; cls: string; text: string } {
  const { reachedCount, totalCount, failedCount } = m.header
  const notReached = totalCount - reachedCount
  // 执行级失败（如时钟偏移 -1021 在下单前中止）优先做判词，别让 0 逐只塌成中性「无结果」。
  if (m.failure) return { icon: '✕', cls: 'text-warn font-bold', text: `执行失败 · ${m.failure.category}` }
  if (failedCount > 0) return { icon: '✕', cls: 'text-warn font-bold', text: `${failedCount} 项失败` }
  if (notReached > 0) return { icon: '⚠', cls: 'text-warn', text: `${reachedCount}/${totalCount} 到位 · ${notReached} 只未到位` }
  if (totalCount === 0) return { icon: '–', cls: 'text-ink-3', text: '无逐只结果' }
  return { icon: '✓', cls: 'text-accent', text: `${totalCount} 只到位` }
}

/** 头条：整条链坍缩成的结论 + 诚实来源条。 */
function Header({ m, currency, assetLabel }: { m: ExecutionDetailModel; currency: string; assetLabel: string }) {
  const v = verdict(m)
  const h = m.header
  const meta = [TRIGGER_LABEL[h.trigger] ?? h.trigger, KIND_LABEL[h.kind] ?? h.kind].filter(Boolean).join(' ')
  return (
    <div className="mt-3">
      <div className={`inline-flex items-center gap-2 text-[15px] font-semibold ${v.cls}`}>
        {v.icon} {v.text}
      </div>
      <div className="num mt-2 text-[13px] text-ink-2">
        {meta && <span className="text-ink-3">{meta} · </span>}
        {h.durationSec != null && <span className="text-ink-3">{fmtDuration(h.durationSec)} · </span>}
        {assetLabel} {fmtEquity(h.equityBefore)} → {h.equityAfter == null ? '—' : <NumberTicker value={h.equityAfter} format={{ minimumFractionDigits: 2, maximumFractionDigits: 2 }} />}
        {h.equityBefore != null && h.equityAfter != null && (
          <span className={`font-semibold ${h.equityAfter >= h.equityBefore ? 'text-up' : 'text-down'}`}>
            {' '}
            ({fmtDelta(h.equityBefore, h.equityAfter)}) {displayCurrencyUnit(currency)}
          </span>
        )}
        {h.exposureBefore != null && (
          <span className="text-ink-3">
            {' · '}敞口 {expPct(h.exposureBefore)} → {h.exposureAfter == null ? '—' : <NumberTicker value={h.exposureAfter} format={{ maximumFractionDigits: 0 }} suffix="%" />}
          </span>
        )}
      </div>
      <SnapshotNote h={h} assetLabel={assetLabel} />
      {m.failure && <FailureNote f={m.failure} />}
    </div>
  )
}

/**
 * 快照来源提示条：按「到位度」与「权益」两族各自的来源标分别措辞，不做全局塌缩。
 *
 * 到位度只依赖执行后快照，权益/敞口/drift 是跨前后差。故：执行后快照退化时，两族皆不可信，
 * 出强提示；仅执行前基线缺失时，只有权益族退化、到位度仍可信，出「只警告该退化的量」的准提示。
 * 琥珀只点在真正偏离的量上，不再把可信的到位度也刷成「仅供参考」。
 */
function SnapshotNote({ h, assetLabel }: { h: ExecutionDetailModel['header']; assetLabel: string }) {
  const posBad = h.sourcePosition !== 'real'
  const eqBad = h.sourceEquity !== 'real'
  if (!posBad && !eqBad) return null
  const label = (s: string) => SOURCE_DEGRADED_LABEL[s] ?? s
  // sourceEquity 恒不优于 sourcePosition：posBad ⇒ 执行后快照退化 ⇒ 两族皆污染。
  const note = posBad
    ? `执行后账户快照为「${label(h.sourcePosition)}」——到位度与${assetLabel}均基于非真实快照，仅供参考。`
    : `执行前基线为「${label(h.sourceEquity)}」——${assetLabel}变动与敞口对比不可得；到位度基于执行后真实快照，仍然可信。`
  return <div className="mt-2 rounded bg-warn-soft px-2.5 py-1.5 text-[12.5px] text-warn">{note}</div>
}

/**
 * 失败判词：把执行级失败（-1021 等）翻成人话——主因 + 归谁 + 可否重试 + 下一步，原始错误可下钻。
 *
 * 「偏离」头条点进来后回答「为什么」。走琥珀（失败=注意，不碰红绿）。
 */
function FailureNote({ f }: { f: FailureReason }) {
  return (
    <div className="mt-2 rounded bg-warn-soft px-3 py-2 text-[12.5px] text-warn">
      <div className="font-medium">{f.human}</div>
      <div className="mt-0.5 text-[12px]">
        归{BLAME_LABEL[f.blame]} · {f.retryable ? '同步前置后可重试' : '需先处理再重试'} · {f.action}
      </div>
      {f.raw && (
        <details className="mt-1">
          <summary className="cursor-pointer select-none text-[11.5px] text-ink-3 hover:text-ink-2">原始错误</summary>
          <div className="num mt-1 break-all whitespace-pre-wrap text-[11.5px] text-ink-3">{f.raw}</div>
        </details>
      )}
    </div>
  )
}

/** ② 目标变化段：回答「为什么调」。 */
function TargetChangeView({ m }: { m: ExecutionDetailModel }) {
  const tc = m.targetChange
  if (!tc) return null
  return (
    <div className="mb-4">
      <div className="mb-2 text-xs font-semibold tracking-wide text-ink-3">目标变化</div>
      <div className="num text-[13px] text-ink-2">
        {tc.rows.map((r) => (
          <span key={r.symbol} className="mr-4 inline-block">
            {r.symbol}{' '}
            {r.last != null && <span className="text-ink-3">{(r.last * 100).toFixed(0)}% → </span>}
            <span className="font-medium">{(r.curr * 100).toFixed(0)}%</span>
          </span>
        ))}
      </div>
      {(tc.algorithm || tc.algoParams) && (
        <div className="mt-1.5 text-[12px] text-ink-3">
          {[tc.algorithm, tc.algoParams].filter(Boolean).join(' · ')}
        </div>
      )}
      {(tc.forbidden.length > 0 || tc.risk.length > 0) && (
        <div className="mt-1 text-[12px] text-warn">
          {tc.forbidden.length > 0 && <span>禁止 {tc.forbidden.join('/')} </span>}
          {tc.risk.length > 0 && <span>风控 {tc.risk.join('/')}</span>}
        </div>
      )}
    </div>
  )
}

/** 订单 → 成交 树（默认折叠的取证下钻）。 */
function OrderTree({ orders, currency, units }: { orders: ExecOrder[]; currency: string; units: DisplayUnits }) {
  if (orders.length === 0) return null
  const nTrades = orders.reduce((n, o) => n + o.trades.length, 0)
  return (
    <details className="mt-1.5">
      <summary className="cursor-pointer select-none text-[11.5px] text-ink-3 hover:text-ink-2">
        订单与成交（{orders.length} 单 · {nTrades} 成交）
      </summary>
      <div className="mt-1 border-l border-line pl-3">
        {orders.map((o) => (
          <div key={o.order_id} className="num py-1 text-[11.5px]">
            <div className="text-ink-2">
              {o.side === 'sell' ? '卖' : o.side === 'buy' ? '买' : ''} {ORDER_TYPE_LABEL[o.order_type] ?? o.order_type}
              {o.price != null && <span> @{fmtPrice(o.price, units, currency)}</span>}
              {' · '}成交 {fmtQty(o.filled_volume ?? 0, units, false)}/{fmtQty(o.volume ?? 0, units)}
              {o.status && <span className="text-ink-3"> · {o.status}</span>}
              {o.client_order_id && <span className="text-ink-3"> · {o.client_order_id}</span>}
            </div>
            {o.trades.map((t, i) => (
              <div key={i} className="pl-3 text-ink-3">
                成交 {fmtQty(t.volume ?? 0, units)} @{fmtPrice(t.price ?? 0, units, currency)}
                {t.fee > 0 && <span> · 费 {withCurrency(fmtMoney(t.fee), t.fee_asset ?? currency)}</span>}
                {t.time && <span> · {t.time.slice(11, 19)}</span>}
              </div>
            ))}
          </div>
        ))}
      </div>
    </details>
  )
}

/** ③ 单只子链：意图 → 决策 → 成交 →（执行质量）→ 到位，可下钻因果动作流/订单成交。 */
function SymbolChainRow({
  s,
  currency,
  units,
  lines,
}: {
  s: SymbolChain
  currency: string
  units: DisplayUnits
  lines: ActionLine[]
}) {
  // 到位=accent 蓝 ✓（正向确认，蓝≠红绿故不撞涨跌）；未到位/欠量=琥珀 ⚠。
  // 到位比例随成交推进而变，用 NumberTicker 里程表式滚动（仅 isLive 轮询下值真变时才动，完成态静止）。
  const ratioNode =
    s.attainedRatio == null ? null : (
      <NumberTicker value={s.attainedRatio * 100} format={{ minimumFractionDigits: 2, maximumFractionDigits: 2 }} suffix="%" />
    )
  const outcome = s.reached
    ? { cls: 'text-accent', node: <>到位 ✓ {ratioNode ?? '—'}</> }
    : { cls: 'text-warn', node: ratioNode != null ? <>⚠ 欠量 · 到位 {ratioNode}</> : <>⚠ 未到位</> }
  const sideText = s.side === 'sell' ? '卖' : s.side === 'buy' ? '买' : ''
  const driftNotable = Math.abs(s.drift) > 1e-6
  // 浮盈：当前水平取 after（无则回退 before）。未成交时前→后 Δ 纯为行情漂移、与执行无关，
  // 只显当前水平、不摆箭头（不把行情盈亏栽到执行头上）；成交了才显前→后。
  const pnlLevel = s.pnlAfter ?? s.pnlBefore
  const showPnlDelta = s.filled !== 0 && s.pnlBefore != null && s.pnlAfter != null
  const tca = s.tca
  const hasQuality = tca != null && (tca.n_trades > 0 || tca.slippage_bps != null)

  return (
    <div className={`border-t border-line py-3 first:border-t-0 ${s.broken ? 'bg-warn-soft/50 -mx-6 px-6' : ''}`}>
      <div className="flex items-baseline justify-between gap-3">
        <div className="flex items-baseline gap-2">
          <span className="text-[13.5px] font-medium">{s.symbol}</span>
          <span className="text-[11px] text-ink-3">{ACTION_LABEL[s.action]}</span>
        </div>
        <span className={`text-[13px] font-semibold ${outcome.cls}`}>{outcome.node}</span>
      </div>

      {/* 意图 → 结果 */}
      <div className="num mt-1 text-[12.5px] text-ink-2">
        意图 {fmtQty(s.before, units)} → {fmtQty(s.after, units)}
        {s.target != null && <span className="text-ink-3"> （目标 {fmtQty(s.target, units)}）</span>}
      </div>

      {/* 决策 + 成交 */}
      {s.side !== 'none' && s.filled !== 0 && (
        <div className="num mt-0.5 text-[12.5px] text-ink-3">
          {s.algorithm && <span>{s.algorithm} · </span>}
          {sideText} {fmtQty(s.filled, units)}
          {s.avgPrice != null && <span> @{fmtPrice(s.avgPrice, units, currency)}</span>}
          <span className="text-ink-2">
            {' '}（≈{withCurrency(fmtMoney(s.filledValue), units.notional_label || currency)}）
          </span>
          {s.terminalStatus && <span className={s.broken ? 'text-warn' : ''}> · {s.terminalStatus}</span>}
          {s.legSeconds != null && <span> · 用时 {Math.round(s.legSeconds)}s</span>}
        </div>
      )}

      {/* 执行质量（TCA）：主/被动 · 滑点 · 费用 · 单/成交笔数 */}
      {hasQuality && (
        <div className="num mt-0.5 text-[12px]">
          {tca.liquidity && <span className="text-ink-2">{LIQUIDITY_LABEL[tca.liquidity] ?? tca.liquidity}</span>}
          {tca.slippage_bps != null && (
            <span className={bpsCls(tca.slippage_bps)}>
              {tca.liquidity ? ' · ' : ''}滑点 {fmtBps(tca.slippage_bps)}
            </span>
          )}
          {tca.fee > 0 && (
            <span className="text-ink-3"> · 费 {withCurrency(fmtMoney(tca.fee), tca.fee_asset ?? currency)}</span>
          )}
          <span className="text-ink-3">
            {' · '}
            {tca.n_orders} 单 {tca.n_trades} 成交
            {tca.fill_ratio != null && tca.fill_ratio < 0.999 && (
              <span className="text-warn"> · 成交率 {(tca.fill_ratio * 100).toFixed(0)}%</span>
            )}
          </span>
        </div>
      )}

      {/* 订单腿原因：断点时琥珀主因（为何没到位）；已到位时降为中性注脚（受阻/空跑，安静即好）。 */}
      {s.reason && (
        <div className={`mt-0.5 text-[12px] ${s.broken ? 'font-medium text-warn' : 'text-ink-3'}`}>{s.reason}</div>
      )}

      {/* 浮盈 / drift */}
      {(pnlLevel != null || driftNotable) && (
        <div className="num mt-0.5 text-[11.5px] text-ink-3">
          {pnlLevel != null && (
            <span>浮盈 {showPnlDelta ? `${s.pnlBefore!.toFixed(1)} → ${s.pnlAfter!.toFixed(1)}` : pnlLevel.toFixed(1)}</span>
          )}
          {driftNotable && <span className="text-warn"> · 偏差 {s.drift.toFixed(4)}</span>}
        </div>
      )}

      {/* 下钻：因果动作流（主）→ 订单成交（取证） */}
      <SymbolActionStream lines={lines} orders={s.orders} currency={currency} units={units} />
    </div>
  )
}

/** ④ 外层控制面骨干（生命周期，细框、带时序、断点变红）——跨品种的两阶段门控在此。 */
function Spine({ m }: { m: ExecutionDetailModel }) {
  if (m.spine.length === 0) return null
  return (
    <div className="mt-5">
      <div className="mb-2 text-xs font-semibold tracking-wide text-ink-3">执行链路</div>
      <div className="relative pl-[22px]">
        <div className="absolute left-1.5 top-1.5 bottom-1.5 w-0.5 bg-line" />
        {m.spine.map((n) => (
          <div key={n.key} className="relative flex items-baseline gap-3 py-1.5">
            <span
              className={`absolute -left-[17px] top-[9px] h-[9px] w-[9px] rounded-full border-2 border-surface ${DOT_CLASS[n.status] ?? DOT_CLASS.INFO}`}
            />
            {n.time && <span className="num w-20 flex-none text-[11px] text-ink-3">{n.time}</span>}
            {!n.time && <span className="w-20 flex-none" />}
            <span className={`text-[13px] ${n.broken ? 'font-medium text-warn' : 'text-ink-2'}`}>{n.label}</span>
            {n.detail && <span className="num text-[12px] text-ink-3">{n.detail}</span>}
          </div>
        ))}
      </div>
    </div>
  )
}

/**
 * 单只泳道展开：因果动作流（决策→挂单→追价→成交）为主叙事，其下嵌套订单树作逐笔取证。
 *
 * 逐只行默认折叠 → 多品种也只是多行摘要，钻进关心的那只才展开，天然 scale。
 */
function SymbolActionStream({
  lines,
  orders,
  currency,
  units,
}: {
  lines: ActionLine[]
  orders: ExecOrder[]
  currency: string
  units: DisplayUnits
}) {
  if (lines.length === 0) return <OrderTree orders={orders} currency={currency} units={units} />
  return (
    <details className="mt-1.5">
      <summary className="cursor-pointer select-none text-[11.5px] text-ink-3 hover:text-ink-2">
        动作流（{lines.length} 步）
      </summary>
      <div className="mt-1 border-l border-line pl-3">
        {lines.map((l) => (
          <div key={l.key} className="num flex items-baseline gap-2 py-0.5 text-[12px]">
            {l.time && <span className="w-16 flex-none text-ink-3">{l.time}</span>}
            {/* 三态：琥珀断点 / accent 蓝正向确认(成交·对账成功) / 中性过程步 */}
            <span className={l.broken ? 'font-medium text-warn' : l.good ? 'text-accent' : 'text-ink-2'}>{l.text}</span>
          </div>
        ))}
        <OrderTree orders={orders} currency={currency} units={units} />
      </div>
    </details>
  )
}

/**
 * 账户书签一行：`现金 A→B`（结构化，不摊 JSON）。
 *
 * ``pnl=true`` 时(仅权益)追加带号 Δ 并按红涨绿跌着色——权益差＝真盈亏，是本页唯一「色＝钱」处；
 * 现金/市值只是资金在现金与持仓间搬家、非盈亏，故保持中性，绝不误用涨跌色。
 */
function BookendRow({
  label,
  before,
  after,
  currency,
  pnl = false,
}: {
  label: string
  before: number | null
  after: number | null
  currency: string
  pnl?: boolean
}) {
  if (before == null && after == null) return null
  const showDelta = pnl && before != null && after != null && Math.abs(after - before) >= 0.005
  return (
    <span className="mr-4 inline-block">
      <span className="text-ink-3">{label} </span>
      {before != null ? withCurrency(fmtMoney(before), currency) : '—'}
      <span className="text-ink-3"> → </span>
      {after != null ? withCurrency(fmtMoney(after), currency) : '—'}
      {showDelta && before != null && after != null && (
        <span className={`font-semibold ${after >= before ? 'text-up' : 'text-down'}`}> ({fmtDelta(before, after)})</span>
      )}
    </span>
  )
}

/** ⑤ 证据：账户前后的结构化事实 + 一键复制原始附件（不再内联裸 JSON）。 */
function Evidence({ m, currency, assetLabel }: { m: ExecutionDetailModel; currency: string; assetLabel: string }) {
  const b = m.bookends
  const [copied, setCopied] = useState(false)
  const copy = () => {
    void navigator.clipboard.writeText(JSON.stringify(m.artifacts, null, 2)).then(() => {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    })
  }
  const hasAccount = b.cashBefore != null || b.equityBefore != null || b.mvBefore != null
  return (
    <div className="mt-5">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-semibold tracking-wide text-ink-3">证据</span>
        {m.artifacts.length > 0 && (
          <button type="button" onClick={copy} className="text-[12px] text-accent hover:underline">
            {copied ? '已复制' : `复制原始附件（${m.artifacts.length}）`}
          </button>
        )}
      </div>
      {hasAccount && (
        <div className="num text-[12.5px] text-ink-2">
          <BookendRow label="现金" before={b.cashBefore} after={b.cashAfter} currency={currency} />
          <BookendRow label={assetLabel} before={b.equityBefore} after={b.equityAfter} currency={currency} pnl />
          <BookendRow label="市值" before={b.mvBefore} after={b.mvAfter} currency={currency} />
        </div>
      )}
      {b.timeoutSec != null && <div className="mt-1 text-[12px] text-ink-3">冻结输入 · 执行超时 {b.timeoutSec}s</div>}
    </div>
  )
}

/**
 * 执行详情路由页 /accounts/:id/executions/:executionId。
 *
 * 一台「可追溯的信任仪器」：把后端记录的这次执行信息都用上——头条结论、目标变化、逐只子链
 * （意图→决策→下单→成交→到位）、外层生命周期脊柱、可下钻的原始证据。成功时安静、失败时在
 * 断点处变红。
 */
export function ExecutionDetailPage() {
  const { id, executionId } = useParams()
  const accountId = Number(id)
  const accounts = useDomainStore((s) => s.accounts)
  const item = accounts?.find((a) => a.account_id === accountId) ?? null
  const name = item?.name ?? `账户 #${accountId}`
  const currency = currencyOf(item?.currency)
  const descriptor = useChannelDescriptor(item?.trade_channel)
  const units = descriptor?.units ?? DEFAULT_UNITS
  const assetTerms = accountAssetTerms(item?.trade_channel)

  const eventsFetcher = useCallback(
    (signal: AbortSignal): Promise<{ data: ExecutionEvent[] }> =>
      executionId ? getExecutionEvents(executionId, signal) : Promise.resolve({ data: [], count: 0 }),
    [executionId],
  )
  const artifactsFetcher = useCallback(
    (signal: AbortSignal): Promise<{ data: ExecutionArtifact[] }> =>
      executionId ? getExecutionArtifacts(executionId, signal) : Promise.resolve({ data: [], count: 0 }),
    [executionId],
  )
  // 本次执行是否仍在跑（服务端真源，SSE 秒级点亮）：在跑则短轮询让脊柱边跑边长，
  // 结束后回落到一次性取数（静态取证）。
  const running = useRunning(accountId)
  const isLive = running != null && running.executionId === executionId
  const pollMs = isLive ? 2500 : 0
  const events = usePolling(eventsFetcher, {
    queryKey: `execution:${executionId ?? 'missing'}:events`,
    intervalMs: pollMs,
    enabled: Boolean(executionId),
  })
  const artifacts = usePolling(artifactsFetcher, {
    queryKey: `execution:${executionId ?? 'missing'}:artifacts`,
    intervalMs: pollMs,
    enabled: Boolean(executionId),
  })

  const loading = events.loading || artifacts.loading
  const error = events.error || artifacts.error
  const rawEvents = events.data?.data ?? []
  const model = !loading && !error ? buildExecutionDetail(rawEvents, artifacts.data?.data ?? []) : null

  return (
    <section>
      <Breadcrumb
        trail={[
          { label: name, to: `/accounts/${accountId}` },
          { label: '执行详情' },
        ]}
      />
      <div className="num mt-3 text-[15px] font-mono text-ink-2">{executionId}</div>
      {model && <Header m={model} currency={currency} assetLabel={assetTerms.shortLabel} />}

      {/* 运行中：顶部给一条确定态阶段条作一瞥总览；逐事件细节仍在下方脊柱。 */}
      {isLive && running && (
        <div className="mt-3 max-w-[760px]">
          <PhaseBar phase={running.phase} />
        </div>
      )}

      <Card className="mt-4 max-w-[760px] px-6 py-5">
        {loading && <SkeletonLines rows={5} />}
        {error && <p className="text-[14px] text-warn">加载失败：{error.message}</p>}
        {model && (
          <>
            <TargetChangeView m={model} />
            {model.symbols.length > 0 ? (
              <>
                <div className="mb-2 text-xs font-semibold tracking-wide text-ink-3">逐只结果</div>
                {model.symbols.map((s) => {
                  const symbolUnits = unitsForSymbol(units, s.symbol, currency)
                  return (
                    <SymbolChainRow
                      key={s.symbol}
                      s={s}
                      currency={currency}
                      units={symbolUnits}
                      lines={buildSymbolActionStream(rawEvents, s.symbol, {
                        quantityLabel: symbolUnits.quantity_label,
                        quantityMaxDecimals: symbolUnits.quantity_max_decimals,
                        priceLabel: symbolUnits.price_label || currency,
                      })}
                    />
                  )
                })}
              </>
            ) : (
              <p className="text-[13px] text-ink-3">本次执行无逐只对账（可能为空跑或早期终止）。</p>
            )}
            <Spine m={model} />
            <Evidence m={model} currency={currency} assetLabel={assetTerms.shortLabel} />
          </>
        )}
      </Card>
    </section>
  )
}
