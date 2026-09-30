/** 账户自定义执行通知工作台：左侧试跑，右侧编辑代码。 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router'
import { Check, Circle, Play, TriangleAlert } from 'lucide-react'
import { Link } from '@/components/ui/nav'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { InkRewrite } from '@/components/ui/InkRewrite'
import { PYTHON_RUN_STYLE, pythonRunStatus, type PythonEditorHandle } from '@/components/ui/PythonFunctionEditor'
import { PythonWorkbench } from '@/components/ui/PythonWorkbench'
import { usePythonDraft, usePythonRun, usePythonSave } from '@/components/ui/pythonWorkbenchState'
import { PythonWorkbenchPane } from '@/components/ui/PythonWorkbenchPane'
import { WorkbenchPanel } from '@/components/ui/WorkbenchPanel'
import { AccountPageTitle } from '@/features/account/pageHead'
import { EditError, EditLoading } from '@/features/account/editUi'
import { notificationDraft } from '@/features/account/notificationDraft'
import { NOTIFICATION_STATUS_LABEL } from '@/features/account/notificationStatus'
import { getAccount, getDefaultAccountNotification, testAccountNotificationFunction, updateAccount, type AccountFeishuTestResult } from '@/lib/api/accounts'
import { usePolling } from '@/lib/hooks/usePolling'
import { useDomainStore } from '@/stores/domain'
import { useToastStore } from '@/stores/ui'

const INSPECTOR_WIDTH_KEY = 'axon.notificationWorkbench.inspectorWidth'

export function AccountEditNotificationPage() {
  const { id } = useParams()
  const accountId = Number(id)
  const toast = useToastStore((state) => state.toast)
  const refreshAccounts = useDomainStore((state) => state.refreshAccounts)
  const account = usePolling(useCallback((signal: AbortSignal) => getAccount(accountId, signal), [accountId]), {
    queryKey: `account:${accountId}`,
    intervalMs: 0,
  })
  const draftState = usePythonDraft<string | null>(null)
  const { draft: code, setDraft: setCode, baseline: savedCode, setBaseline: setSavedCode } = draftState
  const saveState = usePythonSave()
  const [defaultCode, setDefaultCode] = useState<string | null>(null)
  const [resultOpen, setResultOpen] = useState(true)
  const [editorStatus, setEditorStatus] = useState<HTMLDivElement | null>(null)
  const [resizingPanels, setResizingPanels] = useState(false)
  const editorRef = useRef<PythonEditorHandle>(null)

  useEffect(() => {
    if (account.data && defaultCode !== null && code === null) {
      const initial = notificationDraft(account.data.execution_notification_code, defaultCode)
      setCode(initial.code)
      setSavedCode(initial.savedCode)
    }
  }, [account.data, code, defaultCode, setCode, setSavedCode])

  const [templateError, setTemplateError] = useState<Error | null>(null)
  const [templateLoading, setTemplateLoading] = useState(false)
  const loadTemplate = useCallback(async () => {
    setTemplateLoading(true)
    setTemplateError(null)
    try {
      setDefaultCode(await getDefaultAccountNotification(accountId))
    } catch (cause) {
      setTemplateError(cause instanceof Error ? cause : new Error(String(cause)))
    } finally {
      setTemplateLoading(false)
    }
  }, [accountId])
  useEffect(() => { void loadTemplate() }, [loadTemplate])

  const trial = usePythonRun<AccountFeishuTestResult>({
    code: code ?? '', enabled: !saveState.saving,
    execute: (draft) => testAccountNotificationFunction(accountId, draft),
    failed: (cause) => ({ ok: false, message: cause instanceof Error ? cause.message : String(cause) }),
    toEditorResult: (test) => ({ valid: test.ok, errorMessage: test.ok ? null : test.message }),
  })
  const { result: test, editorResult: result, stale } = trial
  const busy = trial.running ? 'test' : saveState.saving ? 'save' : null
  const error = saveState.error
  const status = pythonRunStatus(busy === 'test', result, stale)
  const style = PYTHON_RUN_STYLE[status]

  if (account.error && !account.data) return <EditError error={account.error} onRetry={account.refresh} />
  if (templateError && code === null) return <section><ErrorNotice title="默认模板读取失败" error={templateError} onRetry={() => void loadTemplate()} /></section>
  if (!account.data || code === null) return <EditLoading />

  const acc = account.data
  const empty = !code.trim()
  const dirty = draftState.dirty
  const savedNotificationStatus = NOTIFICATION_STATUS_LABEL[acc.execution_notification_status]
  const inspectorRows = resultOpen
    ? 'auto minmax(0,0fr) 36px minmax(0,1fr)'
    : 'auto minmax(0,1fr) 36px minmax(0,0fr)'
  const runTest = async () => {
    saveState.clearError()
    const next = await trial.run()
    if (next) setResultOpen(true)
  }
  const save = () => saveState.save(dirty && !trial.running, async () => {
    await updateAccount(accountId, { execution_notification_code: code.trim() ? code : null })
    setSavedCode(code)
    toast(code.trim() ? '执行通知函数已保存' : '执行通知已关闭')
    void refreshAccounts()
    void account.refresh()
  })
  const restore = () => {
    draftState.restore()
    saveState.clearError()
    editorRef.current?.focus()
  }

  return (
    <PythonWorkbench
      storageKey={INSPECTOR_WIDTH_KEY}
      resizingPanels={resizingPanels}
      saveAction={{ dirty, saving: saveState.saving, error, disabled: trial.running, onSave: () => void save(), onRestore: restore }}
      status={<div ref={setEditorStatus} className="mr-2 flex-none" />}
      inspector={(
        <div
          className={`grid min-h-0 content-start transition-[grid-template-rows] duration-200 motion-reduce:transition-none ${resizingPanels ? '!transition-none' : ''}`}
          style={{ gridTemplateRows: inspectorRows }}
        >
          <aside className="flex min-h-0 w-full flex-col overflow-y-auto border-line bg-surface px-3 py-2.5 md:border-r">
            <Link to={`/accounts/${accountId}/edit`} className="mb-3 inline-block text-[13px] text-accent hover:underline">
              返回基本信息
            </Link>
            <div className="flex flex-wrap items-baseline gap-2">
              <AccountPageTitle accountId={accountId} page="执行通知函数" name={acc.name} channel={acc.trade_channel} market={acc.market} />
            </div>
            <p className="mt-2 text-[13px] text-ink-3">
              {savedNotificationStatus}
              {code !== savedCode ? ' · 当前草稿未保存' : ''}
            </p>
            <div className="mt-2 flex gap-3 text-[13px]">
              <button type="button" className="cursor-pointer text-accent disabled:opacity-45" disabled={defaultCode === null || templateLoading || busy !== null} onClick={() => { setCode(defaultCode); saveState.clearError() }}>重置为默认</button>
              <button type="button" className="cursor-pointer text-ink-2 disabled:opacity-45" disabled={empty || busy !== null} onClick={() => { setCode(''); saveState.clearError() }}>清空函数</button>
            </div>
            <button
              type="button"
              title="试跑会执行代码，可能向外发送消息"
              className="mt-4 inline-flex w-full cursor-pointer items-center justify-center gap-1.5 rounded-[6px] border-0 bg-ink-1 px-3 py-1.5 text-[14px] font-[550] text-surface disabled:cursor-default disabled:opacity-45"
              disabled={empty || busy !== null}
              onClick={() => void runTest()}
            >
              <Play size={14} aria-hidden /> <InkRewrite text={busy === 'test' ? '试跑中…' : '试跑函数'} tone="label" textClassName="text-surface" />
            </button>
          </aside>
          <div aria-hidden />
          <WorkbenchPanel
            title="试跑结果"
            open={resultOpen}
            onToggle={() => setResultOpen((open) => !open)}
            className="border-t border-line md:border-r"
            stale={stale}
            status={(
              <span className="ml-auto flex items-center gap-1.5 px-3.5 text-[12.5px]">
                {status === 'pass' ? <Check size={13} className="text-accent" /> : status === 'fail' ? <TriangleAlert size={13} className="text-warn" /> : <Circle size={7} className={busy === 'test' ? 'fill-accent text-accent' : 'fill-ink-3 text-ink-3'} />}
                <InkRewrite text={style.body} tone="label" textClassName={style.text} />
              </span>
            )}
          >
            {test ? (
              <p className={`text-[13.5px] ${test.ok ? 'text-ink-2' : 'text-warn'}`} role="status">{test.message}</p>
            ) : (
              <p className="text-[13.5px] text-ink-3">尚未试跑</p>
            )}
          </WorkbenchPanel>
        </div>

      )}
    >
        <PythonWorkbenchPane
          kind="account_notification"
          editorRef={editorRef}
          statusTarget={editorStatus}
          storageKey="axon.notificationWorkbench.editorSplit"
          title="通知函数"
          docHref="/docs/notification"
          code={code}
          onChange={(value) => { setCode(value); saveState.clearError() }}
          running={busy === 'test'}
          runDisabled={saveState.saving}
          stale={stale}
          result={result}
          onRun={() => void runTest()}
          onResizeChange={setResizingPanels}
        />
    </PythonWorkbench>
  )
}
