import { useViewTransitionState } from 'react-router'
import { useNavigate } from '@/components/ui/nav'
import { Card } from '@/components/ui/Card'
import { NumberTicker } from '@/components/ui/NumberTicker'
import { Sparkline } from '@/components/viz/Sparkline'
import { ExposureBar } from '@/components/viz/ExposureBar'
import { INTEGRITY_ICON, INTEGRITY_TEXT_CLASS, INTEGRITY_ORDER, channelLabel } from '@/features/dashboard/display'
import { isExecutingStatus, phaseLabel, runVerb } from '@/features/dashboard/execProgress'
import { integrityOf, gateOf, stateVerdict, holdingText, type Integrity } from '@/lib/derive'
import { displayCurrencyUnit } from '@/lib/format'
import { useRunning } from '@/stores/liveExec'
import type { AccountDashboardItem } from '@/types/api'

function FleetCard({
  item,
  portfolioName,
}: {
  item: AccountDashboardItem
  portfolioName: string | null
}) {
  const navigate = useNavigate()
  const to = `/accounts/${item.account_id}`
  // 仅「正在跳转到本卡」时给账户名挂共享名，与详情页头配对做共享元素 FLIP（平移 + 微缩）。
  const transitioning = useViewTransitionState(to)
  const state = stateVerdict(item)
  const gate = gateOf(item)
  // 服务端真源的在途执行：在跑时状态文案与卡边优先反映「正在执行」。
  const live = useRunning(item.account_id)
  // 「今日」涨跌用服务端按自然日锚定的 today_pct，不再前端取序列末两点相减。
  const pct = item.today_pct ?? null
  // 红涨绿跌：涨→up(红)、跌→down(绿)。
  const pctCls = pct == null ? 'text-ink-2' : pct > 0 ? 'text-up' : pct < 0 ? 'text-down' : 'text-ink-2'

  // 卡边：在跑走 accent（run 档，不碰红绿）；否则注意/失败同为琥珀，失败以更重边框强度区分。
  const borderCls = live
    ? 'border-accent/45 bg-accent-soft/40'
    : state.integrity === 'off'
      ? 'border-warn/45 bg-warn-tint'
      : 'border-transparent'

  return (
    <Card
      className={`mb-4 border px-6 py-4 transition-transform hover:-translate-y-px ${borderCls}`}
      onClick={() => navigate(to)}
    >
      <div className="flex items-center gap-3">
        <span
          className="text-[15px] font-[620]"
          style={transitioning ? { viewTransitionName: `account-name-${item.account_id}` } : undefined}
        >
          {item.name}
        </span>
        {/* 渠道徽章与账户名同一逻辑单元：同门控挂名、同轨飞行，不与名字撕开。 */}
        <span
          className="rounded-chip bg-fill px-2 py-0.5 text-[11px] text-ink-2"
          style={transitioning ? { viewTransitionName: `account-channel-${item.account_id}` } : undefined}
        >
          {channelLabel(item.trade_channel, '')}
        </span>
        {gate.gate === 'paused' && (
          <span className="rounded-chip bg-fill px-2 py-0.5 text-[11px] text-ink-3">{gate.label}</span>
        )}
        <span className="text-xs text-ink-3">{portfolioName ?? (item.portfolio_id ? `组合 #${item.portfolio_id}` : '未绑定组合')}</span>
        {live ? (
          <span className="ml-auto inline-flex items-center gap-1.5 text-[13.5px] font-semibold text-accent">
            {isExecutingStatus(live.status)
              ? `⟳ 正在${runVerb(live.kind)} · ${phaseLabel(live.phase)}${live.pendingExecutionId ? ' · 结束后再调一次' : ''}`
              : '等待执行'}
          </span>
        ) : (
          <span className={`ml-auto inline-flex items-center gap-1.5 text-[13.5px] font-semibold ${INTEGRITY_TEXT_CLASS[state.integrity]}`}>
            {INTEGRITY_ICON[state.integrity]} {state.text}
          </span>
        )}
      </div>

      <div className="mt-3 flex items-end justify-between gap-3">
        <div className="flex flex-wrap items-baseline gap-2">
          <span className="num text-[26px] font-[640] tracking-tight">
            <NumberTicker value={item.total_asset} format={{ minimumFractionDigits: 2, maximumFractionDigits: 2 }} />
          </span>
          <span className="text-[13px] text-ink-3">{displayCurrencyUnit(item.currency)}</span>
          {pct != null && (
            <span className={`num text-[13px] ${pctCls}`}>
              今日 {pct >= 0 ? '+' : '−'}
              <NumberTicker value={Math.abs(pct)} format={{ minimumFractionDigits: 2, maximumFractionDigits: 2 }} suffix="%" />
            </span>
          )}
        </div>
        <Sparkline data={item.equity_series} width={120} height={34} />
      </div>

      <div className="mt-3 flex gap-2.5 border-t border-line pt-3 text-[13.5px]">
        <span className="min-w-14 flex-none text-ink-3">当前持仓</span>
        <span>{holdingText(item.holdings_count, item.position_weights)}</span>
      </div>
      <ExposureBar weights={item.position_weights} />
    </Card>
  )
}

/** 舰队总览（N≥2）：汇总条 + 按状态排序的账户卡。 */
export function FleetView({
  items,
  portfolioNames,
}: {
  items: AccountDashboardItem[]
  portfolioNames: Map<number, string>
}) {
  const withIntegrity = items.map((item) => ({ item, integrity: integrityOf(item).integrity }))
  const offCount = withIntegrity.filter((x) => x.integrity === 'off').length
  const unknownCount = withIntegrity.filter((x) => x.integrity === 'unknown').length
  // 汇总只把「偏离」算作要看的风险；「未知」是缺证据、给中性待办；全在位才敢报「系统正常」。
  const rollup: { key: Integrity; text: string } =
    offCount > 0
      ? { key: 'off', text: `${items.length} 个账户 · ${offCount} 个需要看看` }
      : unknownCount > 0
        ? { key: 'unknown', text: `${items.length} 个账户 · ${unknownCount} 个待对账` }
        : { key: 'aligned', text: `${items.length} 个账户 · 全部到位 · 系统正常` }

  const sorted = [...withIntegrity].sort((a, b) => INTEGRITY_ORDER[a.integrity] - INTEGRITY_ORDER[b.integrity])

  return (
    <section>
      <div className="mx-0.5 my-2 mb-6 flex flex-wrap items-center justify-between gap-3">
        <span className={`inline-flex items-center gap-1.5 text-[16px] font-[640] ${INTEGRITY_TEXT_CLASS[rollup.key]}`}>
          {INTEGRITY_ICON[rollup.key]} {rollup.text}
        </span>
      </div>
      {sorted.map(({ item }) => (
        <FleetCard
          key={item.account_id}
          item={item}
          portfolioName={item.portfolio_id != null ? (portfolioNames.get(item.portfolio_id) ?? null) : null}
        />
      ))}
    </section>
  )
}
