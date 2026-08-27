import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams, useViewTransitionState } from 'react-router'
import { useNavigate } from '@/components/ui/nav'
import { Skeleton } from '@/components/ui/Skeleton'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { EditSaveBar, Section, TEXT } from '@/features/account/editUi'
import { CustomFunctionEditor } from '@/features/portfolio/CustomFunctionEditor'
import { usePolling } from '@/lib/hooks/usePolling'
import { getPortfolio, updatePortfolio } from '@/lib/api/portfolios'
import { useDomainStore } from '@/stores/domain'
import { useToastStore } from '@/stores/ui'

/** 编辑组合名称和唯一的目标计算函数。 */
export function PortfolioEditPage() {
  const { id } = useParams()
  const portfolioId = Number(id)
  const navigate = useNavigate()
  const toast = useToastStore((state) => state.toast)
  const portfolio = usePolling(useCallback((signal: AbortSignal) => getPortfolio(portfolioId, signal), [portfolioId]), {
    queryKey: `portfolio:${portfolioId}`,
    intervalMs: 0,
  })
  const accounts = useDomainStore((state) => state.accounts)
  const accountsError = useDomainStore((state) => state.accountsError)
  const refreshPortfolios = useDomainStore((state) => state.refreshPortfolios)
  const [ready, setReady] = useState(false)
  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const [original, setOriginal] = useState({ name: '', code: '' })
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<Error | null>(null)
  const pf = portfolio.data

  useEffect(() => {
    if (!pf || ready) return
    setName(pf.name)
    setCode(pf.custom_calc_py_code)
    setOriginal({ name: pf.name, code: pf.custom_calc_py_code })
    setReady(true)
  }, [pf, ready])

  const followers = useMemo(
    () => (accounts ?? []).filter((account) => account.portfolio_id === portfolioId),
    [accounts, portfolioId],
  )
  // 同名账户折叠成「名 ×n」，避免「test、test」式复读。
  const followerNames = useMemo(() => {
    const counts = new Map<string, number>()
    for (const account of followers) counts.set(account.name, (counts.get(account.name) ?? 0) + 1)
    return [...counts].map(([label, count]) => (count > 1 ? `${label} ×${count}` : label)).join('、')
  }, [followers])

  // 组合名共享元素：详情 hero ↔ 本页标题槽（同账户域「详情头 ↔ 标题槽」协议，仅过渡涉及详情页时挂名）。
  const tDetail = useViewTransitionState(`/portfolios/${portfolioId}`)

  const changes: string[] = []
  if (name.trim() !== original.name) changes.push('组合名称已改')
  if (code !== original.code) changes.push('目标计算函数已改')
  const blocked = !name.trim() || !code.trim() || accounts == null || Boolean(accountsError)

  const publish = async () => {
    if (blocked || saving || changes.length === 0) return
    setSaving(true)
    setSaveError(null)
    try {
      await updatePortfolio(portfolioId, { name: name.trim(), custom_calc_py_code: code })
      toast('组合已更新')
      void refreshPortfolios()
      navigate(`/portfolios/${portfolioId}`)
    } catch (error) {
      setSaveError(error instanceof Error ? error : new Error(String(error)))
    } finally {
      setSaving(false)
    }
  }

  if (portfolio.loading || (!pf && !portfolio.error) || (pf && !ready)) {
    return (
      <section className="mx-auto w-full max-w-[1440px] pb-24">
        <Skeleton className="h-6 w-44" />
        <Skeleton className="mt-4 h-4 w-64" />
        <Section label="组合名称">
          <div className="md:col-span-2">
            <Skeleton className="h-[34px] w-full" />
          </div>
        </Section>
        <Section label="目标计算函数">
          <div className="md:col-span-2">
            <Skeleton className="h-[300px] w-full" />
          </div>
        </Section>
      </section>
    )
  }
  if (portfolio.error || !pf) {
    return (
      <section>
        <ErrorNotice title="组合加载失败" error={portfolio.error ?? new Error('组合不存在')} onRetry={portfolio.refresh} />
      </section>
    )
  }

  return (
    <section className="mx-auto w-full max-w-[1440px]">
      <h1 className="text-[19px] font-[640]">
        组合 ·{' '}
        <span style={tDetail ? { viewTransitionName: `portfolio-name-${portfolioId}` } : undefined}>{pf.name}</span>
      </h1>

      {/* 影响范围：琥珀只在真有账户跟随时出现，量级收敛到左边条；无人跟随保持中性。 */}
      <div className="mt-4">
        {accountsError ? (
          <p className="border-l-2 border-warn pl-2.5 text-[14px] leading-5 text-warn">
            影响范围 · 绑定关系暂不可用，恢复前无法保存
          </p>
        ) : accounts == null ? (
          <Skeleton className="h-4 w-64" />
        ) : followers.length > 0 ? (
          <p className="border-l-2 border-warn pl-2.5 text-[14px] leading-5 text-ink-1">
            影响范围 · 此组合被 <b>{followers.length}</b> 个账户使用：{followerNames}。
            <span className="text-ink-2">保存后，这些账户会在下次调仓时执行新函数。</span>
          </p>
        ) : (
          <p className="border-l-2 border-line pl-2.5 text-[14px] leading-5 text-ink-3">
            影响范围 · 当前没有账户使用此组合，保存只影响之后绑定的账户。
          </p>
        )}
      </div>

      <Section label="组合名称">
        <div className="md:col-span-2">
          <input
            className={TEXT}
            value={name}
            onChange={(event) => {
              setName(event.target.value)
              setSaveError(null)
            }}
          />
        </div>
      </Section>

      <Section label="目标计算函数">
        <div className="md:col-span-2">
          <CustomFunctionEditor
            code={code}
            onChange={(value) => {
              setCode(value)
              setSaveError(null)
            }}
          />
        </div>
      </Section>

      <EditSaveBar
        changes={changes}
        blocked={blocked}
        cancelTo={`/portfolios/${portfolioId}`}
        onSave={() => void publish()}
        saving={saving}
        error={saveError}
      />
    </section>
  )
}
