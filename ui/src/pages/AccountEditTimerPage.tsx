/**
 * 账户定时子页 /accounts/:id/edit/timer。
 *
 * 完整 :component:`TimerEditor`；保存只 PATCH ``cron_expr``，成功后回到编辑总览。
 */

import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router'
import { useNavigate } from '@/components/ui/nav'
import { getAccount, updateAccount } from '@/lib/api/accounts'
import { usePolling } from '@/lib/hooks/usePolling'
import { useDomainStore } from '@/stores/domain'
import { useToastStore } from '@/stores/ui'
import { AccountPageTitle } from '@/features/account/pageHead'
import {
  cronExprEqual,
  describeCron,
  parseTimerIntent,
  timerStateToCronExpr,
  type TimerEditorState,
} from '@/features/setup/cron'
import { TimerEditor, timerEditorError } from '@/features/setup/TimerEditor'
import { useChannelDescriptor } from '@/stores/channels'
import {
  EditError,
  EditLoading,
  EditSaveBar,
  EditSynopsis,
} from '@/features/account/editUi'

export function AccountEditTimerPage() {
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
  const title = (
    <div className="flex flex-wrap items-baseline gap-3">
      <AccountPageTitle
        accountId={accountId}
        page="定时节奏"
        name={acc?.name ?? cachedAccount?.name}
        channel={acc?.trade_channel ?? cachedAccount?.trade_channel}
        market={acc?.market ?? cachedAccount?.market}
      />
    </div>
  )

  const [ready, setReady] = useState(false)
  const [timer, setTimer] = useState<TimerEditorState | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<Error | null>(null)

  useEffect(() => {
    if (!acc || !descriptor || ready) return
    setTimer(parseTimerIntent(descriptor.schedule.kind, acc.cron_expr ?? '', descriptor.schedule.night))
    setReady(true)
  }, [acc, descriptor, ready])

  if (account.error && !acc)
    return <EditError error={account.error} onRetry={account.refresh} />

  if (account.loading || !ready || !acc || !timer || !descriptor)
    return (
      <section className="pb-24">
        {title}
        <EditLoading bare />
      </section>
    )

  const scheduleKind = descriptor.schedule.kind
  const cronNext = timerStateToCronExpr(scheduleKind, timer, descriptor.schedule.night)
  const cronPrev = acc.cron_expr ?? ''
  const dirty = !cronExprEqual(cronNext, cronPrev)
  const err = timerEditorError(timer)
  const changes = dirty ? [cronNext ? '定时节奏已改' : '关闭自动调仓节奏'] : []

  // 与总览入口同构摘要（随草稿变）。
  const timerSummary = !cronNext.trim()
    ? '已关 · 仅手动'
    : (describeCron(scheduleKind, cronNext, descriptor.schedule.night) ?? '自定义执行节奏')

  const save = async () => {
    if (err) return toast(`执行节奏有误：${err}`)
    if (!dirty) return toast('没有改动')
    setSaving(true)
    setSaveError(null)
    try {
      await updateAccount(accountId, { cron_expr: cronNext })
      toast(cronNext ? '节奏已更新' : '已关闭自动调仓节奏')
      void refreshAccounts()
      account.refresh()
      navigate(`/accounts/${accountId}/edit`)
    } catch (e) {
      setSaveError(e instanceof Error ? e : new Error(String(e)))
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="pb-24">
      {title}
      <EditSynopsis note="时间均为北京时间；保存只更新自动执行计划，不改启停状态。">
        {timerSummary}
      </EditSynopsis>

      <div className="mt-6">
        <TimerEditor
          tradeChannel={acc.trade_channel}
          scheduleKind={scheduleKind}
          nightSchedule={descriptor.schedule.night}
          value={timer}
          onChange={(next) =>
            { setSaveError(null); setTimer((prev) => (typeof next === 'function' ? next(prev as TimerEditorState) : next)) }
          }
        />
      </div>

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
