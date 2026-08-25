import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router'
import { Breadcrumb } from '@/components/ui/Breadcrumb'
import { Card, SectionLabel } from '@/components/ui/Card'
import { useNavigate } from '@/components/ui/nav'
import { Skeleton, SkeletonLines } from '@/components/ui/Skeleton'
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
  const dirty = name.trim() !== original.name || code !== original.code

  const publish = async () => {
    if (!name.trim() || !code.trim() || saving || accounts == null || accountsError) return
    setSaving(true)
    try {
      await updatePortfolio(portfolioId, { name: name.trim(), custom_calc_py_code: code })
      toast('组合已更新')
      void refreshPortfolios()
      navigate(`/portfolios/${portfolioId}`)
    } catch (error) {
      toast(`保存失败：${error instanceof Error ? error.message : String(error)}`)
      setSaving(false)
    }
  }

  if (portfolio.loading || (!pf && !portfolio.error) || (pf && !ready)) {
    return (
      <section>
        <EditCrumb id={portfolioId} name={pf?.name} />
        <p className="mt-3 text-[14px] text-warn">组合加载失败：{portfolio.error?.message ?? '不存在'}</p>
      </section>
    )
  }
  if (portfolio.error || !pf) {
    return (
      <section>
        <EditCrumb id={portfolioId} name={pf?.name} />
        <Card className="mt-3 px-6 py-4"><SkeletonLines rows={2} /></Card>
        <SectionLabel>组合名称</SectionLabel>
        <Skeleton className="h-12 w-full max-w-[520px]" />
        <Card className="mt-6 px-6 py-4"><SkeletonLines rows={5} /></Card>
      </section>
    )
  }

  return (
    <section>
      <EditCrumb id={portfolioId} name={pf.name} />
      <Card className="mt-3 border border-warn/30 bg-warn-tint px-6 py-4">
        <div className="text-[14px]">
          <b>影响范围</b> · {accountsError ? (
            <span className="text-warn">绑定关系暂不可用</span>
          ) : accounts == null ? (
            <Skeleton className="inline-block h-4 w-36 align-middle" />
          ) : (
            <>此组合被 <b>{followers.length}</b> 个账户使用{followers.length > 0 && `：${followers.map((account) => account.name).join('、')}`}</>
          )}
        </div>
        <div className="mt-1 text-[13px] text-ink-2">保存后，这些账户会在下次调仓时执行新函数。</div>
      </Card>

      <SectionLabel>组合名称</SectionLabel>
      <input
        className="w-full max-w-[520px] rounded-[8px] border border-ink-3/30 bg-surface px-4 py-3 text-[16px] font-[550] outline-none focus:border-ink-2"
        value={name}
        onChange={(event) => setName(event.target.value)}
      />

      <SectionLabel>目标计算函数</SectionLabel>
      <Card className="px-6 py-5">
        <CustomFunctionEditor code={code} onChange={setCode} />
      </Card>

      <div className="mt-6 flex items-center justify-end gap-3 border-t border-line pt-4">
        <span className="mr-auto text-[13px] text-ink-3">{dirty ? '有未保存修改' : '没有修改'}</span>
        <button
          className="cursor-pointer rounded-[8px] border-0 bg-ink-1 px-5 py-2.5 text-[14px] font-[550] text-surface disabled:opacity-45"
          disabled={!dirty || !name.trim() || !code.trim() || saving || accounts == null || Boolean(accountsError)}
          onClick={publish}
        >
          {saving ? '保存中…' : '保存修改'}
        </button>
      </div>
    </section>
  )
}

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
