/**
 * 账户定时子页 /accounts/:id/edit/timer。
 *
 * 完整 :component:`TimerEditor`；保存只 PATCH ``cron_expr``，成功后回到编辑总览。
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
  EditBreadcrumb,
  EditError,
  EditLoading,
  EditSaveBar,
  EditWorktopBar,
  editShellVtName,
} from '@/features/account/editUi'

export function AccountEditTimerPage() {
  const { id } = useParams()
  const accountId = Number(id)
  const navigate = useNavigate()
  const toast = useToastStore((s) => s.toast)
  const refreshAccounts = useDomainStore((s) => s.refreshAccounts)
  const account = usePolling(useCallback((s: AbortSignal) => getAccount(accountId, s), [accountId]), 0)
  const acc = account.data
  const descriptor = useChannelDescriptor(acc?.trade_channel)

  const [ready, setReady] = useState(false)
  const [timer, setTimer] = useState<TimerEditorState | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!acc || !descriptor || ready) return
    setTimer(parseTimerIntent(descriptor.schedule.kind, acc.cron_expr ?? ''))
    setReady(true)
  }, [acc, descriptor, ready])

  if (account.error && !acc)
    return <EditError id={accountId} message={account.error.message} />

  if (account.loading || !ready || !acc || !timer || !descriptor)
    return <EditLoading id={accountId} leaf="定时" />

  const scheduleKind = descriptor.schedule.kind
  const cronNext = timerStateToCronExpr(scheduleKind, timer)
  const cronPrev = acc.cron_expr ?? ''
  const dirty = !cronExprEqual(cronNext, cronPrev)
  const err = timerEditorError(timer)
  const changes = dirty ? [cronNext ? '定时节奏已改' : '关闭自动调仓节奏'] : []

  // 与总览入口同构摘要（随草稿变）。
  const timerSummary = !cronNext.trim()
    ? '已关 · 仅手动'
    : (describeCron(scheduleKind, cronNext) ?? '自定义节奏')

  const save = async () => {
    if (err) return toast(`定时表达式有误：${err}`)
    if (!dirty) return toast('没有改动')
    setSaving(true)
    try {
      await updateAccount(accountId, { cron_expr: cronNext })
      toast(cronNext ? '节奏已更新' : '已关闭自动调仓节奏')
      void refreshAccounts()
      account.refresh()
      navigate(`/accounts/${accountId}/edit`)
    } catch (e) {
      toast(`更新失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="pb-24">
      <EditBreadcrumb id={accountId} name={acc.name} leaf="定时" />
      <EditWorktopBar
        label="定时"
        hint="自动调仓"
        summary={timerSummary}
        trailing={<Chip>{channelLabel(acc.trade_channel, acc.market)}</Chip>}
        shellVtName={editShellVtName(accountId, 'timer')}
        lead={`${acc.name} · 完整快捷 / 高级配置 · 时间均为北京时间。保存只更新排程表达式，不改启停状态。`}
      />

      <div className="mt-6">
        <TimerEditor
          tradeChannel={acc.trade_channel}
          scheduleKind={scheduleKind}
          value={timer}
          onChange={(next) =>
            setTimer((prev) => (typeof next === 'function' ? next(prev as TimerEditorState) : next))
          }
        />
      </div>

      <EditSaveBar
        changes={changes}
        blocked={Boolean(err)}
        cancelTo={`/accounts/${accountId}/edit`}
        onSave={() => void save()}
        saving={saving}
      />
    </section>
  )
}
