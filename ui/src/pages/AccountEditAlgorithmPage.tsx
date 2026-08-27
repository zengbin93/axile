/**
 * 账户执行算法子页 /accounts/:id/edit/algorithm。
 *
 * 主交易 + 清仓算法完整编辑器；保存只 PATCH 算法相关字段，成功后回到编辑总览。
 */

import { useCallback, useEffect, useState, type CSSProperties } from 'react'
import { useParams, useViewTransitionState } from 'react-router'
import { useNavigate } from '@/components/ui/nav'
import { getAccount, updateAccount } from '@/lib/api/accounts'
import { usePolling } from '@/lib/hooks/usePolling'
import { useDomainStore } from '@/stores/domain'
import { useToastStore } from '@/stores/ui'
import { AccountPageTitle } from '@/features/account/pageHead'
import { useChannelDescriptor } from '@/stores/channels'
import {
  accountConfigVtName,
  readAccountConfigSummary,
  writeAccountConfigSummary,
} from '@/features/account/configSummary'
import {
  algorithmRefOf,
  describeAlgorithmRef,
  validateAlgorithmRef,
  type AlgorithmRef,
} from '@/features/setup/algorithms'
import { AlgorithmEditor } from '@/features/setup/AlgorithmEditor'
import {
  EditError,
  EditLoading,
  EditSaveBar,
  EditSynopsis,
  Row,
  Section,
} from '@/features/account/editUi'
import type { Account, AlgorithmSlot } from '@/types/api'

function norm(v: unknown): string {
  return JSON.stringify(v ?? null)
}

function algoParamError(algo: AlgorithmRef | null): string | null {
  if (!algo) return null
  return validateAlgorithmRef(algo)
}

export function AccountEditAlgorithmPage() {
  const { id } = useParams()
  const accountId = Number(id)
  const navigate = useNavigate()
  const toast = useToastStore((s) => s.toast)
  const accounts = useDomainStore((s) => s.accounts)
  const refreshAccounts = useDomainStore((s) => s.refreshAccounts)
  const account = usePolling(useCallback((s: AbortSignal) => getAccount(accountId, s), [accountId]), {
    queryKey: `account:${accountId}`,
    intervalMs: 0,
  })
  const acc = account.data
  const cachedAccount = accounts?.find((item) => item.account_id === accountId) ?? null
  const descriptor = useChannelDescriptor(acc?.trade_channel)

  // Hero 配置带「算法」值 ↔ 本页「当前配置 · 下单」摘要的 FLIP：门控与缓存协议
  // 同浅配置页（见 AccountEditPage）——首帧落点靠缓存，真源/保存响应写新值。
  const tSelf = useViewTransitionState(`/accounts/${accountId}/edit/algorithm`)
  const cachedConfig = acc ? null : readAccountConfigSummary(accountId)
  useEffect(() => {
    if (acc && descriptor) {
      writeAccountConfigSummary(accountId, acc, {
        showShortLeverage: descriptor.ui.show_short_leverage,
      })
    }
  }, [acc, descriptor, accountId])
  const title = (
    <div className="flex flex-wrap items-baseline gap-3">
      <AccountPageTitle
        accountId={accountId}
        page="执行算法"
        name={acc?.name ?? cachedAccount?.name}
        channel={acc?.trade_channel ?? cachedAccount?.trade_channel}
        market={acc?.market ?? cachedAccount?.market}
      />
    </div>
  )

  const [ready, setReady] = useState(false)
  const [trade, setTrade] = useState<AlgorithmRef | null>(null)
  const [empty, setEmpty] = useState<AlgorithmRef | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<Error | null>(null)

  useEffect(() => {
    if (!acc || !descriptor || ready) return
    setTrade(algorithmRefOf(acc.algorithm) ?? descriptor.defaults.trade_algorithm)
    setEmpty(algorithmRefOf(acc.empty_positions_algorithm))
    setReady(true)
  }, [acc, descriptor, ready])

  if (account.error && !acc)
    return <EditError error={account.error} onRetry={account.refresh} />

  const isReady = !(account.loading || !ready || !acc || !trade || !descriptor)
  // 「当前配置」摘要常挂：加载（缓存）→ 就绪（草稿）只换文本、不换节点。
  // view transition 的具名捕获认 DOM 节点——摘要若随加载/就绪分支整体重挂，
  // 进行中的组动画会被浏览器杀掉（表现就是「正向 FLIP 不飞」）。
  // 兜底链必须是 草稿 → 真源 → 缓存：acc 已到位而草稿未初始化的中间态若直接掉缓存
  // （cachedConfig 在 acc 存在时为 null），摘要会消失一个 commit、换节点杀动画。
  const savedTradeSum = acc ? describeAlgorithmRef(algorithmRefOf(acc.algorithm)) : null
  const tradeSynopsis = trade
    ? describeAlgorithmRef(trade)
    : (savedTradeSum ?? cachedConfig?.algorithm ?? null)
  // 「下单」值与 hero 配置带同文才挂共享名（草稿改了就退化为整页交叉淡，不做内容 morph）。
  const tradeSame = trade == null || tradeSynopsis === savedTradeSum
  const tradeVtStyle: CSSProperties | undefined =
    tSelf && tradeSame
      ? { viewTransitionName: accountConfigVtName(accountId, 'algorithm') }
      : undefined

  /** 标题 + 当前配置摘要：加载与就绪两态共用（同位同节点）；清仓行待就绪后追加。 */
  const synopsis = tradeSynopsis != null && (
    <EditSynopsis note={isReady ? '保存只更新算法引用，不影响定时与启停。' : undefined}>
      <div className="grid grid-cols-[3rem_minmax(0,1fr)] gap-x-3 gap-y-0.5">
        <span className="font-normal text-ink-3">下单</span>
        <span className="inline-block" style={tradeVtStyle}>
          {tradeSynopsis}
        </span>
        {isReady && (
          <>
            <span className="font-normal text-ink-3">清仓</span>
            <span>{describeAlgorithmRef(empty)}</span>
          </>
        )}
      </div>
    </EditSynopsis>
  )

  if (!isReady)
    return (
      <section className="mx-auto max-w-[900px] pb-24">
        {title}
        {synopsis}
        <EditLoading bare />
      </section>
    )

  const origTrade = algorithmRefOf(acc.algorithm) ?? descriptor.defaults.trade_algorithm
  const origEmpty = algorithmRefOf(acc.empty_positions_algorithm)

  const tradeChanged = norm(trade) !== norm(origTrade)
  const emptyChanged = norm(empty) !== norm(origEmpty)
  const dirty = tradeChanged || emptyChanged

  const err = algoParamError(trade) ?? algoParamError(empty)
  const changes: string[] = []
  if (tradeChanged) changes.push('下单算法已改')
  if (emptyChanged) changes.push(empty ? '清仓算法已改' : '清仓算法已清除')

  const save = async () => {
    if (err) return toast(`算法参数非法：${err}`)
    if (!dirty) return toast('没有改动')
    const patch: Partial<Account> = {}
    if (tradeChanged) patch.algorithm = trade as unknown as Record<string, unknown>
    if (emptyChanged) {
      patch.empty_positions_algorithm = empty
        ? (empty as unknown as Record<string, unknown>)
        : null
    }
    setSaving(true)
    setSaveError(null)
    try {
      const updated = await updateAccount(accountId, patch)
      // 保存响应直接写摘要缓存：返回详情时 hero「算法」值首帧即新值，FLIP 落地同文。
      writeAccountConfigSummary(accountId, updated, {
        showShortLeverage: descriptor.ui.show_short_leverage,
      })
      toast('执行算法已更新')
      void refreshAccounts()
      account.refresh()
      navigate(`/accounts/${accountId}/edit`)
    } catch (e) {
      setSaveError(e instanceof Error ? e : new Error(String(e)))
    } finally {
      setSaving(false)
    }
  }

  const slotRow = (
    slot: AlgorithmSlot,
    label: string,
    value: AlgorithmRef | null,
    onChange: (v: AlgorithmRef | null) => void,
  ) => (
    <Row label={label} top span>
      <AlgorithmEditor
        slot={slot}
        channel={acc.trade_channel}
        value={slot === 'trade' ? (value ?? descriptor.defaults.trade_algorithm) : value}
        allowClear={slot === 'empty'}
        onChange={onChange}
      />
    </Row>
  )

  return (
    <section className="mx-auto max-w-[900px] pb-24">
      {title}
      {synopsis}

      <Section label="主交易">
        {slotRow('trade', '下单算法', trade, (v) => { setSaveError(null); setTrade(v ?? descriptor.defaults.trade_algorithm) })}
      </Section>
      <Section label="清仓">
        {slotRow('empty', '清仓算法', empty, (value) => { setSaveError(null); setEmpty(value) })}
      </Section>

      <EditSaveBar
        changes={changes}
        blocked={Boolean(err)}
        cancelTo={`/accounts/${accountId}/edit`}
        onSave={() => void save()}
        saving={saving}
        error={saveError}
      />
    </section>
  )
}
