import { useCallback, useState } from 'react'
import { useParams, useViewTransitionState } from 'react-router'
import { Link, useNavigate } from '@/components/ui/nav'
import { Breadcrumb } from '@/components/ui/Breadcrumb'
import { Card, SectionLabel, Chip } from '@/components/ui/Card'
import { Skeleton, SkeletonLines } from '@/components/ui/Skeleton'
import { ExposureBar } from '@/components/viz/ExposureBar'
import { ConfirmModal, type ConfirmSpec } from '@/components/ui/ConfirmModal'
import { getPortfolio, getStrategyRecords, getLatestWeights, updatePortfolio } from '@/lib/api/portfolios'
import { useDomainStore } from '@/stores/domain'
import { triggerExecute } from '@/lib/api/executions'
import { usePolling } from '@/lib/hooks/usePolling'
import { useToastStore } from '@/stores/ui'
import { channelLabel } from '@/features/dashboard/display'
import { getChannelForMarket } from '@/stores/channels'
import type { LatestWeights } from '@/types/api'

/** 集中度指标：最大权重、前 10 占比、有效策略数（1/ΣwΒ）。 */
function concentration(weights: number[]) {
  const ws = weights.map(Math.abs).sort((a, b) => b - a)
  const total = ws.reduce((s, w) => s + w, 0) || 1
  const norm = ws.map((w) => w / total)
  const top10 = norm.slice(0, 10).reduce((s, w) => s + w, 0) * 100
  const eff = 1 / norm.reduce((s, w) => s + w * w, 0)
  return { max: (norm[0] ?? 0) * 100, top10, eff }
}

export function PortfolioDetailPage() {
  const { id } = useParams()
  const portfolioId = Number(id)
  const navigate = useNavigate()
  const toast = useToastStore((s) => s.toast)
  const [confirm, setConfirm] = useState<ConfirmSpec | null>(null)

  const portfolio = usePolling(useCallback((s: AbortSignal) => getPortfolio(portfolioId, s), [portfolioId]), 0)
  const records = usePolling(useCallback((s: AbortSignal) => getStrategyRecords(portfolioId, s), [portfolioId]), 0)
  const accounts = useDomainStore((s) => s.accounts)
  const portfolios = useDomainStore((s) => s.portfolios)

  const pf = portfolio.data
  // 组合列表已在共享 store 里，冷拉详情时先用它渲染页头，避免整屏塌成一行（L1 消闪）。
  const lite = portfolios?.find((p) => p.id === portfolioId) ?? null
  const head = pf ?? lite
  const boundAccount = accounts?.find((a) => a.portfolio_id === portfolioId) ?? null
  const channel = boundAccount?.trade_channel ?? getChannelForMarket(head?.market)

  // 共享元素 FLIP：组合名与列表卡配对（A）；绑定账户名与账户详情头配对（B，复用 account-name）。
  const pfNameVt = useViewTransitionState(`/portfolios/${portfolioId}`)
  const acctNameVt = useViewTransitionState(boundAccount ? `/accounts/${boundAccount.account_id}` : '__none__')

  const weights = usePolling<LatestWeights>(
    useCallback(
      (s: AbortSignal) => (pf && channel ? getLatestWeights(portfolioId, channel, s) : Promise.resolve({})),
      [portfolioId, channel, pf],
    ),
    0,
    pf && channel ? `${portfolioId}:${channel}` : null,
  )

  if (portfolio.error && !pf)
    return (
      <section>
        <Breadcrumb
          trail={[
            { label: '组合', to: '/portfolios' },
            { label: lite?.name ?? `组合 #${portfolioId}` },
          ]}
        />
        <p className="mt-3 text-[14px] text-bad">组合加载失败：{portfolio.error.message}</p>
      </section>
    )

  const strategies = pf?.strategy_config ?? []
  const stratWeights = strategies.map((s) => s.weight)
  const conc = concentration(stratWeights)

  const target = weights.data ?? {}
  const targetRows = Object.entries(target)
    .filter(([, w]) => Math.abs(w) > 1e-9)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
  const coverage = targetRows.reduce((s, [, w]) => s + Math.abs(w), 0) * 100

  const runFanout = () => {
    if (!boundAccount) return
    setConfirm({
      title: '全部跟随账户立即执行',
      body: `通知跟随本组合的账户（${boundAccount.name}）立即按最新目标调仓。若目标未变，多数会空跑、几乎不增成本。`,
      okText: '通知执行',
      onConfirm: async () => {
        try {
          await triggerExecute(boundAccount.account_id)
          toast(`已通知 ${boundAccount.name} 立即调仓`)
        } catch (e) {
          toast(`触发失败：${e instanceof Error ? e.message : String(e)}`)
        }
      },
    })
  }

  return (
    <section>
      <Breadcrumb
        trail={[
          { label: '组合', to: '/portfolios' },
          { label: head?.name ?? `组合 #${portfolioId}` },
        ]}
      />

      {/* Hero：有 head（成品或列表 lite）即时渲染，全空才骨架 */}
      <Card className="mt-3 p-6">
        {head ? (
          <>
            <div className="flex flex-wrap items-center gap-3">
              <span
                className="text-[18px] font-[640]"
                style={pfNameVt ? { viewTransitionName: `portfolio-name-${portfolioId}` } : undefined}
              >
                {head.name}
              </span>
              <Chip>{head.market}</Chip>
              <Chip>
                {head.custom_calc_py_code
                  ? '自定义逻辑'
                  : pf
                    ? `加权组合 · ${strategies.length} 策略`
                    : '加权组合'}
              </Chip>
            </div>
            {head.description && <div className="mt-2 text-[13px] text-ink-2">{head.description}</div>}
            <div className="mt-6 flex gap-8 border-t border-line pt-4">
              <Meta k="跟随账户" v={boundAccount ? '1 个' : '未绑定'} />
              <Meta k="目标覆盖" v={targetRows.length ? `${coverage.toFixed(0)}%` : '—'} />
              <Meta k="创建" v={head.created_at.slice(0, 10)} />
            </div>
            <div className="mt-6 flex gap-2.5">
              <button
                className="cursor-pointer rounded-[9px] border border-line bg-surface px-4 py-2 text-[13.5px] text-ink-2 hover:border-ink-3/40 hover:text-ink-1"
                onClick={() => navigate(`/portfolios/${portfolioId}/edit`)}
              >
                编辑组合
              </button>
              {boundAccount && (
                <button
                  className="cursor-pointer rounded-[9px] border-0 bg-ink-1 px-4 py-2 text-[13.5px] font-[550] text-surface"
                  onClick={runFanout}
                >
                  全部跟随账户立即执行
                </button>
              )}
            </div>
          </>
        ) : (
          <>
            <Skeleton className="h-6 w-52" />
            <Skeleton className="mt-3 h-4 w-full" />
            <Skeleton className="mt-6 h-10 w-64" />
          </>
        )}
      </Card>

      {/* 策略构成 */}
      <SectionLabel>策略构成 · 各策略在组合中的权重</SectionLabel>
      <Card className="px-6 py-4">
        {!pf ? (
          <SkeletonLines rows={4} />
        ) : strategies.length === 0 ? (
          <p className="text-[13px] text-ink-3">
            {pf.custom_calc_py_code ? '自定义逻辑组合，无策略权重表。' : '暂无策略。'}
          </p>
        ) : (
          <>
            <ExposureBar weights={stratWeights} />
            <div className="my-2 text-[13px] text-ink-2">
              {strategies.length} 个策略 · 最大 {conc.max.toFixed(1)}% · 前 10 占 {conc.top10.toFixed(0)}% · 有效 ≈ {conc.eff.toFixed(1)} 个
            </div>
            {[...strategies]
              .sort((a, b) => b.weight - a.weight)
              .map((s) => (
                <div key={s.name} className="flex items-center gap-3 border-t border-line py-3 first:border-t-0">
                  <div className="flex-1 min-w-0">
                    <div className="truncate text-[14px] font-semibold">{s.name}</div>
                    {s.base_freq && <div className="text-xs text-ink-3">频率 {s.base_freq}</div>}
                  </div>
                  <div className="num w-14 flex-none text-right text-[14.5px] font-[640]">
                    {(s.weight * 100).toFixed(1)}%
                  </div>
                </div>
              ))}
            <div className="mt-3 text-xs text-ink-3">
              注：后端仅下发合成后的目标权重，暂无「逐策略 → 品种」的分项贡献，故此处不展开双向归因。
            </div>
          </>
        )}
      </Card>

      {/* 原始目标 */}
      <SectionLabel>组合原始目标 · 各账户再套自己的风控/杠杆</SectionLabel>
      <Card className="px-6 py-4">
        {!pf && <SkeletonLines rows={3} />}
        {pf && weights.loading && <p className="text-[13px] text-ink-2">计算目标权重中…</p>}
        {pf && weights.error && <p className="text-[13px] text-ink-3">目标权重暂不可用：{weights.error.message}</p>}
        {pf && !weights.loading && !weights.error && targetRows.length === 0 && (
          <p className="text-[13px] text-ink-3">当前无目标持仓。</p>
        )}
        {targetRows.length > 0 && (
          <>
            <div className="mb-1 text-[13px] text-ink-2">
              {targetRows.length} 只 · 最大 {targetRows[0][0]} {(targetRows[0][1] * 100).toFixed(1)}%
            </div>
            <ExposureBar weights={targetRows.map(([, w]) => w)} />
            <div className="mt-2">
              {targetRows.map(([sym, w]) => (
                <div key={sym} className="flex items-center gap-3 border-t border-line py-2.5 text-[13.5px] first:border-t-0">
                  <span className="flex-1 min-w-0 truncate">{sym}</span>
                  <span className={`num w-16 flex-none text-right font-semibold ${w < 0 ? 'text-bad' : ''}`}>
                    {(w * 100).toFixed(1)}%
                  </span>
                </div>
              ))}
            </div>
          </>
        )}
      </Card>

      {/* 跟随账户 */}
      <SectionLabel>跟随此组合的账户</SectionLabel>
      <Card className="px-6 py-2">
        {boundAccount ? (
          <Link
            to={`/accounts/${boundAccount.account_id}`}
            className="flex items-center gap-3 py-3 text-inherit hover:bg-bg-subtle"
          >
            <div>
              <div
                className="text-[14px] font-semibold"
                style={acctNameVt ? { viewTransitionName: `account-name-${boundAccount.account_id}` } : undefined}
              >
                {boundAccount.name}
              </div>
              <div className="text-xs text-ink-3">{channelLabel(boundAccount.trade_channel, boundAccount.market)}</div>
            </div>
            <span className="ml-auto text-[18px] text-ink-3">›</span>
          </Link>
        ) : (
          <p className="py-3 text-[13px] text-ink-3">暂无账户跟随此组合。</p>
        )}
      </Card>

      {/* 策略更换记录 */}
      <SectionLabel>策略更换记录</SectionLabel>
      <Card className="px-6 py-4">
        {records.loading && <p className="text-[13px] text-ink-2">加载中…</p>}
        {!records.loading && (records.data?.data.length ?? 0) === 0 && (
          <p className="text-[13px] text-ink-3">暂无更换记录。</p>
        )}
        {(records.data?.data.length ?? 0) > 0 && (
          <div className="relative pl-[22px]">
            <div className="absolute left-1.5 top-2 bottom-2 w-0.5 bg-line" />
            {records.data!.data
              .slice()
              .sort((a, b) => b.created_at.localeCompare(a.created_at))
              .map((r, i) => (
                <div key={r.id ?? i} className="relative flex items-center gap-3 py-2.5">
                  <span className={`absolute -left-[19px] top-3.5 h-[9px] w-[9px] rounded-full border-2 border-surface ${i === 0 ? 'bg-accent' : 'bg-border-strong'}`} />
                  <div className="flex-1">
                    <div className="text-[13px] text-ink-3">
                      {r.created_at.replace('T', ' ').slice(0, 16)}
                      {i === 0 && <span className="ml-2 text-accent">当前版本</span>}
                    </div>
                    <div className="text-[14px]">{r.strategies.length} 个策略配置</div>
                  </div>
                  {i !== 0 && (
                    <button
                      className="cursor-pointer rounded-lg border border-line px-2.5 py-1 text-[12.5px] text-ink-2 hover:border-ink-3/40 hover:text-ink-1"
                      onClick={() =>
                        setConfirm({
                          title: '回滚到此版配置',
                          body: '把这一版的策略配置重新发布为新版本。回滚的是配置（spec），持仓仍按当下市场重算。',
                          okText: '回滚',
                          onConfirm: async () => {
                            try {
                              await updatePortfolio(portfolioId, { strategies: r.strategies })
                              toast('已回滚为新版本')
                              records.refresh()
                              portfolio.refresh()
                            } catch (e) {
                              toast(`回滚失败：${e instanceof Error ? e.message : String(e)}`)
                            }
                          },
                        })
                      }
                    >
                      回滚
                    </button>
                  )}
                </div>
              ))}
          </div>
        )}
      </Card>

      <ConfirmModal spec={confirm} onClose={() => setConfirm(null)} />
    </section>
  )
}

function Meta({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <div className="text-xs text-ink-3">{k}</div>
      <div className="mt-px text-[16px] font-semibold">{v}</div>
    </div>
  )
}
