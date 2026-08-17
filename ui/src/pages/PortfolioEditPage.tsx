import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router'
import { Link, useNavigate } from '@/components/ui/nav'
import { Breadcrumb } from '@/components/ui/Breadcrumb'
import { Card, SectionLabel } from '@/components/ui/Card'
import { Skeleton, SkeletonLines } from '@/components/ui/Skeleton'
import { StrategyComposer } from '@/features/portfolio/StrategyComposer'
import { concentration, specDiff, targetDiff, type DraftStrategy } from '@/features/portfolio/diff'
import { peekDataSourceAvailable } from '@/lib/api/init'
import { getPortfolio, previewWeights, updatePortfolio } from '@/lib/api/portfolios'
import { useDomainStore } from '@/stores/domain'
import { usePolling } from '@/lib/hooks/usePolling'
import { useToastStore } from '@/stores/ui'
import { getChannelForMarket } from '@/stores/channels'
import type { LatestWeights } from '@/types/api'

/** 组合发版页 /portfolios/:id/edit —— 编辑=发布新版本。 */
export function PortfolioEditPage() {
  const { id } = useParams()
  const portfolioId = Number(id)
  const navigate = useNavigate()
  const toast = useToastStore((s) => s.toast)

  // 数据源能力位：null（启动探测失败）按允许处理，真正兜底交后端护栏。
  const dsAvailable = peekDataSourceAvailable() !== false

  const portfolio = usePolling(useCallback((s: AbortSignal) => getPortfolio(portfolioId, s), [portfolioId]), 0)
  const accounts = useDomainStore((s) => s.accounts)
  const refreshPortfolios = useDomainStore((s) => s.refreshPortfolios)
  const pf = portfolio.data

  // 草稿状态：加载到组合后用当前配置初始化一次。
  const [ready, setReady] = useState(false)
  const [name, setName] = useState('')
  const [mode, setMode] = useState<'compose' | 'custom'>('compose')
  const [strategies, setStrategies] = useState<DraftStrategy[]>([])
  const [customCode, setCustomCode] = useState('')
  const [original, setOriginal] = useState<{ name: string; strategies: DraftStrategy[]; code: string }>({
    name: '',
    strategies: [],
    code: '',
  })

  useEffect(() => {
    if (!pf || ready) return
    const strat = (pf.strategy_config ?? []).map((s) => ({ name: s.name, weight: Math.round(s.weight * 1000) / 10 }))
    const code = pf.custom_calc_py_code ?? ''
    setName(pf.name)
    setStrategies(strat)
    setCustomCode(code)
    // 无数据源时强制自定义逻辑；否则按现有配置推断初始档。
    setMode(!dsAvailable || code ? 'custom' : 'compose')
    setOriginal({ name: pf.name, strategies: strat, code })
    setReady(true)
  }, [pf, ready, dsAvailable])

  const followers = useMemo(
    () => (accounts ?? []).filter((a) => a.portfolio_id === portfolioId),
    [accounts, portfolioId],
  )
  const channel = followers[0]?.trade_channel ?? getChannelForMarket(pf?.market)

  const diff = specDiff(original.strategies, strategies)
  const nameChanged = name.trim() !== original.name
  const codeChanged = mode === 'custom' && customCode !== original.code
  const dirty = diff.dirty || nameChanged || codeChanged || (mode === 'custom') !== Boolean(original.code)

  const concBefore = concentration(original.strategies.map((s) => s.weight))
  const concAfter = concentration(strategies.map((s) => s.weight))

  // 生效目标·前后（后端 preview 背靠背）
  const [before, setBefore] = useState<LatestWeights | null>(null)
  const [after, setAfter] = useState<LatestWeights | null>(null)
  const [previewing, setPreviewing] = useState(false)

  const runPreview = async () => {
    if (!channel) {
      toast('当前市场没有可用交易渠道，无法试算')
      return
    }
    setPreviewing(true)
    try {
      const toFrac = (rows: DraftStrategy[]) =>
        rows.filter((r) => r.name.trim()).map((r) => ({ name: r.name.trim(), weight: r.weight / 100 }))
      const [b, a] = await Promise.all([
        previewWeights(toFrac(original.strategies), channel),
        previewWeights(toFrac(strategies), channel),
      ])
      setBefore(b)
      setAfter(a)
    } catch (e) {
      toast(`试算失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setPreviewing(false)
    }
  }

  const publish = async () => {
    try {
      await updatePortfolio(portfolioId, {
        name: name.trim(),
        custom_calc_py_code: mode === 'custom' ? customCode : null,
        strategies:
          mode === 'custom'
            ? []
            : strategies.filter((r) => r.name.trim()).map((r) => ({ name: r.name.trim(), weight: r.weight / 100 })),
      })
      toast('已发布新版本')
      void refreshPortfolios()
      navigate(`/portfolios/${portfolioId}`)
    } catch (e) {
      toast(`发布失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  if (portfolio.error || !pf)
    return (
      <section>
        <EditCrumb id={portfolioId} name={pf?.name} />
        <p className="mt-3 text-[14px] text-bad">组合加载失败：{portfolio.error?.message ?? '不存在'}</p>
      </section>
    )
  if (portfolio.loading || !ready)
    return (
      <section>
        {/* 表单页框 + 骨架，避免整屏塌成一行（L1 消闪） */}
        <EditCrumb id={portfolioId} name={pf?.name} />
        <Card className="mt-3 px-6 py-4">
          <SkeletonLines rows={2} />
        </Card>
        <SectionLabel>组合名称</SectionLabel>
        <Skeleton className="h-12 w-full max-w-[520px]" />
        <Card className="mt-6 px-6 py-4">
          <SkeletonLines rows={5} />
        </Card>
      </section>
    )

  const tRows = before && after ? targetDiff(before, after) : []

  return (
    <section>
      <EditCrumb id={portfolioId} name={pf?.name} />

      {/* 影响半径 */}
      <Card className="mt-3 border border-warn/30 bg-warn-tint px-6 py-4">
        <div className="text-[14px]">
          <b>影响半径</b> · 此组合被 <b>{followers.length}</b> 个账户跟随
          {followers.length > 0 && `：${followers.map((f) => f.name).join('、')}`}
        </div>
        <div className="mt-1 text-[13px] text-ink-2">发布新版本会改变这些账户<b>下次调仓</b>的目标；已到位的仓位会在下次执行时向新目标收敛。</div>
      </Card>

      {/* 命名 */}
      <SectionLabel>组合名称</SectionLabel>
      <input
        className="w-full max-w-[520px] rounded-[11px] border border-ink-3/30 bg-surface px-4 py-3 text-[16px] font-[550] outline-none focus:border-ink-2"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />

      {/* 配置编辑 */}
      <SectionLabel>策略配置 · 编辑即发布新版本</SectionLabel>
      <Card className="px-6 py-5">
        <StrategyComposer
          mode={mode}
          onModeChange={setMode}
          strategies={strategies}
          onStrategiesChange={setStrategies}
          customCode={customCode}
          onCustomCodeChange={setCustomCode}
          allowCompose={dsAvailable}
        />
      </Card>

      {/* 规格 diff */}
      <SectionLabel>你改了什么 · 规格 diff（干净归因）</SectionLabel>
      <Card className="px-6 py-4">
        {mode === 'custom' ? (
          <p className="text-[13px] text-ink-2">{codeChanged ? '自定义代码已修改。' : '自定义代码未改动。'}</p>
        ) : !diff.dirty ? (
          <p className="text-[13px] text-ink-3">尚无改动。</p>
        ) : (
          <div className="space-y-1.5 text-[13.5px]">
            {diff.added.map((s) => (
              <div key={s.name} className="flex gap-2"><span className="w-6 text-ok">＋</span><span className="flex-1">{s.name}</span><span className="num text-ok">+{s.weight}%</span></div>
            ))}
            {diff.removed.map((s) => (
              <div key={s.name} className="flex gap-2"><span className="w-6 text-bad">−</span><span className="flex-1 line-through opacity-70">{s.name}</span><span className="num text-bad">−{s.weight}%</span></div>
            ))}
            {diff.changed.map((s) => (
              <div key={s.name} className="flex gap-2"><span className="w-6 text-warn">~</span><span className="flex-1">{s.name}</span><span className="num text-ink-2">{s.from}% → <b className="text-ink-1">{s.to}%</b></span></div>
            ))}
            <div className="mt-2 border-t border-line pt-2 text-[12.5px] text-ink-3">
              集中度：最大 {concBefore.max.toFixed(0)}%→{concAfter.max.toFixed(0)}% · 有效策略 ≈ {concBefore.eff.toFixed(1)}→{concAfter.eff.toFixed(1)} 个
            </div>
          </div>
        )}
      </Card>

      {/* 生效目标·前后 */}
      <SectionLabel>生效目标 · 前后 · 含市场实时合成（参考后果）</SectionLabel>
      <Card className="px-6 py-4">
        <button
          className="cursor-pointer rounded-[9px] border-0 bg-ink-1 px-4 py-2 text-[13.5px] font-[550] text-surface disabled:opacity-50"
          onClick={runPreview}
          disabled={previewing || mode === 'custom' || !channel}
        >
          {previewing ? '试算中…' : '▶ 试算前后'}
        </button>
        {mode === 'custom' && <span className="ml-3 text-[13px] text-ink-3">自定义逻辑请在组合详情用「试跑」查看目标。</span>}
        {before && after && (
          tRows.length === 0 ? (
            <p className="mt-3 text-[13px] text-ink-3">目标无实质变化（策略权重变了但合成后目标几乎不动）。</p>
          ) : (
            <div className="mt-3">
              <div className="flex items-center gap-3 py-1.5 text-xs font-semibold text-ink-3">
                <span className="flex-1">品种</span><span className="w-16 text-right">前</span><span className="w-16 text-right">后</span><span className="w-16 text-right">Δ</span>
              </div>
              {tRows.map((r) => {
                const d = r.after - r.before
                const badge = { entered: ['进', 'text-ok'], exited: ['出', 'text-bad'], increased: ['加', 'text-ok'], decreased: ['减', 'text-warn'] }[r.kind]
                return (
                  <div key={r.symbol} className="flex items-center gap-3 border-t border-line py-2 text-[13.5px]">
                    <span className={`w-5 flex-none font-semibold ${badge[1]}`}>{badge[0]}</span>
                    <span className="flex-1 min-w-0 truncate">{r.symbol}</span>
                    <span className="num w-16 text-right text-ink-3">{r.before.toFixed(1)}</span>
                    <span className="num w-16 text-right">{r.after.toFixed(1)}</span>
                    <span className={`num w-16 text-right ${d >= 0 ? 'text-ok' : 'text-bad'}`}>{d >= 0 ? '+' : '−'}{Math.abs(d).toFixed(1)}</span>
                  </div>
                )
              })}
            </div>
          )
        )}
      </Card>

      {/* 发布 */}
      <div className="mt-6 flex items-center justify-end gap-3">
        <Link to={`/portfolios/${portfolioId}`} className="rounded-[11px] border border-line bg-surface px-5 py-2.5 text-[14px] text-ink-2">取消</Link>
        <button
          className="cursor-pointer rounded-[11px] border border-ink-1 bg-ink-1 px-6 py-2.5 text-[14px] font-semibold text-surface disabled:opacity-45"
          onClick={publish}
          disabled={!dirty || !name.trim()}
        >
          发布新版本
        </button>
      </div>
    </section>
  )
}

/** 组合编辑页三处状态（错误/加载/正常）共用的面包屑：总览 / 组合 / {名} / 编辑。 */
function EditCrumb({ id, name }: { id: number; name?: string }) {
  return (
    <Breadcrumb
      trail={[
        { label: '组合', to: '/portfolios' },
        { label: name ?? `组合 #${id}`, to: `/portfolios/${id}` },
        { label: '编辑' },
      ]}
    />
  )
}
