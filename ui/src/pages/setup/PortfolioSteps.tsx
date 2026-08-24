import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from '@/components/ui/nav'
import { WizardPage, WizardNav } from '@/features/setup/WizardNav'
import { ConfirmModal, type ConfirmSpec } from '@/components/ui/ConfirmModal'
import { CustomFunctionEditor } from '@/features/portfolio/CustomFunctionEditor'
import { OverflowText } from '@/components/ui/OverflowText'
import { createPortfolio } from '@/lib/api/portfolios'
import { useWizardStore } from '@/stores/wizard'
import { useToastStore } from '@/stores/ui'
import { useDomainStore } from '@/stores/domain'
import { useChannelCatalogStore } from '@/stores/channels'
import {
  portfolioMarketOptions,
  portfolioTemplate,
  selectPortfolioMarket,
  type PortfolioMarketOption,
} from '@/features/portfolio/portfolioMarkets'

function usePortfolioMarkets() {
  const channels = useChannelCatalogStore((state) => state.channels)
  return useMemo(() => portfolioMarketOptions(channels ?? []), [channels])
}

function MarketChoiceGroup({
  value,
  options,
  onChange,
}: {
  value: string
  options: PortfolioMarketOption[]
  onChange: (value: string) => void
}) {
  return (
    <div role="radiogroup" aria-label="市场" className="grid gap-px overflow-hidden rounded-[8px] border border-line bg-line sm:grid-cols-3">
      {options.map((option) => {
        const selected = option.value === value
        const examples = option.exampleSymbols.slice(0, 2).join(' · ')
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            className={`relative flex min-h-[76px] min-w-0 items-center bg-surface px-4 py-3 text-left transition-colors ${
              selected ? 'bg-accent-soft' : 'hover:bg-bg-subtle'
            }`}
            onClick={() => onChange(option.value)}
          >
            <span className="min-w-0 flex-1">
              <span className={`block text-[14px] font-[620] ${selected ? 'text-ink-1' : 'text-ink-2'}`}>{option.label}</span>
              <OverflowText className="mt-1 text-[12px] text-ink-3" text={examples} />
            </span>
            {selected && <span aria-hidden className="absolute inset-y-0 left-0 w-0.5 bg-accent sm:inset-x-0 sm:top-auto sm:bottom-0 sm:h-0.5 sm:w-auto" />}
          </button>
        )
      })}
    </div>
  )
}

/* ---------------- 1 命名 ---------------- */
export function PfName() {
  const { pf, setPf } = useWizardStore()
  const markets = usePortfolioMarkets()
  const loading = useChannelCatalogStore((state) => state.loading)
  const error = useChannelCatalogStore((state) => state.error)
  const refresh = useChannelCatalogStore((state) => state.refresh)
  const selectedMarket = markets.find((market) => market.value === pf.market) ?? null

  useEffect(() => {
    if (markets.length === 0) return
    const nextMarket = selectedMarket ?? markets[0]
    const next = selectPortfolioMarket(pf, nextMarket, markets)
    if (
      next.market !== pf.market ||
      next.customCode !== pf.customCode ||
      next.templateMarket !== pf.templateMarket
    ) {
      setPf({ ...next, verified: null })
    }
  }, [markets, pf, selectedMarket, setPf])

  const changeMarket = (market: string) => {
    const nextMarket = markets.find((option) => option.value === market)
    if (!nextMarket) return
    setPf({ ...selectPortfolioMarket(pf, nextMarket, markets), verified: null })
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1">
        <WizardPage kicker="组合设置 · 1 / 3" title="先给组合起个名字" lead="组合是「交易什么」的来源——一套目标持仓，可被多个账户复用。">
          <div className="max-w-[520px]">
            <label className="mb-1.5 block text-[13px] text-ink-2">组合名称</label>
            <input
              className="w-full rounded-[11px] border border-ink-3/30 bg-surface px-[18px] py-4 text-[22px] font-[550] outline-none focus:border-ink-2"
              value={pf.name}
              onChange={(e) => setPf({ name: e.target.value })}
              placeholder="例如：我的趋势组合"
            />
            <label className="mb-1.5 mt-5 block text-[13px] text-ink-2">市场</label>
            <MarketChoiceGroup
              value={pf.market}
              options={markets}
              onChange={changeMarket}
            />
            {loading && markets.length === 0 && <p className="mt-2 text-[13px] text-ink-2">加载市场…</p>}
            {error && markets.length === 0 && (
              <button type="button" className="mt-2 text-[13px] text-warn hover:underline" onClick={() => void refresh()}>
                市场目录加载失败，点击重试
              </button>
            )}
          </div>
        </WizardPage>
      </div>
      <WizardNav nextTo="/setup/pf/define" nextDisabled={!pf.name.trim() || selectedMarket == null} />
    </div>
  )
}

/* ---------------- 2 定义策略 ---------------- */
export function PfDefine() {
  const { pf, setPf } = useWizardStore()
  const markets = usePortfolioMarkets()
  const selectedMarket = markets.find((market) => market.value === pf.market) ?? null
  const navigate = useNavigate()
  const toast = useToastStore((s) => s.toast)
  const refreshPortfolios = useDomainStore((s) => s.refreshPortfolios)
  const [confirm, setConfirm] = useState<ConfirmSpec | null>(null)

  const doCreate = async () => {
    if (!selectedMarket) {
      toast('当前市场不可用，请返回上一步重新选择')
      return
    }
    try {
      const created = await createPortfolio({
        name: pf.name,
        market: selectedMarket.label,
        custom_calc_py_code: pf.customCode,
      })
      setPf({ savedId: created.id })
      toast('组合已创建')
      void refreshPortfolios()
      navigate('/setup/pf/done')
    } catch (e) {
      toast(`创建失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  const onNext = async () => {
    // 软拦截：没试跑通过就创建，先确认——别把没跑过的组合绑上真钱。
    if (!pf.verified?.ok) {
      setConfirm({
        title: '这个组合还没试跑通过',
        body: '试跑能确认它此刻会产出什么目标持仓、有没有报错。确定不试跑就继续创建吗？',
        okText: '仍然创建',
        onConfirm: () => {
          void doCreate()
        },
      })
      return
    }
    await doCreate()
  }

  const canNext = pf.customCode.trim().length > 0 && selectedMarket != null
  const templateMismatch = pf.templateMarket !== null && pf.templateMarket !== pf.market

  return (
    <div className="flex h-full flex-col">
      {/* 预留滚动条槽位：验证结果出现使内容超出一屏、滚动条切入时，居中列不会左右抖动。 */}
      <div className="flex-1 overflow-y-auto [scrollbar-gutter:stable]">
        <WizardPage kicker="组合设置 · 2 / 3" title="这个组合交易什么？">
          <div
            inert={!templateMismatch}
            className={`grid transition-[grid-template-rows] duration-200 ease-[cubic-bezier(.4,0,.2,1)] motion-reduce:transition-none ${templateMismatch ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}
          >
            <div className="min-h-0 overflow-hidden">
              <div className="mb-4 flex items-center justify-between gap-4 border-l-[3px] border-warn bg-warn-soft px-4 py-3 text-[13px]">
                <span className="text-ink-2">当前代码来自其他市场。</span>
                <button
                  type="button"
                  className="shrink-0 font-[550] text-warn hover:underline"
                  onClick={() => {
                    if (!selectedMarket) return
                    setPf({
                      customCode: portfolioTemplate(selectedMarket),
                      templateMarket: selectedMarket.value,
                      verified: null,
                    })
                  }}
                >
                  换成{selectedMarket?.label ?? '当前市场'}示例
                </button>
              </div>
            </div>
          </div>
          <CustomFunctionEditor
            code={pf.customCode}
            onChange={(customCode) => setPf({ customCode, verified: null })}
            onVerifiedChange={(v) => setPf({ verified: v })}
          />
        </WizardPage>
      </div>
      <WizardNav prevTo="/setup/pf/name" nextLabel="创建" onNext={onNext} nextDisabled={!canNext} />
      <ConfirmModal spec={confirm} onClose={() => setConfirm(null)} />
    </div>
  )
}

/* ---------------- 3 完成 ---------------- */
export function PfDone() {
  const { pf } = useWizardStore()
  return (
    <div className="py-16 text-center">
      <div className="text-[56px]">🎯</div>
      <h2 className="mt-3.5 text-[24px] font-semibold">组合已保存</h2>
      <p className="mt-2 text-ink-2">
        {pf.savedId != null ? `“${pf.name}” 已创建。` : ''}去「账户设置」把它绑定到交易所即可开跑。
      </p>
      <div className="mt-6 flex justify-center gap-3">
        {pf.savedId != null && (
          <Link to={`/portfolios/${pf.savedId}`} className="rounded-[11px] border border-line bg-surface px-5 py-2.5 text-[14px] text-ink-2">
            查看组合
          </Link>
        )}
        <Link to="/setup/acct/channel" className="rounded-[11px] border border-ink-1 bg-ink-1 px-5 py-2.5 text-[14px] font-semibold text-surface">
          去新建账户 →
        </Link>
      </div>
    </div>
  )
}
