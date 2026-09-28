/** 账户自定义执行通知编辑页。保存有效函数时才启用自定义通知。 */

import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router'
import { Link, useNavigate } from '@/components/ui/nav'
import { AccountPageTitle } from '@/features/account/pageHead'
import { AREA, EditError, EditLoading, Row, Section } from '@/features/account/editUi'
import { getAccount, testAccountNotificationFunction, updateAccount, type AccountFeishuTestResult } from '@/lib/api/accounts'
import { usePolling } from '@/lib/hooks/usePolling'
import { useDomainStore } from '@/stores/domain'
import { useToastStore } from '@/stores/ui'

export function AccountEditNotificationPage() {
  const { id } = useParams()
  const accountId = Number(id)
  const navigate = useNavigate()
  const toast = useToastStore((state) => state.toast)
  const refreshAccounts = useDomainStore((state) => state.refreshAccounts)
  const account = usePolling(useCallback((signal: AbortSignal) => getAccount(accountId, signal), [accountId]), {
    queryKey: `account:${accountId}`,
    intervalMs: 0,
  })
  const [code, setCode] = useState<string | null>(null)
  const [test, setTest] = useState<AccountFeishuTestResult | null>(null)
  const [busy, setBusy] = useState<'test' | 'save' | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (account.data && code === null) setCode(account.data.execution_notification_code ?? '')
  }, [account.data, code])

  if (account.error && !account.data) return <EditError error={account.error} onRetry={account.refresh} />
  if (!account.data || code === null) return <EditLoading />

  const acc = account.data
  const empty = !code.trim()
  const runTest = async () => {
    setBusy('test')
    setError(null)
    try {
      setTest(await testAccountNotificationFunction(accountId, code))
    } catch (cause) {
      setTest({ ok: false, message: cause instanceof Error ? cause.message : String(cause) })
    } finally {
      setBusy(null)
    }
  }
  const save = async () => {
    setBusy('save')
    setError(null)
    try {
      await updateAccount(accountId, {
        execution_notification_mode: 'function',
        execution_notification_code: code,
      })
      toast('自定义执行通知已启用')
      void refreshAccounts()
      void navigate(`/accounts/${accountId}/edit`)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setBusy(null)
    }
  }

  return (
    <section className="pb-24">
      <Link to={`/accounts/${accountId}/edit`} className="mb-3 inline-block text-[13px] text-accent hover:underline">
        返回基本信息
      </Link>
      <AccountPageTitle accountId={accountId} page="自定义执行通知" name={acc.name} channel={acc.trade_channel} market={acc.market} />
      <p className="mt-3 text-[14px] text-ink-2">保存有效函数后启用自定义通知。函数负责自行发送消息；返回时当前通知方式不变。</p>
      <Section label="通知函数">
        <Row label="代码" top span>
          <p className="mb-2 text-[13px] text-ink-3">定义同步函数 notify(context)。context 包含 account、execution、assets、targets、positions、orders、trades、symbols 和 summary。</p>
          <textarea
            aria-label="执行通知函数"
            className={`${AREA} min-h-64 w-full resize-y`}
            value={code}
            spellCheck={false}
            onChange={(event) => { setCode(event.target.value); setTest(null); setError(null) }}
            placeholder={'def notify(context):\n    print(context["execution"]["status"])'}
          />
          <p className="mt-1 text-[12px] text-ink-3">试跑会实际执行当前代码，可能向外发送消息；样例事件中 is_test 为 true。</p>
          {test && <p className={`mt-2 text-[13px] ${test.ok ? 'text-accent' : 'text-warn'}`} role="status">{test.message}</p>}
          {error && <p className="mt-2 text-[13px] text-warn" role="alert">{error}</p>}
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button type="button" className="cursor-pointer rounded-[9px] border border-line px-4 py-2 text-[14px] text-ink-2 disabled:opacity-45" disabled={empty || busy !== null} onClick={() => void runTest()}>
              {busy === 'test' ? '试跑中…' : '试跑函数'}
            </button>
            <button type="button" className="cursor-pointer rounded-[9px] bg-ink-1 px-4 py-2 text-[14px] font-semibold text-surface disabled:opacity-45" disabled={empty || busy !== null} onClick={() => void save()}>
              {busy === 'save' ? '保存中…' : '保存并启用'}
            </button>
          </div>
        </Row>
      </Section>
    </section>
  )
}
