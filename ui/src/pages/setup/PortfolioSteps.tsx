import { useEffect, useState } from 'react'
import { Link, useNavigate } from '@/components/ui/nav'
import { WizardPage, WizardNav } from '@/features/setup/WizardNav'
import { ChoiceGroup } from '@/components/ui/ChoiceGroup'
import { ConfirmModal, type ConfirmSpec } from '@/components/ui/ConfirmModal'
import { StrategyComposer } from '@/features/portfolio/StrategyComposer'
import { peekDataSourceAvailable } from '@/lib/api/init'
import { createPortfolio } from '@/lib/api/portfolios'
import { useWizardStore } from '@/stores/wizard'
import { useToastStore } from '@/stores/ui'
import { useDomainStore } from '@/stores/domain'
import { getChannelForMarket } from '@/stores/channels'

const MARKETS = ['加密货币', 'A股', '期货']

/* ---------------- 1 命名 ---------------- */
export function PfName() {
  const { pf, setPf } = useWizardStore()
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
            <ChoiceGroup
              value={pf.market}
              options={MARKETS.map((m) => ({ value: m, label: m }))}
              onChange={(m) => setPf({ market: m })}
            />
          </div>
        </WizardPage>
      </div>
      <WizardNav nextTo="/setup/pf/define" nextDisabled={!pf.name.trim()} />
    </div>
  )
}

/* ---------------- 2 定义策略 ---------------- */
export function PfDefine() {
  const { pf, setPf } = useWizardStore()
  const navigate = useNavigate()
  const toast = useToastStore((s) => s.toast)
  const refreshPortfolios = useDomainStore((s) => s.refreshPortfolios)
  const [confirm, setConfirm] = useState<ConfirmSpec | null>(null)

  // 数据源能力位：null（启动探测失败）按允许处理，兜底交后端护栏。
  const dsAvailable = peekDataSourceAvailable() !== false
  // 无数据源时强制自定义逻辑；effMode 兜住 store 纠正的时序，并回写 store 供后续步骤一致。
  const effMode: 'compose' | 'custom' = dsAvailable ? pf.mode : 'custom'
  useEffect(() => {
    if (!dsAvailable && pf.mode !== 'custom') setPf({ mode: 'custom' })
  }, [dsAvailable, pf.mode, setPf])

  const doCreate = async () => {
    try {
      const created = await createPortfolio({
        name: pf.name,
        market: pf.market,
        custom_calc_py_code: effMode === 'custom' ? pf.customCode : null,
        strategies:
          effMode === 'custom'
            ? []
            : pf.strategies.filter((r) => r.name.trim()).map((r) => ({ name: r.name.trim(), weight: r.weight / 100 })),
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

  const canNext = effMode === 'custom' ? pf.customCode.trim().length > 0 : pf.strategies.some((r) => r.name.trim())

  return (
    <div className="flex h-full flex-col">
      {/* 预留滚动条槽位：验证结果出现使内容超出一屏、滚动条切入时，居中列不会左右抖动。 */}
      <div className="flex-1 overflow-y-auto [scrollbar-gutter:stable]">
        <WizardPage kicker="组合设置 · 2 / 3" title="这个组合交易什么？">
          <StrategyComposer
            mode={effMode}
            onModeChange={(m) => setPf({ mode: m })}
            strategies={pf.strategies}
            onStrategiesChange={(s) => setPf({ strategies: s })}
            customCode={pf.customCode}
            onCustomCodeChange={(c) => setPf({ customCode: c })}
            tradeChannel={getChannelForMarket(pf.market)}
            onVerifiedChange={(v) => setPf({ verified: v })}
            allowCompose={dsAvailable}
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
