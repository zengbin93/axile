import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react'
import { useViewTransitionState } from 'react-router'
import { RefreshCw } from 'lucide-react'
import { Link, useNavigate } from '@/components/ui/nav'
import { Card, Chip } from '@/components/ui/Card'
import { DriftBar } from '@/components/viz/DriftBar'
import { Sparkline } from '@/components/viz/Sparkline'
import { InkRewrite } from '@/components/ui/InkRewrite'
import { NumberTicker } from '@/components/ui/NumberTicker'
import { OverflowText } from '@/components/ui/OverflowText'
import { Tooltip } from '@/components/ui/Tooltip'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { Skeleton, SkeletonGroup, SkeletonText } from '@/components/ui/Skeleton'
import { AccountActions } from '@/features/account/AccountActions'
import { useExecutionRunner } from '@/features/account/useExecutionRunner'
import { useTerminateAction } from '@/features/account/useTerminateAction'
import { buildRecentActivity, recentRowText } from '@/features/account/recent'
import { StaleDataStatus } from '@/features/account/StaleDataStatus'
import { connectionStaleAt, localQueryError } from '@/features/account/staleData'
import {
  currentHoldingPreview,
  formatHoldingQuantity,
  rebalanceTurnover,
  type CurrentHoldingPreview,
} from '@/features/account/holdingPreview'
import { ScheduleSummary, ScheduleTimeline, ScheduleTimelineSkeleton } from '@/features/account/ScheduleTimeline'
import { accountAssetTerms, INTEGRITY_ICON, INTEGRITY_TEXT_CLASS, STATUS_TEXT_CLASS, channelLabel } from '@/features/dashboard/display'
import { isExecutingStatus, phaseLabel, runVerb } from '@/features/dashboard/execProgress'
import { executionJustSettled, useRunning } from '@/stores/liveExec'
import { useDomainStore } from '@/stores/domain'
import { algorithmRefOf, describeAlgorithmRef } from '@/features/setup/algorithms'
import {
  accountConfigVtName,
  describeLeverage,
  describeSymbolControl,
  readAccountConfigSummary,
  writeAccountConfigSummary,
} from '@/features/account/configSummary'
import {
  getAccount,
  getAccountAssetSnapshots,
  getAccountActivity,
  getAccountTargetSnapshot,
  getNextRun,
  prefetchExecuteRecords,
  refreshAccountAssets,
  refreshAccountTargetSnapshot,
  updateAccount,
  deleteAccount,
} from '@/lib/api/accounts'
import { usePolling } from '@/lib/hooks/usePolling'
import { useTargetSnapshot } from '@/lib/hooks/useTargetSnapshot'
import { stateVerdict, gateOf, observedTotalAsset, rebalancePlan, positionsOf, positionsOfAssets, type StatusLevel } from '@/lib/derive'
import { shortErrorReason } from '@/lib/errorInfo'
import { displayCurrencyUnit, fmtMoney, withCurrency } from '@/lib/format'
import { describeCron } from '@/features/setup/cron'
import { TimerQuickModal } from '@/features/setup/TimerQuickModal'
import { useToastStore } from '@/stores/ui'
import { useChannelDescriptor } from '@/stores/channels'
import type { AccountDashboardItem } from '@/types/api'
import { TargetSnapshotControl } from '@/features/portfolio/TargetSnapshotControl'

interface AccountDetailProps {
  accountId: number
  /** 若来自仪表盘可直接传入聚合项，省一次请求；否则组件自取。 */
  item: AccountDashboardItem
  /** 顶栏已确认网络级失联；详情页据此收起重复的缓存刷新错误。 */
  connectionUnavailable?: boolean
  /** 仪表盘数据刷新回调（执行/启停后触发）。 */
  onDashboardRefresh?: () => void
}

export function AccountDetail({
  accountId,
  item,
  connectionUnavailable = false,
  onDashboardRefresh,
}: AccountDetailProps) {
  const navigate = useNavigate()
  const toast = useToastStore((s) => s.toast)
  const [timerOpen, setTimerOpen] = useState(false)
  const [refreshingAssets, setRefreshingAssets] = useState(false)
  // 启停乐观态：确认后立刻翻转，驱动按钮/状态句日记式换字；与 item 对齐后清除。
  const [startedOverride, setStartedOverride] = useState<boolean | null>(null)
  // 共享元素 FLIP 门控：
  // - 账户名：进详情（舰队/组合）或去编辑页时挂名；持仓/回看不飞名。
  // - 金额：仅「去回看」；曲线不共享（禁止小图 5× 内容 morph）。
  const tDetail = useViewTransitionState(`/accounts/${accountId}`)
  const tEdit = useViewTransitionState(`/accounts/${accountId}/edit`)
  const tHistory = useViewTransitionState(`/accounts/${accountId}/history`)
  const nameVt = tDetail || tEdit
  const amountVt = tHistory
  const assetTerms = accountAssetTerms(item.trade_channel)
  const channelDescriptor = useChannelDescriptor(item.trade_channel)
  const channelSchedule = channelDescriptor?.schedule
  const scheduleKind = channelSchedule?.kind
  // 组合名：领域 store 已在应用根加载（PortfolioLite 带 name），取名不增请求；未加载/找不到退回 #id。
  const portfolios = useDomainStore((s) => s.portfolios)

  const isStarted = startedOverride ?? item.is_started
  useEffect(() => {
    if (startedOverride != null && item.is_started === startedOverride) {
      setStartedOverride(null)
    }
  }, [item.is_started, startedOverride])

  const account = usePolling(useCallback((s: AbortSignal) => getAccount(accountId, s), [accountId]), {
    queryKey: `account:${accountId}`,
    intervalMs: 15000,
  })
  const RECENT_LIMIT = 50
  const activity = usePolling(
    useCallback((s: AbortSignal) => getAccountActivity(accountId, { limit: RECENT_LIMIT }, s), [accountId]),
    { queryKey: `account:${accountId}:activity:${RECENT_LIMIT}`, intervalMs: 10000 },
  )
  const nextRun = usePolling(useCallback((s: AbortSignal) => getNextRun(accountId, s), [accountId]), {
    queryKey: `account:${accountId}:next-run`,
    intervalMs: 30000,
  })
  const assetSnapshots = usePolling(
    useCallback((s: AbortSignal) => getAccountAssetSnapshots(accountId, { limit: 1 }, s), [accountId]),
    { queryKey: `account:${accountId}:asset-snapshots:1`, intervalMs: 10000 },
  )

  const portfolioId = account.data?.portfolio_id ?? item.portfolio_id ?? null
  // 目标改取账户级「执行器口径」权重（后端已叠加杠杆与精度），与含杠杆的真实持仓同尺。
  const weights = useTargetSnapshot(
    useCallback((s: AbortSignal) => getAccountTargetSnapshot(accountId, s), [accountId]),
    useCallback(() => refreshAccountTargetSnapshot(accountId), [accountId]),
    `account:${accountId}:target-snapshot`,
  )

  const accountFreshness = { error: account.error, stale: account.stale, updatedAt: account.updatedAt }
  const activityFreshness = { error: activity.error, stale: activity.stale, updatedAt: activity.updatedAt }
  const nextRunFreshness = { error: nextRun.error, stale: nextRun.stale, updatedAt: nextRun.updatedAt }
  const assetFreshness = {
    error: assetSnapshots.error,
    stale: assetSnapshots.stale,
    updatedAt: assetSnapshots.updatedAt,
  }
  const targetFreshness = { error: weights.error, stale: weights.stale, updatedAt: weights.updatedAt }
  const automaticStaleAt = connectionStaleAt(connectionUnavailable, [accountFreshness, nextRunFreshness])
  const activityStaleAt = connectionStaleAt(connectionUnavailable, [activityFreshness])
  const comparisonStaleAt = connectionStaleAt(connectionUnavailable, [assetFreshness, targetFreshness])

  const reloadTargetSnapshot = weights.reloadSnapshot
  const refreshAccount = account.refresh
  const refreshActivity = activity.refresh
  const refreshNextRun = nextRun.refresh
  const refreshAssetSnapshots = assetSnapshots.refresh
  // 执行终态时记录与资产快照已落库：立刻重读观测面，避免目标单飞、权益/持仓停在上一帧。
  const refreshObservedState = useCallback(() => {
    refreshActivity()
    void reloadTargetSnapshot()
    void refreshAssetSnapshots()
    onDashboardRefresh?.()
  }, [refreshActivity, reloadTargetSnapshot, refreshAssetSnapshots, onDashboardRefresh])
  const runner = useExecutionRunner(accountId, refreshObservedState)
  // 服务端真源的在途执行（SSE/轮询汇入 liveExec store）：任何来源发起的执行都可见。
  const live = useRunning(accountId)
  const previousLiveRef = useRef(live)
  useEffect(() => {
    if (executionJustSettled(previousLiveRef.current, live)) refreshObservedState()
    previousLiveRef.current = live
  }, [live, refreshObservedState])
  // 顶栏的单次重试恢复连接后，立即同步详情页查询，不再等待各自的轮询间隔。
  const connectionUnavailableRef = useRef(connectionUnavailable)
  useEffect(() => {
    const restored = connectionUnavailableRef.current && !connectionUnavailable
    connectionUnavailableRef.current = connectionUnavailable
    if (!restored) return
    void Promise.all([
      refreshAccount(),
      refreshActivity(),
      refreshNextRun(),
      refreshAssetSnapshots(),
      reloadTargetSnapshot(),
    ])
  }, [
    connectionUnavailable,
    refreshAccount,
    refreshActivity,
    refreshNextRun,
    refreshAssetSnapshots,
    reloadTargetSnapshot,
  ])
  // 当前在途执行 id：优先服务端真源，退回本地 runner（首帧前）。用于「一行可点跳详情」。
  const runningExecId = live?.executionId ?? runner.executionId

  const recordList = activity.data?.data.flatMap((item) => item.kind === 'execution' ? [item.record] : []) ?? []
  const latestAssets = assetSnapshots.data?.data[0]?.assets
  const snapshotPositions = positionsOfAssets(latestAssets)
  const positions = latestAssets ? snapshotPositions : positionsOf(recordList)
  const equity = observedTotalAsset(latestAssets, item.total_asset)
  const holdingsCount = latestAssets ? snapshotPositions.length : item.holdings_count
  const target = weights.data?.weights ?? {}
  const positionsLoading = latestAssets === undefined && activity.data === null
    && (assetSnapshots.loading || activity.loading)
  const positionsError = latestAssets === undefined && activity.data === null && !positionsLoading
    ? (assetSnapshots.error ?? activity.error)
    : null
  const comparisonLoading = (weights.data === null && weights.loading) || positionsLoading
  const comparisonError = weights.data === null ? (weights.error ?? positionsError) : positionsError
  const comparisonReady = weights.data?.calculated_at != null && !positionsLoading && !positionsError
  // 背离摘要：与明细抽屉同口径（均出自 rebalancePlan）。文案讲「几只要动 · 卖几买几」，
  // 条画各品种的要成交幅度；到位/空仓退成静态一句。
  const quantities = weights.data?.quantities ?? null
  const plan = rebalancePlan(positions, target, equity, quantities)
  const driftLevel: StatusLevel = plan.off > 0 ? 'warn' : 'ok'
  const driftHeadline =
    plan.rows.length === 0
      ? '空仓 · 与目标一致'
      : plan.off === 0
        ? '已调仓到位'
        : `${plan.off} 只待调整`
  const targetCount = Object.values(target).filter((weight) => Math.abs(weight) > 1e-9).length
  const turnover = rebalanceTurnover(plan)
  const currentHoldings = currentHoldingPreview(positions, equity)
  // 有服务端 quantities 时现场计划即在位性；否则不拿权重尺子盖掉仪表盘 off_symbol_count。
  const state = stateVerdict({
    ...item,
    is_started: isStarted,
    off_symbol_count: comparisonReady && quantities != null ? plan.off : item.off_symbol_count,
  })
  const gate = gateOf({ ...item, is_started: isStarted })
  // 执行态：服务端 live 优先，runner 仅首帧前乐观。queued ≠ 正在下单。
  const isBusy = !!(live || runner.running)
  const isExecuting = live != null && isExecutingStatus(live.status)
  const isQueued = isBusy && !isExecuting
  // 终止动作 + 防连点：点后乐观进「终止中…」并禁用按钮，执行离开运行态即复位。
  const { terminating, terminate } = useTerminateAction(accountId, isBusy, activity.refresh)
  const runKind = live?.kind ?? (runner.kind === 'clear' ? 'clear' : 'rebalance')
  const statusHeadline = isExecuting
    ? `正在${runVerb(runKind)}`
    : isQueued
      ? '等待执行'
      : `${INTEGRITY_ICON[state.integrity]} ${state.text}`
  // 「需要看看」兑现：空闲且上次失败时，状态行点进最近失败执行详情（与近期失败行同构）。
  const lastFailExecId =
    !isBusy && state.integrity === 'off' && item.last_output_status !== 'BLOCKED'
      ? (recordList.find((r) => r.raw_result?.status !== 'BLOCKED' && r.is_success !== 1 && r.execution_id)?.execution_id ?? null)
      : null
  const statusNavId = runningExecId ?? lastFailExecId
  const goStatusNav = statusNavId
    ? () => navigate(`/accounts/${accountId}/executions/${statusNavId}`)
    : undefined

  // 定时节奏：把存储的 crontab 反解成设置向导同款人话（命中预设时如「每 15 分钟 · 补发 2 次」）；
  // 命不中则退为「自定义执行节奏」。未来时刻统一使用服务端 APScheduler 真源，不在此处近似推算。
  const cronExpr = account.data?.cron_expr ?? ''
  const cronHuman = cronExpr && scheduleKind ? describeCron(scheduleKind, cronExpr, channelSchedule?.night) : null

  // Hero 配置带（杠杆 / 品种控制 / 算法）：取自本组件已在轮询的账户详情，零新增请求。
  // 配置事实而非盈亏或偏离：中性色、零动效；每项兼作对应编辑分区的入口。
  // 值文本与编辑分区页「当前配置」摘要是同一句话的两个落点：去往/离开该分区时挂
  // 共享名做平移 + 微缩（身份对 + 几何真变）；模块级摘要缓存保证两端首帧都有落点。
  const acc = account.data
  const tEditLeverage = useViewTransitionState(`/accounts/${accountId}/edit/leverage`)
  const tEditSymbols = useViewTransitionState(`/accounts/${accountId}/edit/symbols`)
  const tEditAlgorithm = useViewTransitionState(`/accounts/${accountId}/edit/algorithm`)
  const showShortLeverage = channelDescriptor?.ui.show_short_leverage ?? true
  // 真源到位即写缓存：编辑页首帧同步读出，FLIP 落点不断档。
  useEffect(() => {
    if (acc) writeAccountConfigSummary(accountId, acc, { showShortLeverage })
  }, [acc, accountId, showShortLeverage])
  const cachedConfig = acc ? null : readAccountConfigSummary(accountId)
  /** 配置带常挂：详情未加载且缓存未命中时值位骨架占位（null）。 */
  const configLoading = acc == null && account.loading && cachedConfig == null
  const portfolioName =
    portfolioId != null ? (portfolios?.find((p) => p.id === portfolioId)?.name ?? null) : null
  const leverageText = acc
    ? describeLeverage(acc.long_leverage, acc.short_leverage, showShortLeverage)
    : (cachedConfig?.leverage ?? null)
  const symbolsText = acc
    ? describeSymbolControl(acc.forbidden_symbols, acc.risk_symbols)
    : (cachedConfig?.symbols ?? null)
  // 算法摘要不收短：TARGET-POS-TASK 等直接给完整参数句，配置带里整项分组 + 截断兜底。
  const algorithmText = acc
    ? describeAlgorithmRef(algorithmRefOf(acc.algorithm))
    : (cachedConfig?.algorithm ?? null)
  const onToggleStarted = async () => {
    const next = !isStarted
    setStartedOverride(next)
    try {
      await updateAccount(accountId, { is_started: next })
      toast(next ? '已启动自动执行' : '已暂停自动执行')
      account.refresh()
      nextRun.refresh()
      onDashboardRefresh?.()
    } catch (e) {
      setStartedOverride(null)
      toast(shortErrorReason(e))
    }
  }
  const onDelete = async () => {
    try {
      await deleteAccount(accountId)
      toast('账户已删除')
      onDashboardRefresh?.()
      navigate('/')
    } catch (e) {
      toast(shortErrorReason(e))
    }
  }
  const onRefreshAssets = async () => {
    if (refreshingAssets || isExecuting) return
    setRefreshingAssets(true)
    try {
      await refreshAccountAssets(accountId)
      await Promise.all([assetSnapshots.refresh(), onDashboardRefresh?.()])
      toast('账户权益已刷新')
    } catch (e) {
      toast(shortErrorReason(e))
    } finally {
      setRefreshingAssets(false)
    }
  }

  // 「今日」涨跌用服务端按自然日锚定的 today_pct（昨收/今开为基准），不再前端取序列末两点相减。
  const pct = item.today_pct ?? null
  // 兼容尚未重启、dashboard 暂未携带 remark 的开发服务；详情到位后仍能展示已保存备注。
  const remark = account.data?.remark ?? item.remark

  return (
    <section>
      {/* Hero */}
      <Card className="p-6">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex flex-none items-center gap-3">
            {/* 与舰队卡 / 组合行 / 编辑页标题名配对做共享元素 FLIP（平移 + 微缩）。 */}
            <span
              className="text-[16px] font-[620]"
              style={nameVt ? { viewTransitionName: `account-name-${accountId}` } : undefined}
            >
              {item.name}
            </span>
            {/* 渠道徽章与账户名同一逻辑单元：随名字同门控挂名、同轨飞行（nameVt）。 */}
            <Chip style={nameVt ? { viewTransitionName: `account-channel-${accountId}` } : undefined}>
              {channelLabel(item.trade_channel, item.market)}
            </Chip>
            {gate.gate === 'paused' && <Chip>{gate.label}</Chip>}
          </div>
          {remark && (
            <OverflowText
              className="order-last basis-full text-[13px] leading-5 text-ink-3 xl:order-none xl:min-w-0 xl:max-w-[520px] xl:flex-1 xl:basis-auto"
              text={remark}
            />
          )}
          <AccountActions
            name={item.name}
            isStarted={isStarted}
            running={isBusy}
            executing={isExecuting}
            terminating={terminating}
            onExec={() => runner.start('exec')}
            onClear={() => runner.start('clear')}
            onTerminate={terminate}
            onToggleStarted={onToggleStarted}
            onEdit={() => navigate(`/accounts/${accountId}/edit`)}
            onDelete={onDelete}
          />
        </div>

        {/*
         * 状态区固定为「标题行 + 副行」两行结构，高度不随运行态增减（框不动，戏在框里演）。
         * 主句常驻 InkRewrite prose：暂停↔执行、执行↔清仓、启停空闲句均墨褪再显。
         * 执行中：生命体征 + phase 副标事件门控，不叠日记（phase 连刷勿糊墨）。
         * 可点：在途 → 当前执行；「需要看看」→ 最近失败执行。外层始终 div，避免 Link remount 打断换字。
         */}
        <div
          className={`relative mt-[18px] inline-flex min-w-0 items-center gap-2 text-[23px] font-[640] tracking-tight transition-[padding-left] duration-[440ms] ease-[cubic-bezier(.4,0,.2,1)] motion-reduce:transition-none ${
            isBusy ? 'pl-[18px]' : 'pl-0'
          } ${isBusy ? 'text-accent' : INTEGRITY_TEXT_CLASS[state.integrity]}${
            statusNavId ? ' cursor-pointer hover:opacity-80' : ''
          }`}
          role={statusNavId ? 'link' : undefined}
          tabIndex={statusNavId ? 0 : undefined}
          title={lastFailExecId ? '查看失败执行详情' : undefined}
          onClick={goStatusNav}
          onKeyDown={
            goStatusNav
              ? (e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    goStatusNav()
                  }
                }
              : undefined
          }
        >
          {/* 圆点绝对定位、落进 padding-left 腾出的 18px 里：进执行时靠容器 padding 过渡把正文
              「温和推开」而非被撞开；圆点自身不占 flow、不推挤。my-auto 竖直居中（走 margin，
              不占 transform，避让 exec-breathe 的 scale）。 */}
          {isBusy && (
            <span className="exec-dot absolute left-0 top-0 bottom-0 my-auto h-2.5 w-2.5" aria-hidden />
          )}
          {/*
           * exec-flow 必须挂在真正有文字节点的层（textClassName），不能套在槽外：
           * background-clip:text + 透明字色只对「本元素自己的字」生效，套父级会让字消失。
           * 颜色也随 textClassName 按层快照（墨随句走）：旧句以旧色褪——琥珀告警句
           * 退场途中不会被瞬时染蓝；父级色只供箭头/相位副标等当前态元素。
           */}
          <InkRewrite
            text={statusHeadline}
            tone="prose"
            fluid
            className="min-w-0"
            textClassName={isExecuting ? 'text-accent exec-flow' : isBusy ? 'text-accent' : INTEGRITY_TEXT_CLASS[state.integrity]}
          />
          {/* 相位副标：外壳 phase-grow 让入场 footprint 宽度 0→内容（grid-fr，箭头随 reflow 挪、
              进执行那刻不被瞬时占位顶跳）；内层 phase-enter 管 opacity 淡入。相位词逐步推进走
              label 档日记换字（触发→冻结输入→算目标→下单→对账），宽变由内层 InkRewrite fluid 自理。
              首帧不播、纯 opacity 无 blur，不与主句流光抢；「·」静态钉住只重写相位词。 */}
          {isExecuting && (
            <span className="phase-grow">
              <span className="phase-enter inline-flex min-w-0 items-center gap-1 overflow-hidden whitespace-nowrap text-[15px] font-medium text-ink-2">
                <span aria-hidden>·</span>
                <InkRewrite text={phaseLabel(live?.phase)} tone="label" fluid />
              </span>
            </span>
          )}
          {isExecuting && live?.pendingExecutionId ? (
            <span className="text-[15px] font-medium text-ink-2">· 结束后再调一次</span>
          ) : null}
          {/* 可点暗示：执行中用生命体征箭头；失败「需要看看」用静止 →，色随父级琥珀。
              箭头纯 inline、只跟随 reflow（不再挂 transform-FLIP）：上游全走 CSS 布局过渡
              （槽宽 + 圆点 padding），箭头随之连续挪——单一范式，无采样、无自激。
              exec-arrow 自体漂移只在 running 时挂在此层。 */}
          {statusNavId && (
            <span
              className={`inline-block text-[15px] font-medium ${isExecuting ? 'exec-arrow' : ''}`}
              aria-hidden
            >
              →
            </span>
          )}
        </div>
        <ScheduleSummary
          lastExecutedAt={item.last_exec_at}
          nextRunAt={nextRun.data?.next_execution_times[0] ?? null}
        />

        <div className="mt-6 border-t border-line pt-4">
          <div className="flex items-center gap-1.5 text-[13px] text-ink-2">
            <span>{assetTerms.fullLabel}</span>
            <Tooltip content={isExecuting ? '执行中，结束后可刷新账户权益' : '从交易渠道刷新账户权益'}>
              <span className="inline-flex">
                <button
                  type="button"
                  onClick={onRefreshAssets}
                  disabled={isExecuting || refreshingAssets}
                  aria-label={refreshingAssets ? '正在刷新账户权益' : '刷新账户权益'}
                  title={isExecuting ? '执行中，无法刷新账户权益' : undefined}
                  className="grid h-6 w-6 cursor-pointer place-items-center rounded-md text-ink-3 hover:bg-fill hover:text-ink-1 disabled:cursor-default disabled:opacity-40 disabled:hover:bg-transparent"
                >
                  <RefreshCw
                    size={14}
                    className={refreshingAssets ? 'animate-spin motion-reduce:animate-none' : undefined}
                  />
                </button>
              </span>
            </Tooltip>
          </div>
          <div className="flex items-end justify-between gap-4">
            <div>
              {/* 金额 → 绩效 hero：共享元素 FLIP（平移 + 微缩）；曲线不参与。 */}
              <div
                className="num mt-0.5 text-[34px] font-[640] tracking-tight"
                style={amountVt ? { viewTransitionName: `equity-amount-${accountId}` } : undefined}
              >
                <NumberTicker value={equity} format={{ minimumFractionDigits: 2, maximumFractionDigits: 2 }} />
                <span className="ml-1.5 text-[16px] font-medium text-ink-3">{displayCurrencyUnit(item.currency)}</span>
              </div>
              <div className="mt-1.5 text-[13.5px] text-ink-2">
                {pct != null && (
                  <span className={`num ${pct > 0 ? 'text-up' : pct < 0 ? 'text-down' : 'text-ink-2'}`}>
                    今日 {pct >= 0 ? '+' : '−'}
                    <NumberTicker value={Math.abs(pct)} format={{ minimumFractionDigits: 2, maximumFractionDigits: 2 }} suffix="%" />
                  </span>
                )}
                {portfolioId != null && (
                  <>
                    {' · 组合 '}
                    {/* 组合名是自由文本、长度无界：槽位截断 + hover 原地播全名（OverflowText 既有模式）。 */}
                    <Link
                      to={`/portfolios/${portfolioId}`}
                      className="inline-flex min-w-0 max-w-60 align-middle font-semibold text-accent hover:underline"
                    >
                      <OverflowText className="min-w-0" text={portfolioName ?? `#${portfolioId}`} />
                    </Link>
                  </>
                )}
              </div>
            </div>
            {/*
              权益走势迷你线即入口：点击跳「回看 · 绩效」。曲线不挂共享名（禁止小图→大图内容
              morph）；连续叙事只落在金额 FLIP。affordance 走安静瓷砖（hover 提亮，不叠字）；
              发现性由 title 与页内「完整回看 / 绩效 →」兜底。
            */}
            <Link
              to={`/accounts/${accountId}/history`}
              aria-label="查看回看 · 绩效"
              title="回看 · 绩效"
              // hover/聚焦预取绩效全量记录：首帧有数据、不闪骨架，金额 FLIP 有真实落点。
              onPointerEnter={() => prefetchExecuteRecords(accountId)}
              onFocus={() => prefetchExecuteRecords(accountId)}
              className="group -m-2 block cursor-pointer p-2"
            >
              {/* 静止略暗、hover 提亮；只动亮度，不改色相。 */}
              <span className="inline-block opacity-70 transition-opacity duration-150 group-hover:opacity-100">
                <Sparkline data={item.equity_series} width={150} height={46} />
              </span>
            </Link>
          </div>
        </div>

        {/*
         * 配置带：hero 最后一层（名称 → 状态 → 资产 → 配置），label 领值的「· 外分组」
         * 形态——每项是独立 inline 单元，折行只发生在项间，算法参数句内部的「·」不再
         * 与分段符糊成一片。带常挂（缓存/骨架占位），卡高不随账户详情到位而长个。
         * 算法项吃剩余宽、OverflowText 截断 + hover 播全句；整项可点跳编辑分区。
         * 值文本挂共享名：与目标编辑页的「当前配置」摘要值配对 FLIP（各自门控）。
         */}
        <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-1.5 border-t border-line pt-3.5 text-[13px]">
          <HeroConfigItem
            label="杠杆"
            to={`/accounts/${accountId}/edit/leverage`}
            title="杠杆设置"
            value={configLoading ? null : (leverageText ?? '—')}
            vtName={tEditLeverage ? accountConfigVtName(accountId, 'leverage') : undefined}
          />
          <HeroConfigItem
            label="品种"
            to={`/accounts/${accountId}/edit/symbols`}
            title="品种控制"
            value={configLoading ? null : (symbolsText ?? '—')}
            vtName={tEditSymbols ? accountConfigVtName(accountId, 'symbols') : undefined}
          />
          <HeroConfigItem
            label="算法"
            to={`/accounts/${accountId}/edit/algorithm`}
            title="执行算法"
            value={configLoading ? null : (algorithmText ?? '—')}
            grow
            vtName={tEditAlgorithm ? accountConfigVtName(accountId, 'algorithm') : undefined}
          />
        </div>
      </Card>

      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
        <Card className="px-6 py-4 md:col-span-2">
          <div className="mb-3 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5">
            <h3 className="mr-auto text-[13px] font-semibold text-ink-2">持仓 vs 目标</h3>
            <StaleDataStatus updatedAt={comparisonStaleAt} />
            <TargetSnapshotControl
              snapshot={weights.data}
              loading={weights.loading}
              recalculating={weights.recalculating}
              error={weights.recalculateError}
              disabled={isExecuting || portfolioId == null}
              disabledReason={isExecuting ? '账户正在执行，结束后可重新计算' : portfolioId == null ? '账户未绑定组合' : undefined}
              variant="compact"
              onRecalculate={() => void weights.recalculate()}
            />
            <Link
              to={`/accounts/${accountId}/holdings`}
              className="flex-none text-[12.5px] font-semibold text-accent hover:underline"
            >
              持仓明细 →
            </Link>
          </div>
          {comparisonLoading ? (
            <SkeletonGroup label="正在加载持仓与目标对照" className="grid min-h-40 gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
              <div className="space-y-3 border-t border-line pt-3">
                <Skeleton className="h-7 w-32" />
                <Skeleton className="h-4 w-44" />
                <Skeleton className="h-2 w-full" />
              </div>
              <div className="min-w-0 border-t border-line lg:border-t-0 lg:border-l lg:pl-5">
                <HoldingsPreviewTable holdings={null} />
              </div>
            </SkeletonGroup>
          ) : comparisonError ? null : !weights.data?.calculated_at ? (
            <div className="border-t border-line py-3 text-[13px] leading-relaxed text-ink-3">
              尚无目标权重，刷新后生成持仓对照
            </div>
          ) : comparisonReady ? (
            <div className="grid min-h-40 gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
              <div className="border-t border-line pt-3">
                <div className={`text-[22px] font-[640] ${STATUS_TEXT_CLASS[driftLevel]}`}>
                  {driftHeadline}
                </div>
                <div className="mt-1.5 text-[13px] text-ink-2">
                  当前 {holdingsCount === 0 ? '空仓' : `${holdingsCount} 只`} · 目标 {targetCount} 只
                </div>
                {plan.off > 0 && (
                  <>
                    <div className="mt-1 text-[13px] text-ink-2">
                      卖 {plan.sells} · 买 {plan.buys}{plan.flips > 0 ? ` · 翻向 ${plan.flips}` : ''}
                    </div>
                    <div className="mt-4 flex items-baseline justify-between gap-3 text-[12.5px]">
                      <span className="text-ink-2">预计换手</span>
                      <span className="num font-medium text-ink-1">{turnover.toFixed(1)}%</span>
                    </div>
                    <DriftBar rows={plan.rows} />
                  </>
                )}
              </div>
              <div className="min-w-0 border-t border-line lg:border-t-0 lg:border-l lg:pl-5">
                <HoldingsPreviewTable holdings={currentHoldings} currency={item.currency} />
              </div>
            </div>
          ) : null}
          <ErrorNotice
            title="持仓与目标对照加载失败"
            error={comparisonError}
            variant={positions.length > 0 || weights.data != null ? 'stale' : 'section'}
            updatedAt={assetSnapshots.updatedAt ?? weights.updatedAt}
            onRetry={() => Promise.all([assetSnapshots.refresh(), activity.refresh(), weights.reloadSnapshot()]).then(() => undefined)}
          />
        </Card>

        <Card className="px-6 py-4">
          <div className="mb-3 flex items-center justify-between gap-2">
            <h3 className="text-[13px] font-semibold text-ink-2">自动执行</h3>
            <div className="flex min-w-0 items-center gap-3">
              <StaleDataStatus updatedAt={automaticStaleAt} />
              <button
                type="button"
                disabled={!scheduleKind}
                title={!scheduleKind ? '渠道能力加载中' : undefined}
                className="cursor-pointer text-[12.5px] font-semibold text-accent hover:underline disabled:cursor-default disabled:text-ink-3 disabled:no-underline"
                onClick={() => setTimerOpen(true)}
              >
                调整
              </button>
            </div>
          </div>
          <button
            type="button"
            disabled={!scheduleKind}
            title={!scheduleKind ? '渠道能力加载中' : undefined}
            className="flex w-full cursor-pointer items-center justify-between gap-3 border-t border-line py-1.5 text-left text-[14px] first:border-t-0 disabled:cursor-default"
            onClick={() => setTimerOpen(true)}
          >
            <span className="flex-none text-ink-2">节奏</span>
            <span className="flex min-w-0 flex-1 items-center justify-end">
              {account.loading ? (
                <SkeletonText className="ml-auto w-28" />
              ) : account.error && account.data === null ? (
                <span className="ml-auto text-[13px] text-ink-3">—</span>
              ) : (
                <OverflowText
                  className="min-w-0 flex-1 text-right font-medium text-ink-1"
                  text={cronExpr ? (cronHuman ?? '自定义执行节奏') : '—'}
                />
              )}
              <span className="ml-1.5 flex-none text-ink-3" aria-hidden>
                ›
              </span>
            </span>
          </button>
          <ErrorNotice
            title="账户节奏加载失败"
            error={localQueryError(connectionUnavailable, accountFreshness)}
            variant={account.stale ? 'stale' : 'compact'}
            updatedAt={account.updatedAt}
            onRetry={account.refresh}
          />
          {nextRun.loading ? (
            <ScheduleTimelineSkeleton />
          ) : nextRun.error && nextRun.data === null ? null : (
            <ScheduleTimeline
              lastExecutedAt={item.last_exec_at}
              nextRunTimes={nextRun.data?.next_execution_times ?? []}
            />
          )}
          <ErrorNotice
            title="自动执行计划加载失败"
            error={localQueryError(connectionUnavailable, nextRunFreshness)}
            variant={nextRun.stale ? 'stale' : 'compact'}
            updatedAt={nextRun.updatedAt}
            onRetry={nextRun.refresh}
          />
        </Card>
      </div>

      <TimerQuickModal
        open={timerOpen}
        accountId={accountId}
        accountName={item.name}
        tradeChannel={item.trade_channel}
        cronExpr={cronExpr}
        onClose={() => setTimerOpen(false)}
        onSaved={() => {
          account.refresh()
          nextRun.refresh()
          onDashboardRefresh?.()
        }}
      />

      {/* 近期活动 */}
      <div className="mx-0.5 mt-6 mb-3 flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5">
        <span className="text-xs font-semibold tracking-wide text-ink-3">近期活动</span>
        <div className="flex min-w-0 items-center gap-3">
          <StaleDataStatus updatedAt={activityStaleAt} />
          <Link to={`/accounts/${accountId}/history`} className="text-[12.5px] font-semibold text-accent hover:underline">
            完整回看 / 绩效 →
          </Link>
        </div>
      </div>
      <Card className="overflow-hidden">
        {activity.loading && <div className="px-6 py-4 text-[14px] text-ink-2">加载中…</div>}
        <div className="px-6">
          <ErrorNotice
            title="近期活动加载失败"
            error={localQueryError(connectionUnavailable, activityFreshness)}
            variant={activity.stale ? 'stale' : 'section'}
            updatedAt={activity.updatedAt}
            onRetry={activity.refresh}
          />
        </div>
        {!activity.loading && !activity.error && (activity.data?.data.length ?? 0) === 0 && (
          <div className="px-6 py-4 text-[14px] text-ink-3">暂无执行或跳过记录。</div>
        )}
        {(() => {
          const { rows, truncated } = buildRecentActivity(activity.data?.data ?? [], {
            cap: 6,
            fetchLimit: RECENT_LIMIT,
          })
          const fmt = (t: string) => t.replace('T', ' ').slice(5, 16)
          return (
            <>
              {rows.map((row) => {
                const clickable = 'executionId' in row && Boolean(row.executionId)
                const onClick = () => {
                  if ('executionId' in row && row.executionId)
                    navigate(`/accounts/${accountId}/executions/${row.executionId}`)
                }
                return (
                  <div
                    key={row.key}
                    className={`flex items-center gap-4 border-t border-line px-6 py-3 text-[14px] transition-colors first:border-t-0 ${
                      clickable ? 'cursor-pointer hover:bg-bg-subtle' : ''
                    }`}
                    onClick={onClick}
                  >
                    <span className="num w-28 flex-none text-[13px] text-ink-3">{fmt(row.time)}</span>
                    {row.type === 'fill' && (
                      <>
                        <span className="w-4 flex-none text-center text-ok">✓</span>
                        <OverflowText className="min-w-0 flex-1" text={recentRowText(row)} />
                        <RecentAmount amount={row.amount} currency={item.currency} />
                      </>
                    )}
                    {row.type === 'partial' && (
                      <>
                        <span className="w-4 flex-none text-center text-warn">⚠</span>
                        <OverflowText className="min-w-0 flex-1 text-ink-1" text={recentRowText(row)} />
                        <RecentAmount amount={row.amount} currency={item.currency} />
                      </>
                    )}
                    {row.type === 'noop' && (
                      <>
                        <span className="w-4 flex-none text-center text-ink-3">–</span>
                        <OverflowText className="min-w-0 flex-1 text-ink-3" text={recentRowText(row)} />
                      </>
                    )}
                    {row.type === 'fail' && (
                      <>
                        <span className="w-4 flex-none text-center text-warn">⚠</span>
                        <OverflowText className="min-w-0 flex-1 text-ink-1" text={recentRowText(row)} />
                      </>
                    )}
                    {row.type === 'terminated' && (
                      <>
                        <span className="w-4 flex-none text-center text-ink-3">■</span>
                        <OverflowText className="min-w-0 flex-1 text-ink-2" text={recentRowText(row)} />
                      </>
                    )}
                    {row.type === 'skip' && (
                      <>
                        <span className="w-4 flex-none text-center text-ink-3">–</span>
                        <OverflowText className="min-w-0 flex-1 text-ink-2" text={recentRowText(row)} />
                      </>
                    )}
                    {row.type === 'blocked' && (
                      <>
                        <span className="w-4 flex-none text-center text-ink-3">–</span>
                        <OverflowText className="min-w-0 flex-1 text-ink-2" text={recentRowText(row)} />
                      </>
                    )}
                  </div>
                )
              })}
              {truncated && (
                <Link
                  to={`/accounts/${accountId}/history`}
                  className="block border-t border-line px-6 py-3 text-center text-[13px] text-ink-3 hover:text-ink-2"
                >
                  更多历史见「完整回看」→
                </Link>
              )}
            </>
          )
        })()}
      </Card>
    </section>
  )
}

/**
 * 近期活动右侧权益：数字与页头同一口径，单位走渠道声明的简短名（CNY→元）。
 * 无金额（部分执行未带回权益）不占位，避免空列把其它行挤歪。
 */
function RecentAmount({ amount, currency }: { amount: string; currency: string }) {
  if (!amount) return null
  const unit = amount === '—' ? '' : displayCurrencyUnit(currency)
  return (
    <span className="num whitespace-nowrap text-[13px] text-ink-2">
      {amount}
      {unit ? <span className="ml-1 font-medium text-ink-3">{unit}</span> : null}
    </span>
  )
}

/**
 * 账户详情「持仓 vs 目标」右栏的当前持仓快照。
 *
 * 表头与行同一张表，列宽按内容自动算。前三列 ``w-[1%]`` + nowrap 收缩到最宽格；
 * 市值不收缩、右对齐，把右栏剩余宽度吃掉——数字贴栏的右缘，品种和仓位仍然挨着。
 * 表头 sticky 钉在滚动容器顶。
 */
const PREVIEW_TH = 'sticky top-0 z-[1] h-8 bg-surface align-middle font-medium'
const PREVIEW_COL = 'w-[1%] whitespace-nowrap'

function HoldingsPreviewTable({
  holdings,
  currency = '',
}: {
  /** `null` = 对照仍在加载，表结构在、单元格骨架占位。 */
  holdings: CurrentHoldingPreview[] | null
  currency?: string
}) {
  return (
    <div
      tabIndex={0}
      className="quiet-scrollbar h-40 min-w-0 overflow-y-auto overscroll-contain [scrollbar-gutter:stable] focus-visible:outline focus-visible:outline-1 focus-visible:outline-offset-2 focus-visible:outline-line"
    >
      <table aria-label="当前持仓" className="w-full border-separate border-spacing-0">
        <thead>
          <tr className="text-[11px] font-medium text-ink-3">
            <th scope="col" className={`${PREVIEW_TH} ${PREVIEW_COL} border-b border-line pr-1.5 text-left`}>
              品种
            </th>
            <th scope="col" className={`${PREVIEW_TH} ${PREVIEW_COL} border-b border-line px-1.5 text-right`}>
              仓位
            </th>
            <th scope="col" className={`${PREVIEW_TH} ${PREVIEW_COL} border-b border-line px-1.5 text-right`}>
              持仓/可用
            </th>
            <th scope="col" className={`${PREVIEW_TH} border-b border-line pl-1.5 text-right whitespace-nowrap`}>
              市值
            </th>
          </tr>
        </thead>
        <tbody>
          {holdings == null ? (
            Array.from({ length: 4 }, (_, index) => (
              <tr key={index} className="border-t border-line first:border-t-0">
                <td className={`h-8 ${PREVIEW_COL} pr-1.5`}>
                  <Skeleton className="h-3 w-12" />
                </td>
                <td className={`h-8 ${PREVIEW_COL} px-1.5`}>
                  <Skeleton className="ml-auto h-3 w-9" />
                </td>
                <td className={`h-8 ${PREVIEW_COL} px-1.5`}>
                  <Skeleton className="ml-auto h-3 w-12" />
                </td>
                <td className="h-8 pl-1.5 whitespace-nowrap">
                  <Skeleton className="ml-auto h-3 w-14" />
                </td>
              </tr>
            ))
          ) : holdings.length === 0 ? (
            <tr>
              <td colSpan={4} className="h-32 text-[13px] text-ink-3">
                当前空仓
              </td>
            </tr>
          ) : (
            holdings.map((holding) => {
              const dir = holding.direction === 'short' ? '空' : '多'
              const weight = holding.weight == null ? `${dir}—` : `${dir}${Math.abs(holding.weight).toFixed(1)}%`
              const volume = formatHoldingQuantity(holding.volume)
              const availableVolume = formatHoldingQuantity(holding.availableVolume)
              const value = holding.value == null ? '—' : withCurrency(fmtMoney(holding.value), currency)
              return (
                <tr key={holding.key} className="border-t border-line text-[12.5px] first:border-t-0">
                  <td className={`h-8 ${PREVIEW_COL} pr-1.5 text-[13px] font-[560] text-ink-1`}>{holding.symbol}</td>
                  <td className={`num h-8 ${PREVIEW_COL} px-1.5 text-right text-ink-2`}>{weight}</td>
                  <td className={`num h-8 ${PREVIEW_COL} px-1.5 text-right text-ink-2`}>
                    {volume}/{availableVolume}
                  </td>
                  <td className="num h-8 pl-1.5 text-right font-medium whitespace-nowrap text-ink-1">{value}</td>
                </tr>
              )
            })
          )}
        </tbody>
      </table>
    </div>
  )
}

/** Hero 配置带单项：label 领着值，整体是一个跳编辑分区的安静链接；值未就位时骨架占位。 */
function HeroConfigItem({
  label,
  to,
  title,
  value,
  grow = false,
  vtName,
}: {
  label: string
  to: string
  title: string
  /** `null` = 账户详情仍在加载，值位骨架占位。 */
  value: string | null
  /** 占满剩余宽并允许截断（算法长句用）。 */
  grow?: boolean
  /** 正在去往/离开对应编辑分区时为共享名（值文本 FLIP 配对）；否则不挂。 */
  vtName?: string
}) {
  const vtStyle: CSSProperties | undefined = vtName ? { viewTransitionName: vtName } : undefined
  return (
    <Link
      to={to}
      title={title}
      className={`group flex min-w-0 items-center gap-1.5 ${grow ? 'min-w-48 flex-1' : 'flex-none'}`}
    >
      <span className="flex-none text-ink-3">{label}</span>
      {value === null ? (
        <SkeletonText className="w-14" />
      ) : grow ? (
        // 壳包 OverflowText：共享名挂在与值同盒的 wrapper 上，不进 marquee 组件内部。
        <span className="block min-w-0 flex-1" style={vtStyle}>
          <OverflowText className="num font-medium text-ink-1 group-hover:underline" text={value} />
        </span>
      ) : (
        <span className="num whitespace-nowrap font-medium text-ink-1 group-hover:underline" style={vtStyle}>
          {value}
        </span>
      )}
    </Link>
  )
}

/** 仪表盘与账户路由共用的冷拉骨架。 */
export function AccountDetailSkeleton() {
  return (
    <SkeletonGroup label="正在加载账户详情">
      <Card className="p-6">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="mt-[18px] h-8 w-52" />
        <Skeleton className="mt-2 h-4 w-44" />
        <div className="mt-6 border-t border-line pt-4">
          <Skeleton className="h-4 w-20" />
          <Skeleton className="mt-2 h-10 w-64" />
          <Skeleton className="mt-2 h-4 w-48" />
        </div>
        <div className="mt-4 flex gap-6 border-t border-line pt-3.5">
          <Skeleton className="h-3.5 w-28" />
          <Skeleton className="h-3.5 w-24" />
          <Skeleton className="h-3.5 w-64" />
        </div>
      </Card>
      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
        <Card className="min-h-[190px] px-6 py-4 md:col-span-2">
          <Skeleton className="h-4 w-24" />
          <div className="mt-4 grid gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
            <div className="space-y-3 border-t border-line pt-3">
              <Skeleton className="h-7 w-32" />
              <Skeleton className="h-4 w-44" />
              <Skeleton className="h-2 w-full" />
            </div>
            <div className="space-y-3 border-t border-line pt-3 lg:border-t-0 lg:border-l lg:pt-0 lg:pl-5">
              {Array.from({ length: 3 }, (_, index) => <Skeleton key={index} className="h-10 w-full" />)}
            </div>
          </div>
        </Card>
        <Card className="min-h-[190px] px-6 py-4">
          <Skeleton className="h-4 w-24" />
          <div className="mt-4 space-y-3 border-t border-line pt-3">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-4/5" />
          </div>
        </Card>
      </div>
      <div className="mt-6 mb-3"><Skeleton className="h-3 w-20" /></div>
      <Card className="px-6 py-4"><Skeleton className="h-4 w-full" /></Card>
    </SkeletonGroup>
  )
}
