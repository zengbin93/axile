import { useCallback, useEffect, useState } from 'react'
import { useViewTransitionState } from 'react-router'
import { Link, useNavigate } from '@/components/ui/nav'
import { Card, SectionLabel, Chip } from '@/components/ui/Card'
import { DriftBar } from '@/components/viz/DriftBar'
import { Sparkline } from '@/components/viz/Sparkline'
import { InkRewrite } from '@/components/ui/InkRewrite'
import { NumberTicker } from '@/components/ui/NumberTicker'
import { AccountActions } from '@/features/account/AccountActions'
import { useExecutionRunner } from '@/features/account/useExecutionRunner'
import { useTerminateAction } from '@/features/account/useTerminateAction'
import { buildRecentActivity } from '@/features/account/recent'
import { INTEGRITY_ICON, INTEGRITY_TEXT_CLASS, STATUS_ICON, STATUS_TEXT_CLASS, channelLabel } from '@/features/dashboard/display'
import { phaseLabel, runVerb } from '@/features/dashboard/execProgress'
import { useRunning } from '@/stores/liveExec'
import {
  getAccount,
  getAccountActivity,
  getAccountTargetWeights,
  getNextRun,
  prefetchExecuteRecords,
  updateAccount,
  deleteAccount,
} from '@/lib/api/accounts'
import { usePolling } from '@/lib/hooks/usePolling'
import { stateVerdict, gateOf, rebalancePlan, positionsOf, type StatusLevel } from '@/lib/derive'
import { marketForChannel, describeCron, nextFires, fmtFire } from '@/features/setup/cron'
import { TimerQuickModal } from '@/features/setup/TimerQuickModal'
import { useToastStore } from '@/stores/ui'
import type { AccountDashboardItem, LatestWeights } from '@/types/api'

interface AccountDetailProps {
  accountId: number
  /** 若来自仪表盘可直接传入聚合项，省一次请求；否则组件自取。 */
  item: AccountDashboardItem
  /** 仪表盘数据刷新回调（执行/启停后触发）。 */
  onDashboardRefresh?: () => void
}

export function AccountDetail({ accountId, item, onDashboardRefresh }: AccountDetailProps) {
  const navigate = useNavigate()
  const toast = useToastStore((s) => s.toast)
  const [timerOpen, setTimerOpen] = useState(false)
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

  const isStarted = startedOverride ?? item.is_started
  useEffect(() => {
    if (startedOverride != null && item.is_started === startedOverride) {
      setStartedOverride(null)
    }
  }, [item.is_started, startedOverride])

  const account = usePolling(useCallback((s: AbortSignal) => getAccount(accountId, s), [accountId]), 15000)
  const RECENT_LIMIT = 50
  const activity = usePolling(
    useCallback((s: AbortSignal) => getAccountActivity(accountId, { limit: RECENT_LIMIT }, s), [accountId]),
    10000,
  )
  const nextRun = usePolling(useCallback((s: AbortSignal) => getNextRun(accountId, s), [accountId]), 30000)

  const portfolioId = account.data?.portfolio_id ?? null
  // 目标改取账户级「执行器口径」权重（后端已叠加杠杆与精度），与含杠杆的真实持仓同尺。
  const weights = usePolling<LatestWeights>(
    useCallback((s: AbortSignal) => getAccountTargetWeights(accountId, s), [accountId]),
    60000,
    accountId,
  )

  const runner = useExecutionRunner(accountId, () => {
    activity.refresh()
    onDashboardRefresh?.()
  })
  // 服务端真源的在途执行（SSE/轮询汇入 liveExec store）：任何来源发起的执行都可见。
  const live = useRunning(accountId)
  // 当前在途执行 id：优先服务端真源，退回本地 runner（首帧前）。用于「一行可点跳详情」。
  const runningExecId = live?.executionId ?? runner.executionId

  const recordList = activity.data?.data.flatMap((item) => item.kind === 'execution' ? [item.record] : []) ?? []
  const positions = positionsOf(recordList)
  const target = weights.data ?? {}
  // 背离摘要：与明细抽屉同口径（均出自 rebalancePlan）。文案讲「几只要动 · 卖几买几」，
  // 条画各品种的要成交幅度；到位/空仓退成静态一句。
  const plan = rebalancePlan(positions, target, item.total_asset)
  const driftLevel: StatusLevel = plan.off > 0 ? 'warn' : 'ok'
  const driftText =
    plan.rows.length === 0
      ? '空仓 · 与目标一致'
      : plan.off === 0
        ? '已调仓到位'
        : `${plan.off} 只待调整 · 卖 ${plan.sells} 买 ${plan.buys}${plan.flips > 0 ? ` · 翻向 ${plan.flips}` : ''}`
  // 在位性（风险轴）只由执行结果派生、不看 is_started；档位（模式）随乐观 is_started 变，便于启停后立刻日记式重写。
  // 四象限判词：模式给风险改台词（暂停+偏离＝不会自愈，措辞最重）。
  const state = stateVerdict({ ...item, is_started: isStarted })
  const gate = gateOf({ ...item, is_started: isStarted })
  // 执行态：服务端 live 优先，runner 仅首帧前乐观；驱动主句「正在执行/清仓」与生命体征。
  const isRunning = !!(live || runner.running)
  // 终止动作 + 防连点：点后乐观进「终止中…」并禁用按钮，执行离开运行态即复位。
  const { terminating, terminate } = useTerminateAction(accountId, isRunning, activity.refresh)
  const runKind = live?.kind ?? (runner.kind === 'clear' ? 'clear' : 'rebalance')
  // 主句只跟离散态变（进出执行、执行↔清仓、启停空闲句）；phase 不并入，避免连刷糊墨。
  const statusHeadline = isRunning
    ? `正在${runVerb(runKind)}`
    : `${INTEGRITY_ICON[state.integrity]} ${state.text}`
  // 「需要看看」兑现：空闲且上次失败时，状态行点进最近失败执行详情（与近期失败行同构）。
  const lastFailExecId =
    !isRunning && state.integrity === 'off'
      ? (recordList.find((r) => r.is_success !== 1 && r.execution_id)?.execution_id ?? null)
      : null
  const statusNavId = runningExecId ?? lastFailExecId
  const goStatusNav = statusNavId
    ? () => navigate(`/accounts/${accountId}/executions/${statusNavId}`)
    : undefined

  // 定时节奏：把存储的 crontab 反解成设置向导同款人话（命中预设时如「每 15 分钟 · 补发 2 次」）；
  // 命不中则退为「自定义」并给出下次触发预览，原始表达式收进 tooltip。
  const cronExpr = account.data?.cron_expr ?? ''
  const cronHuman = cronExpr ? describeCron(marketForChannel(item.trade_channel), cronExpr) : null
  const cronFires =
    cronExpr && !cronHuman
      ? nextFires(
          cronExpr
            .split(/[|\n]/)
            .map((s) => s.trim())
            .filter(Boolean),
          3,
        )
      : []

  const onToggleStarted = async () => {
    const next = !isStarted
    setStartedOverride(next)
    try {
      await updateAccount(accountId, { is_started: next })
      toast(next ? '已启动自动执行' : '已暂停自动执行')
      account.refresh()
      onDashboardRefresh?.()
    } catch (e) {
      setStartedOverride(null)
      toast(`操作失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }
  const onDelete = async () => {
    try {
      await deleteAccount(accountId)
      toast('账户已删除')
      onDashboardRefresh?.()
      navigate('/')
    } catch (e) {
      toast(`删除失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  // 「今日」涨跌用服务端按自然日锚定的 today_pct（昨收/今开为基准），不再前端取序列末两点相减。
  const pct = item.today_pct ?? null

  return (
    <section>
      {/* Hero */}
      <Card className="p-6">
        <div className="flex flex-wrap items-center gap-3">
          {/* 与舰队卡 / 组合行 / 编辑页标题名配对做共享元素 FLIP（平移 + 微缩）。 */}
          <span
            className="text-[16px] font-[620]"
            style={nameVt ? { viewTransitionName: `account-name-${accountId}` } : undefined}
          >
            {item.name}
          </span>
          <Chip>{channelLabel(item.trade_channel, item.market)}</Chip>
          {gate.gate === 'paused' && <Chip>{gate.label}</Chip>}
          <AccountActions
            name={item.name}
            isStarted={isStarted}
            running={isRunning}
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
            isRunning ? 'pl-[18px]' : 'pl-0'
          } ${isRunning ? 'text-accent' : INTEGRITY_TEXT_CLASS[state.integrity]}${
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
          {isRunning && (
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
            textClassName={isRunning ? 'text-accent exec-flow' : INTEGRITY_TEXT_CLASS[state.integrity]}
          />
          {/* 相位副标：外壳 phase-grow 让入场 footprint 宽度 0→内容（grid-fr，箭头随 reflow 挪、
              进执行那刻不被瞬时占位顶跳）；内层 phase-enter 管 opacity 淡入。相位词逐步推进走
              label 档日记换字（触发→冻结输入→算目标→下单→对账），宽变由内层 InkRewrite fluid 自理。
              首帧不播、纯 opacity 无 blur，不与主句流光抢；「·」静态钉住只重写相位词。 */}
          {isRunning && (
            <span className="phase-grow">
              <span className="phase-enter inline-flex min-w-0 items-center gap-1 overflow-hidden whitespace-nowrap text-[15px] font-medium text-ink-2">
                <span aria-hidden>·</span>
                <InkRewrite text={phaseLabel(live?.phase)} tone="label" fluid />
              </span>
            </span>
          )}
          {/* 可点暗示：执行中用生命体征箭头；失败「需要看看」用静止 →，色随父级琥珀。
              箭头纯 inline、只跟随 reflow（不再挂 transform-FLIP）：上游全走 CSS 布局过渡
              （槽宽 + 圆点 padding），箭头随之连续挪——单一范式，无采样、无自激。
              exec-arrow 自体漂移只在 running 时挂在此层。 */}
          {statusNavId && (
            <span
              className={`inline-block text-[15px] font-medium ${isRunning ? 'exec-arrow' : ''}`}
              aria-hidden
            >
              →
            </span>
          )}
        </div>
        <div className="mt-1.5 text-[13px] text-ink-3">
          {item.last_exec_at ? `上次 ${item.last_exec_at.replace('T', ' ')}` : '尚无执行'}
          {nextRun.data?.next_run_time ? ` · 下次排程 ${nextRun.data.next_run_time.replace('T', ' ').slice(0, 16)}` : ''}
        </div>

        <div className="mt-6 border-t border-line pt-4">
          <div className="text-[13px] text-ink-2">总权益</div>
          <div className="flex items-end justify-between gap-4">
            <div>
              {/* 金额 → 绩效 hero：共享元素 FLIP（平移 + 微缩）；曲线不参与。 */}
              <div
                className="num mt-0.5 text-[34px] font-[640] tracking-tight"
                style={amountVt ? { viewTransitionName: `equity-amount-${accountId}` } : undefined}
              >
                <NumberTicker value={item.total_asset} format={{ minimumFractionDigits: 2, maximumFractionDigits: 2 }} />
                <span className="ml-1.5 text-[16px] font-medium text-ink-3">{item.currency}</span>
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
                    {' · '}
                    <Link to={`/portfolios/${portfolioId}`} className="font-semibold text-accent hover:underline">
                      组合 #{portfolioId}
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
      </Card>

      {/* Vitals */}
      <SectionLabel>状态</SectionLabel>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Card className="px-6 py-4">
          <h3 className="mb-3 text-[13px] font-semibold text-ink-2">系统健康</h3>
          <Kv k="axile 服务" v="在线" ok />
          <Kv k="自动调度" v={nextRun.data?.is_scheduled ? '已排程' : '未排程'} ok={nextRun.data?.is_scheduled ?? false} />
          <Kv k="自动执行" v={isStarted ? '已启动' : '已暂停'} ok={isStarted} />
        </Card>

        <Card className="px-6 py-4">
          <h3 className="mb-3 text-[13px] font-semibold text-ink-2">持仓 vs 目标</h3>
          <Kv k="当前持仓" v={item.holdings_count === 0 ? '空仓' : `${item.holdings_count} 只`} />
          <Kv k="目标品种" v={`${Object.keys(target).filter((s) => Math.abs(target[s]) > 1e-9).length} 只`} />
          <div className={`mt-2.5 flex items-center gap-1.5 text-[13px] font-semibold ${STATUS_TEXT_CLASS[driftLevel]}`}>
            {STATUS_ICON[driftLevel]} {driftText}
          </div>
          {weights.error && <div className="mt-2 text-xs text-ink-3">目标权重暂不可用</div>}
          {plan.off > 0 && <DriftBar rows={plan.rows} />}
          <Link
            to={`/accounts/${accountId}/holdings`}
            className="mt-2.5 inline-block text-[12.5px] font-semibold text-accent hover:underline"
          >
            持仓明细 →
          </Link>
        </Card>

        <Card className="px-6 py-4">
          <div className="mb-3 flex items-center justify-between gap-2">
            <h3 className="text-[13px] font-semibold text-ink-2">自动执行</h3>
            <button
              type="button"
              className="cursor-pointer text-[12.5px] font-semibold text-accent hover:underline"
              onClick={() => setTimerOpen(true)}
            >
              调整
            </button>
          </div>
          <button
            type="button"
            className="flex w-full cursor-pointer items-center justify-between gap-3 border-t border-line py-1.5 text-left text-[14px] first:border-t-0"
            onClick={() => setTimerOpen(true)}
            title={cronExpr || undefined}
          >
            <span className="flex-none text-ink-2">节奏</span>
            <span className="min-w-0 truncate text-right font-medium text-ink-1">
              {cronExpr ? (cronHuman ?? '自定义') : '—'}
              <span className="ml-1.5 text-ink-3" aria-hidden>
                ›
              </span>
            </span>
          </button>
          <Kv k="上次" v={item.last_exec_at ? item.last_exec_at.replace('T', ' ').slice(5, 16) : '—'} />
          <Kv k="下次排程" v={nextRun.data?.next_run_time ? nextRun.data.next_run_time.replace('T', ' ').slice(5, 16) : '未排程'} />
          {cronFires.length > 0 && (
            <div className="num pt-1.5 text-right text-[12px] text-ink-3">接下来 {cronFires.map(fmtFire).join(' · ')}</div>
          )}
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
      <div className="mx-0.5 mt-6 mb-3 flex items-center justify-between">
        <span className="text-xs font-semibold tracking-wide text-ink-3">近期活动</span>
        <Link to={`/accounts/${accountId}/history`} className="text-[12.5px] font-semibold text-accent hover:underline">
          完整回看 / 绩效 →
        </Link>
      </div>
      <Card className="overflow-hidden">
        {activity.loading && <div className="px-6 py-4 text-[14px] text-ink-2">加载中…</div>}
        {activity.error && <div className="px-6 py-4 text-[14px] text-warn">加载失败：{activity.error.message}</div>}
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
                        <span className="flex-1 min-w-0 truncate">{row.desc}</span>
                        <span className="num text-[13px] text-ink-2">{row.amount}</span>
                      </>
                    )}
                    {row.type === 'noop' && (
                      <>
                        <span className="w-4 flex-none text-center text-ink-3">–</span>
                        <span className="flex-1 min-w-0 truncate text-ink-3">
                          {row.count > 1 ? `${row.count} 次空跑` : '空跑'} · 目标未变
                        </span>
                      </>
                    )}
                    {row.type === 'fail' && (
                      <>
                        <span className="w-4 flex-none text-center text-warn">⚠</span>
                        <span className="flex-1 min-w-0 truncate text-ink-1">
                          {row.count > 1 ? `连续 ${row.count}${row.saturated ? '+' : ''} 次执行失败` : '执行失败'}
                        </span>
                      </>
                    )}
                    {row.type === 'terminated' && (
                      <>
                        <span className="w-4 flex-none text-center text-ink-3">■</span>
                        <span className="flex-1 min-w-0 truncate text-ink-2">
                          {row.count > 1 ? `已终止 · ${row.count} 次` : '已终止'}
                        </span>
                      </>
                    )}
                    {row.type === 'skip' && (
                      <>
                        <span className="w-4 flex-none text-center text-ink-3">–</span>
                        <span className="flex-1 min-w-0 truncate text-ink-2">
                          {row.count > 1 ? `连续 ${row.count} 次排程因休市跳过` : '排程已跳过 · 当日休市'}
                        </span>
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

/** 状态卡里的键值行。 */
function Kv({ k, v, ok, mono }: { k: string; v: string; ok?: boolean; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between border-t border-line py-1.5 text-[14px] first:border-t-0">
      <span className="text-ink-2">{k}</span>
      <span className={`inline-flex items-center gap-1.5 font-medium text-ink-1 ${mono ? 'font-mono text-[12px]' : ''}`}>
        {/* 状态离开红绿：正常=中性 ✓（安静即好），异常=琥珀 ⚠。红绿只留给行情涨跌。 */}
        {ok != null && (
          <span className={`flex-none text-[11px] ${ok ? 'text-ink-3' : 'text-warn'}`}>{ok ? '✓' : '⚠'}</span>
        )}
        {v}
      </span>
    </div>
  )
}
