/**
 * 账户执行算法子页 /accounts/:id/edit/algorithm。
 *
 * 主交易 + 清仓算法完整编辑器；保存只 PATCH 算法相关字段，成功后回到编辑总览。
 */

import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router'
import { useNavigate } from '@/components/ui/nav'
import { Chip } from '@/components/ui/Card'
import { getAccount, updateAccount } from '@/lib/api/accounts'
import { usePolling } from '@/lib/hooks/usePolling'
import { useDomainStore } from '@/stores/domain'
import { useToastStore } from '@/stores/ui'
import { channelLabel } from '@/features/dashboard/display'
import { useChannelDescriptor } from '@/stores/channels'
import {
  describeAlgorithmRef,
  validateAlgorithmRef,
  type AlgorithmRef,
} from '@/features/setup/algorithms'
import { AlgorithmEditor } from '@/features/setup/AlgorithmEditor'
import {
  EditError,
  EditLoading,
  EditSaveBar,
  EditWorktopBar,
  Row,
  Section,
  editShellVtName,
} from '@/features/account/editUi'
import type { Account, AlgorithmSlot } from '@/types/api'

function refFromAccount(algo: unknown): AlgorithmRef | null {
  if (!algo || typeof algo !== 'object') return null
  const v = algo as { method?: unknown; params?: unknown }
  if (typeof v.method !== 'string') return null
  return { method: v.method, params: (v.params ?? {}) as Record<string, unknown> }
}

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
  const refreshAccounts = useDomainStore((s) => s.refreshAccounts)
  const account = usePolling(useCallback((s: AbortSignal) => getAccount(accountId, s), [accountId]), {
    queryKey: `account:${accountId}`,
    intervalMs: 0,
  })
  const acc = account.data
  const descriptor = useChannelDescriptor(acc?.trade_channel)

  const [ready, setReady] = useState(false)
  const [trade, setTrade] = useState<AlgorithmRef | null>(null)
  const [empty, setEmpty] = useState<AlgorithmRef | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<Error | null>(null)

  useEffect(() => {
    if (!acc || !descriptor || ready) return
    setTrade(refFromAccount(acc.algorithm) ?? descriptor.defaults.trade_algorithm)
    setEmpty(refFromAccount(acc.empty_positions_algorithm))
    setReady(true)
  }, [acc, descriptor, ready])

  if (account.error && !acc)
    return <EditError error={account.error} onRetry={account.refresh} />

  if (account.loading || !ready || !acc || !trade || !descriptor)
    return <EditLoading />

  const origTrade = refFromAccount(acc.algorithm) ?? descriptor.defaults.trade_algorithm
  const origEmpty = refFromAccount(acc.empty_positions_algorithm)

  const tradeChanged = norm(trade) !== norm(origTrade)
  const emptyChanged = norm(empty) !== norm(origEmpty)
  const dirty = tradeChanged || emptyChanged

  const err = algoParamError(trade) ?? algoParamError(empty)
  const changes: string[] = []
  if (tradeChanged) changes.push('下单算法已改')
  if (emptyChanged) changes.push(empty ? '清仓算法已改' : '清仓算法已清除')

  // 与总览入口同构摘要（随草稿变，FLIP 中列语义连续）。
  const tradeSum = describeAlgorithmRef(trade)
  const emptySum = describeAlgorithmRef(empty)
  const algoSummary = emptySum === '未设置' ? tradeSum : `${tradeSum} · 清仓 ${emptySum}`

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
      await updateAccount(accountId, patch)
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
    <section className="pb-24">
      <EditWorktopBar
        label="执行算法"
        hint="下单 / 清仓"
        summary={algoSummary}
        trailing={<Chip>{channelLabel(acc.trade_channel, acc.market)}</Chip>}
        shellVtName={editShellVtName(accountId, 'algorithm')}
        lead={`${acc.name} · 主交易与清仓分槽配置。保存只更新算法引用，不影响定时与启停。`}
      />

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
