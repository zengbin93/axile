import { useCallback, useState } from 'react'
import { useParams, useViewTransitionState } from 'react-router'
import { useNavigate } from '@/components/ui/nav'
import { Breadcrumb } from '@/components/ui/Breadcrumb'
import { Card, SectionLabel } from '@/components/ui/Card'
import { Skeleton } from '@/components/ui/Skeleton'
import { EquityChart, type ChartMarker } from '@/components/viz/EquityChart'
import { DailyBars } from '@/components/viz/DailyBars'
import { Segmented } from '@/components/ui/Segmented'
import {
  getAccount,
  getAccountActivity,
  getAccountAssetSnapshots,
  getCachedExecuteRecords,
  getPortfolioRecords,
} from '@/lib/api/accounts'
import { usePolling } from '@/lib/hooks/usePolling'
import { withViewTransition } from '@/lib/viewTransition'
import { accountAssetTerms, channelLabel } from '@/features/dashboard/display'
import { formatMoney } from '@/lib/derive'
import { displayCurrencyUnit } from '@/lib/format'
import {
  aggregateStats,
  buildDailyBars,
  buildEquityPoints,
  buildEvents,
  buildSegments,
  filterAssetSnapshots,
  filterRecords,
  filterScheduleSkips,
  type RangeKey,
} from '@/features/history/derive'

const RANGES: { value: RangeKey; label: string }[] = [
  { value: '30', label: '30 天' },
  { value: '90', label: '90 天' },
  { value: 'all', label: '全部' },
]

const VIEWS: { value: 'daily' | 'cumulative'; label: string }[] = [
  { value: 'daily', label: '每日' },
  { value: 'cumulative', label: '累计' },
]

const EVENT_TAG_CLASS: Record<string, string> = {
  create: 'text-ink-3 bg-fill',
  rebind: 'text-accent bg-accent-soft',
  // 失败=琥珀（红绿只留给行情涨跌，不表达成败）。
  fail: 'text-warn bg-warn-soft',
  skip: 'text-ink-3 bg-fill',
}

const EVENT_DOT_CLASS: Record<string, string> = {
  create: 'bg-border-strong',
  rebind: 'bg-accent',
  fail: 'bg-warn',
  skip: 'bg-border-strong',
}

/** 回看 / 绩效页 /accounts/:id/history。 */
export function AccountHistoryPage() {
  const { id } = useParams()
  const accountId = Number(id)
  const [range, setRange] = useState<RangeKey>('all')
  // 图区视角：累计估值线（默认，与总览 sparkline 同属线视角）/ 每日增量柱。
  const [view, setView] = useState<'daily' | 'cumulative'>('cumulative')
  // hover 命中的图内下标：scrub 时上抬为 hero 读数，图头保持权威读数位置。
  const [hoverIdx, setHoverIdx] = useState<number | null>(null)
  const navigate = useNavigate()

  /** 平滑滚动到账户时间线区块。 */
  const scrollToTimeline = () => document.getElementById('account-timeline')?.scrollIntoView({ behavior: 'smooth', block: 'start' })

  // 金额共享元素 FLIP（详情卡金额 → 本页 hero）；曲线不共享（root 淡入）。
  const amountVt = useViewTransitionState(`/accounts/${accountId}/history`)

  const account = usePolling(useCallback((s: AbortSignal) => getAccount(accountId, s), [accountId]), {
    queryKey: `account:${accountId}`,
    intervalMs: 0,
  })
  const assetTerms = accountAssetTerms(account.data?.trade_channel)
  const activity = usePolling(
    useCallback((s: AbortSignal) => getAccountActivity(accountId, { limit: 500 }, s), [accountId]),
    { queryKey: `account:${accountId}:activity:500`, intervalMs: 0 },
  )
  const bindings = usePolling(
    useCallback((s: AbortSignal) => getPortfolioRecords(accountId, s), [accountId]),
    { queryKey: `account:${accountId}:portfolio-records`, intervalMs: 0 },
  )
  const snapshots = usePolling(
    useCallback((s: AbortSignal) => getAccountAssetSnapshots(accountId, { limit: 500 }, s), [accountId]),
    { queryKey: `account:${accountId}:asset-snapshots:500`, intervalMs: 0 },
  )
  // 首帧优先用 hover 预取缓存：有缓存即直接出图，落地不闪骨架，金额 FLIP 有真实落点。
  const cached = getCachedExecuteRecords(accountId)
  const allRecords = activity.data
    ? activity.data.data.flatMap((item) => item.kind === 'execution' ? [item.record] : [])
    : cached?.data ?? []
  const recordsData = activity.data ?? cached ?? null
  const allSkips = activity.data?.data.flatMap((item) => item.kind === 'schedule_skip' ? [item] : []) ?? []
  const ranged = filterRecords(allRecords, range)
  const allSnapshots = snapshots.data?.data ?? []
  const rangedSnapshots = filterAssetSnapshots(allSnapshots, range)
  const rangedSkips = filterScheduleSkips(allSkips, allRecords, range)
  const points = buildEquityPoints(rangedSnapshots)
  const snapshotCurrency = [...rangedSnapshots].reverse().find((s) => s.assets.currency)?.assets.currency ?? ''
  const stats = aggregateStats(ranged, points, snapshotCurrency)
  const currencyUnit = displayCurrencyUnit(stats.currency)
  const segments = bindings.data ? buildSegments(bindings.data.data, points) : []
  const events = bindings.data ? buildEvents(bindings.data.data, ranged, rangedSkips) : []

  const sgn = (v: number) => (v >= 0 ? '+' : '−') + formatMoney(Math.abs(v))
  const ret = stats.pnl != null && stats.eqFirst ? (stats.pnl / stats.eqFirst) * 100 : null
  const feeDrag = stats.eqLast ? (stats.fee / stats.eqLast) * 100 : null

  // 疑似资金进出：有则「区间盈亏」降级为中性「估值变化」并在曲线做中性竖标；无则纯真盈亏。
  const hasTransfer = stats.transfers.length > 0
  const dailyBars = buildDailyBars(points, stats.transfers)
  const transferMarkers: ChartMarker[] = stats.transfers.map((t) => ({
    index: t.index,
    label: '疑似资金进出',
    color: 'var(--color-ink-3)',
  }))

  /**
   * hover 读数：把 scrub 命中的那个点/柱折算成「权益水平 + 盈亏 + 日期」，
   * 供 hero 顶替最新值显示（松开即回最新）。准星只吸附真实点，故读数永不插假值。
   */
  const readout = (() => {
    if (hoverIdx == null) return null
    if (view === 'cumulative') {
      const p = points[hoverIdx]
      if (!p) return null
      const pnl = stats.eqFirst != null ? p.eq - stats.eqFirst : null
      const pct = pnl != null && stats.eqFirst ? (pnl / stats.eqFirst) * 100 : null
      return { eq: p.eq, when: p.date, pnl, pct, label: '区间盈亏至此' }
    }
    const b = dailyBars[hoverIdx]
    if (!b) return null
    return { eq: b.endEq, when: b.day, pnl: b.delta, pct: null as number | null, label: '当日盈亏' }
  })()
  const reviewing = readout != null
  const heroEq = reviewing ? readout.eq : stats.eqLast

  /** 切换视角/区间时清掉旧 hover 下标（避免指向另一数组的错位点）。 */
  const switchView = (v: 'daily' | 'cumulative') => withViewTransition(() => {
    setHoverIdx(null)
    setView(v)
  })
  const switchRange = (v: RangeKey) => withViewTransition(() => {
    setHoverIdx(null)
    setRange(v)
  })

  return (
    <section>
      <div className="mb-3 flex items-center justify-between">
        <Breadcrumb
          trail={[
            { label: account.data?.name ?? `账户 #${accountId}`, to: `/accounts/${accountId}` },
            { label: '回看 · 绩效' },
          ]}
        />
        <Segmented size="sm" value={range} options={RANGES} onChange={switchRange} />
      </div>

      {(!recordsData || !snapshots.data) && (activity.loading || snapshots.loading) && (
        <>
          {/* 骨架与成品同尺寸：hero + 曲线 + 概览四卡，避免整屏塌成一行（L1 消闪）。 */}
          <Card className="p-6">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="mt-3 h-8 w-56" />
            <Skeleton className="mt-2 h-4 w-72" />
            <Skeleton className="mt-4 h-[180px] w-full" />
          </Card>
          <SectionLabel>概览</SectionLabel>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            {Array.from({ length: 4 }, (_, i) => (
              <Card key={i} className="px-4 py-4">
                <Skeleton className="h-3 w-16" />
                <Skeleton className="mt-2 h-6 w-20" />
                <Skeleton className="mt-2 h-3 w-24" />
              </Card>
            ))}
          </div>
        </>
      )}
      {(!recordsData || !snapshots.data) && (activity.error || snapshots.error) && (
        <p className="text-[14px] text-bad">
          加载失败：{activity.error?.message ?? snapshots.error?.message}
        </p>
      )}

      {recordsData && snapshots.data && (
        <>
          {/* Hero + 曲线 */}
          <Card className="p-6">
            <div className="flex flex-wrap items-baseline gap-3">
              <span className="text-[15px] font-[620]">{account.data?.name ?? `账户 #${accountId}`}</span>
              {account.data && (
                <span className="text-xs text-ink-3">{channelLabel(account.data.trade_channel, account.data.market)}</span>
              )}
            </div>
            <div
              // w-fit：金额盒贴文字宽（与卡片金额同形），FLIP 只剩上移平移 + 微缩，避免横向硬拉。
              className="num mt-1.5 w-fit text-[32px] font-[640] tracking-tight"
              style={amountVt ? { viewTransitionName: `equity-amount-${accountId}` } : undefined}
            >
              {heroEq != null ? formatMoney(heroEq) : '—'}
              <span className="ml-1.5 text-[15px] font-medium text-ink-3">{currencyUnit}</span>
              {reviewing && (
                // 明确「这是回看历史点、非实时」，避免 hero 跳动被误读为账户实变。
                <span className="ml-2 align-middle text-xs font-normal text-ink-3">· 回看 {readout.when}</span>
              )}
            </div>
            <div className="mt-1 text-[13.5px] text-ink-2">
              {reviewing ? (
                // scrub 读数：命中点的盈亏（累计=至此区间盈亏，每日=当日盈亏），红涨绿跌。
                <>
                  {readout.label}{' '}
                  <span className={`num ${readout.pnl == null ? 'text-ink-3' : readout.pnl >= 0 ? 'text-up' : 'text-down'}`}>
                    {readout.pnl == null ? '—' : sgn(readout.pnl)} {currencyUnit}
                    {readout.pct != null && `（${readout.pct >= 0 ? '+' : '−'}${Math.abs(readout.pct).toFixed(1)}%）`}
                  </span>
                </>
              ) : stats.pnl == null ? (
                `区间内${assetTerms.pointLabel}不足`
              ) : hasTransfer ? (
                // 有疑似资金进出：这是「估值变化」而非盈亏，走中性；免责升为琥珀提示。
                <>
                  区间估值变化{' '}
                  <span className="num text-ink-1">
                    {sgn(stats.pnl)} {currencyUnit}
                  </span>
                  <span className="text-warn"> · 含疑似资金进出 {stats.transfers.length} 笔（见图标注）</span>
                </>
              ) : (
                // 无资金进出：等同真盈亏，走红绿，不再常驻免责。
                <>
                  区间盈亏{' '}
                  <span className={`num ${stats.pnl >= 0 ? 'text-up' : 'text-down'}`}>
                    {sgn(stats.pnl)} {currencyUnit}
                    {ret != null && `（${ret >= 0 ? '+' : '−'}${Math.abs(ret).toFixed(1)}%）`}
                  </span>
                </>
              )}
            </div>
            {/* 曲线不挂共享名（禁止小图/线柱内容 morph）：大图随 root 淡入；只金额做 FLIP。 */}
            <div className="mt-4">
              <div className="mb-1.5 flex items-center justify-between">
                <span className="text-xs text-ink-3">{view === 'daily' ? '每日盈亏' : '累计估值'}</span>
                <Segmented size="sm" value={view} options={VIEWS} onChange={switchView} />
              </div>
              {/*
                页内每日↔累计是内容真换：锚点（Segmented）钉死，图区靠 withViewTransition +
                槽位替换，不挂 viewTransitionName（避免线↔柱内容 morph）。
              */}
              <div>
                {view === 'daily' ? (
                  <DailyBars bars={dailyBars} hoverIndex={hoverIdx} onHover={setHoverIdx} />
                ) : (
                  <EquityChart points={points} markers={transferMarkers} hoverIndex={hoverIdx} onHover={setHoverIdx} />
                )}
              </div>
            </div>
          </Card>

          {/* 统计卡 */}
          <SectionLabel>概览</SectionLabel>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <StatCard
              k={hasTransfer ? '区间估值变化' : '区间盈亏'}
              v={stats.pnl != null ? `${sgn(stats.pnl)}` : '—'}
              vClass={stats.pnl == null || hasTransfer ? '' : stats.pnl >= 0 ? 'text-up' : 'text-down'}
              sub={hasTransfer ? `${currencyUnit} · 含资金进出` : `${currencyUnit} · 真盈亏`}
              subWarn={hasTransfer}
            />
            <StatCard
              k="累计手续费"
              v={stats.fee > 0 ? stats.fee.toFixed(4) : '0'}
              sub={feeDrag != null ? `${assetTerms.ratioLabel} ${feeDrag.toFixed(2)}%` : currencyUnit}
              subWarn={feeDrag != null && feeDrag > 0}
            />
            <StatCard
              k="执行"
              v={`${stats.fills}`}
              vUnit="成交"
              sub={`空跑 ${stats.noops} · 跳过 ${rangedSkips.length} · 失败 ${stats.fails}${stats.terminated > 0 ? ` · 终止 ${stats.terminated}` : ''}`}
            />
            <StatCard
              k="失败"
              v={`${stats.fails}`}
              vUnit="次"
              sub={stats.fails > 0 ? '见时间线 ↓' : '无异常'}
              subWarn={stats.fails > 0}
              onSub={stats.fails > 0 ? scrollToTimeline : undefined}
            />
          </div>

          {/* 分段收益 */}
          <SectionLabel>绑定分段收益 · {assetTerms.shortLabel}跨多段绑定，分开算才诚实</SectionLabel>
          <Card className="px-6 py-4">
            {!bindings.data && bindings.loading ? (
              <><Skeleton className="h-4 w-44" /><Skeleton className="mt-3 h-4 w-56" /></>
            ) : bindings.error ? (
              <p className="text-[13px] text-warn">绑定记录暂不可用：{bindings.error.message} <button className="font-semibold underline" onClick={() => void bindings.refresh()}>重试</button></p>
            ) : segments.length === 0 ? (
              <p className="text-[13px] text-ink-3">本区间无可用的分段数据。</p>
            ) : (
              segments.map((s, i) => (
                <div key={i} className="flex items-center gap-3 border-t border-line py-3 text-[14px] first:border-t-0">
                  <div className="flex-1 min-w-0">
                    <div className="font-semibold">{s.portfolioId != null ? `组合 #${s.portfolioId}` : '未绑定'}</div>
                    <div className="text-xs text-ink-3">自 {s.start}</div>
                  </div>
                  <div className={`num w-24 flex-none text-right font-semibold ${s.pnl == null ? 'text-ink-3' : s.pnl >= 0 ? 'text-up' : 'text-down'}`}>
                    {s.pnl == null ? '—' : `${sgn(s.pnl)}`}
                  </div>
                </div>
              ))
            )}
          </Card>

          {/* 账户时间线（账户级动态；失败行可下钻到执行级事件详情） */}
          <div id="account-timeline" className="scroll-mt-4">
          <SectionLabel>账户时间线 · 你不在时发生了什么</SectionLabel>
          <Card className="px-6 py-4">
            {!bindings.data && bindings.loading ? (
              <><Skeleton className="h-4 w-full" /><Skeleton className="mt-3 h-4 w-4/5" /><Skeleton className="mt-3 h-4 w-3/5" /></>
            ) : bindings.error ? (
              <p className="text-[13px] text-warn">绑定时间线暂不可用：{bindings.error.message} <button className="font-semibold underline" onClick={() => void bindings.refresh()}>重试</button></p>
            ) : events.length === 0 ? (
              <p className="text-[13px] text-ink-3">本区间无异常事件。</p>
            ) : (
              <div className="relative pl-[22px]">
                <div className="absolute left-1.5 top-1.5 bottom-1.5 w-0.5 bg-line" />
                {events.map((e, i) => {
                  const clickable = e.kind === 'fail' && Boolean(e.executionId)
                  return (
                    <div
                      key={i}
                      className={`group relative -mx-2 flex items-baseline gap-3 rounded px-2 py-2.5 ${
                        clickable ? 'cursor-pointer hover:bg-bg-subtle' : ''
                      }`}
                      onClick={
                        clickable
                          ? () => navigate(`/accounts/${accountId}/executions/${e.executionId}`)
                          : undefined
                      }
                    >
                      <span className={`absolute -left-[17px] top-[15px] h-[9px] w-[9px] rounded-full border-2 border-surface ${EVENT_DOT_CLASS[e.kind]}`} />
                      <span className="w-24 flex-none text-xs text-ink-3">{e.date}</span>
                      <span className="min-w-0 flex-1 text-[14px]">
                        <span className={`mr-1.5 rounded px-1.5 py-px text-[11px] font-semibold ${EVENT_TAG_CLASS[e.kind]}`}>{e.tag}</span>
                        {e.text}
                      </span>
                      {clickable && (
                        <span className="flex-none text-sm text-accent opacity-0 transition-opacity group-hover:opacity-100">→</span>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </Card>
          </div>
        </>
      )}
    </section>
  )
}

function StatCard({
  k,
  v,
  vUnit,
  vClass = '',
  sub,
  subWarn,
  onSub,
}: {
  k: string
  v: string
  vUnit?: string
  vClass?: string
  sub: string
  subWarn?: boolean
  onSub?: () => void
}) {
  const subCls = `mt-0.5 text-xs ${subWarn ? 'text-warn' : 'text-ink-3'}`
  return (
    <Card className="px-4 py-4">
      <div className="text-xs text-ink-3">{k}</div>
      <div className={`num mt-0.5 text-[20px] font-[640] ${vClass}`}>
        {v}
        {vUnit && <span className="ml-1 text-[13px] font-normal text-ink-3">{vUnit}</span>}
      </div>
      {onSub ? (
        <button className={`${subCls} cursor-pointer border-0 bg-transparent p-0 hover:underline`} onClick={onSub}>
          {sub}
        </button>
      ) : (
        <div className={subCls}>{sub}</div>
      )}
    </Card>
  )
}
