/** 账户自定义执行通知工作台：左侧试跑，右侧编辑代码。 */

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { useParams } from 'react-router'
import { Check, Circle, Play, TriangleAlert } from 'lucide-react'
import { Link, useNavigate } from '@/components/ui/nav'
import { InkRewrite } from '@/components/ui/InkRewrite'
import { PYTHON_RUN_STYLE, pythonRunStatus, type PythonEditorHandle, type PythonValidationState } from '@/components/ui/PythonFunctionEditor'
import { PythonWorkbenchPane } from '@/components/ui/PythonWorkbenchPane'
import { WorkbenchPanel } from '@/components/ui/WorkbenchPanel'
import { AccountPageTitle } from '@/features/account/pageHead'
import { EditError, EditLoading } from '@/features/account/editUi'
import { getAccount, testAccountNotificationFunction, updateAccount, type AccountFeishuTestResult } from '@/lib/api/accounts'
import { usePolling } from '@/lib/hooks/usePolling'
import { useDomainStore } from '@/stores/domain'
import { useToastStore } from '@/stores/ui'

const DEFAULT_INSPECTOR_WIDTH = 320
const MIN_INSPECTOR_WIDTH = 260
const MAX_INSPECTOR_WIDTH = 480
const INSPECTOR_WIDTH_KEY = 'axon.notificationWorkbench.inspectorWidth'

function clampInspectorWidth(width: number, containerWidth = Number.POSITIVE_INFINITY) {
  const available = Math.max(MIN_INSPECTOR_WIDTH, containerWidth - 520)
  return Math.min(Math.max(width, MIN_INSPECTOR_WIDTH), MAX_INSPECTOR_WIDTH, available)
}

function initialInspectorWidth() {
  if (typeof window === 'undefined') return DEFAULT_INSPECTOR_WIDTH
  const stored = Number(window.localStorage.getItem(INSPECTOR_WIDTH_KEY))
  return Number.isFinite(stored) && stored > 0 ? clampInspectorWidth(stored) : DEFAULT_INSPECTOR_WIDTH
}

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
  const [savedCode, setSavedCode] = useState('')
  const [test, setTest] = useState<AccountFeishuTestResult | null>(null)
  const [testedCode, setTestedCode] = useState<string | null>(null)
  const [resultOpen, setResultOpen] = useState(true)
  const [busy, setBusy] = useState<'test' | 'save' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [editorStatus, setEditorStatus] = useState<HTMLDivElement | null>(null)
  const [inspectorWidth, setInspectorWidth] = useState(initialInspectorWidth)
  const [resizingInspector, setResizingInspector] = useState(false)
  const [resizingPanels, setResizingPanels] = useState(false)
  const editorRef = useRef<PythonEditorHandle>(null)
  const workbenchRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (account.data && code === null) {
      const initial = account.data.execution_notification_code ?? ''
      setCode(initial)
      setSavedCode(initial)
    }
  }, [account.data, code])

  const result = useMemo<PythonValidationState | null>(() => test && ({
    valid: test.ok,
    errorMessage: test.ok ? null : test.message,
  }), [test])
  const stale = test !== null && testedCode !== code
  const status = pythonRunStatus(busy === 'test', result, stale)
  const style = PYTHON_RUN_STYLE[status]

  if (account.error && !account.data) return <EditError error={account.error} onRetry={account.refresh} />
  if (!account.data || code === null) return <EditLoading />

  const acc = account.data
  const empty = !code.trim()
  const dirty = code !== savedCode || acc.execution_notification_mode !== 'function'
  const inspectorRows = resultOpen
    ? 'auto minmax(0,0fr) 36px minmax(0,1fr)'
    : 'auto minmax(0,1fr) 36px minmax(0,0fr)'
  const resizeInspector = (clientX: number) => {
    const bounds = workbenchRef.current?.getBoundingClientRect()
    if (bounds) setInspectorWidth(clampInspectorWidth(clientX - bounds.left, bounds.width))
  }
  const persistInspectorWidth = (width: number) => {
    window.localStorage.setItem(INSPECTOR_WIDTH_KEY, String(width))
  }
  const runTest = async () => {
    if (empty || busy !== null) return
    const draft = code
    setBusy('test')
    setError(null)
    try {
      setTest(await testAccountNotificationFunction(accountId, draft))
    } catch (cause) {
      setTest({ ok: false, message: cause instanceof Error ? cause.message : String(cause) })
    } finally {
      setTestedCode(draft)
      setBusy(null)
      setResultOpen(true)
    }
  }
  const save = async () => {
    if (empty || busy !== null) return
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
    <section className="flex h-full w-full flex-col bg-canvas">
      <div
        ref={workbenchRef}
        className={`relative grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[var(--notification-inspector-width)_minmax(0,1fr)] ${resizingInspector || resizingPanels ? 'select-none' : ''}`}
        style={{ '--notification-inspector-width': `${inspectorWidth}px` } as CSSProperties}
      >
        <div
          className={`grid min-h-0 content-start transition-[grid-template-rows] duration-200 motion-reduce:transition-none ${resizingPanels ? '!transition-none' : ''}`}
          style={{ gridTemplateRows: inspectorRows }}
        >
          <aside className="flex min-h-0 w-full flex-col overflow-y-auto border-line bg-surface px-3 py-2.5 md:border-r">
            <Link to={`/accounts/${accountId}/edit`} className="mb-3 inline-block text-[13px] text-accent hover:underline">
              返回基本信息
            </Link>
            <div className="flex flex-wrap items-baseline gap-2">
              <AccountPageTitle accountId={accountId} page="自定义执行通知" name={acc.name} channel={acc.trade_channel} market={acc.market} />
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

        <PythonWorkbenchPane
          editorRef={editorRef}
          statusTarget={editorStatus}
          storageKey="axon.notificationWorkbench.editorSplit"
          title="通知函数"
          code={code}
          onChange={(value) => { setCode(value); setError(null) }}
          running={busy === 'test'}
          stale={stale}
          result={result}
          onRun={() => void runTest()}
          onResizeChange={setResizingPanels}
        />
        <div
          role="separator"
          aria-label="调整运行检查器宽度"
          aria-orientation="vertical"
          aria-valuemin={MIN_INSPECTOR_WIDTH}
          aria-valuemax={MAX_INSPECTOR_WIDTH}
          aria-valuenow={Math.round(inspectorWidth)}
          tabIndex={0}
          title="左右拖动调整宽度 · 双击恢复默认"
          className="group absolute inset-y-0 z-20 hidden w-[7px] -translate-x-1/2 touch-none cursor-col-resize outline-none md:block"
          style={{ left: `${inspectorWidth}px` }}
          onDoubleClick={() => {
            setInspectorWidth(DEFAULT_INSPECTOR_WIDTH)
            persistInspectorWidth(DEFAULT_INSPECTOR_WIDTH)
          }}
          onPointerDown={(event) => {
            event.preventDefault()
            event.currentTarget.setPointerCapture(event.pointerId)
            setResizingInspector(true)
            resizeInspector(event.clientX)
          }}
          onPointerMove={(event) => {
            if (event.currentTarget.hasPointerCapture(event.pointerId)) resizeInspector(event.clientX)
          }}
          onPointerUp={(event) => {
            const bounds = workbenchRef.current?.getBoundingClientRect()
            const width = bounds ? clampInspectorWidth(event.clientX - bounds.left, bounds.width) : inspectorWidth
            if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
            setInspectorWidth(width)
            setResizingInspector(false)
            persistInspectorWidth(width)
          }}
          onPointerCancel={() => setResizingInspector(false)}
          onKeyDown={(event) => {
            let next = inspectorWidth
            if (event.key === 'ArrowLeft') next -= 16
            else if (event.key === 'ArrowRight') next += 16
            else if (event.key === 'Home') next = MIN_INSPECTOR_WIDTH
            else if (event.key === 'End') next = MAX_INSPECTOR_WIDTH
            else return
            event.preventDefault()
            const containerWidth = workbenchRef.current?.getBoundingClientRect().width
            next = clampInspectorWidth(next, containerWidth)
            setInspectorWidth(next)
            persistInspectorWidth(next)
          }}
        >
          <span className={`absolute inset-y-0 left-1/2 w-px transition-colors duration-130 ${resizingInspector ? 'bg-accent' : 'bg-line group-hover:bg-accent group-focus:bg-accent'}`} />
          <span aria-hidden className={`absolute left-1/2 top-1/2 h-7 w-[3px] -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-surface transition-colors duration-130 ${resizingInspector ? 'bg-accent' : 'bg-ink-3 group-hover:bg-accent group-focus:bg-accent'}`} />
        </div>
      </div>
      <footer className="flex h-7 flex-none items-center border-t border-line bg-surface px-2 text-[12px]">
        <div className={`flex min-w-0 flex-1 items-center gap-1.5 truncate ${error || empty ? 'text-warn' : 'text-ink-2'}`} role={error ? 'alert' : 'status'} title={error ?? undefined}>
          <span className={error || empty ? 'text-warn' : dirty ? 'text-accent' : 'text-ink-3'} aria-hidden>{error || empty ? '△' : dirty ? '●' : '✓'}</span>
          <InkRewrite text={error ? '保存失败' : busy === 'save' ? '保存中…' : empty ? '内容不完整' : dirty ? '未保存' : '已启用'} tone="label" />
        </div>
        <div ref={setEditorStatus} className="mr-2 flex-none" />
        <button
          type="button"
          title={error ?? '保存后启用自定义通知'}
          className="h-full cursor-pointer px-2 font-[550] text-ink-1 hover:bg-fill disabled:cursor-default disabled:text-ink-3"
          disabled={empty || busy !== null}
          onClick={() => void save()}
        >
          {busy === 'save' ? '保存中…' : '保存并启用'}
        </button>
      </footer>
    </section>
  )
}
