import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { useParams, useViewTransitionState } from 'react-router'
import { Clipboard, Pencil, Play } from 'lucide-react'
import { Link } from '@/components/ui/nav'
import { Chip } from '@/components/ui/Card'
import { Skeleton } from '@/components/ui/Skeleton'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { InkRewrite } from '@/components/ui/InkRewrite'
import { Select } from '@/components/ui/Select'
import { PythonFunctionEditor, type PythonEditorHandle } from '@/components/ui/PythonFunctionEditor'
import { PythonRunPanel } from '@/components/ui/PythonRunPanel'
import { channelLabel } from '@/features/dashboard/display'
import { WeightResult } from '@/features/portfolio/WeightResult'
import { useCustomCalcValidation } from '@/features/portfolio/useCustomCalcValidation'
import { usePolling } from '@/lib/hooks/usePolling'
import { getPortfolio, updatePortfolio } from '@/lib/api/portfolios'
import { useDomainStore } from '@/stores/domain'
import { useToastStore } from '@/stores/ui'

const DEFAULT_INSPECTOR_WIDTH = 320
const MIN_INSPECTOR_WIDTH = 260
const MAX_INSPECTOR_WIDTH = 480
const INSPECTOR_WIDTH_KEY = 'axon.portfolioWorkbench.inspectorWidth'
const PANEL_SPLIT_KEY = 'axon.portfolioWorkbench.panelSplit'

function clampInspectorWidth(width: number, containerWidth = Number.POSITIVE_INFINITY) {
  const available = Math.max(MIN_INSPECTOR_WIDTH, containerWidth - 520)
  return Math.min(Math.max(width, MIN_INSPECTOR_WIDTH), MAX_INSPECTOR_WIDTH, available)
}

function initialInspectorWidth() {
  if (typeof window === 'undefined') return DEFAULT_INSPECTOR_WIDTH
  const stored = Number(window.localStorage.getItem(INSPECTOR_WIDTH_KEY))
  return Number.isFinite(stored) && stored > 0 ? clampInspectorWidth(stored) : DEFAULT_INSPECTOR_WIDTH
}

function initialPanelSplit() {
  if (typeof window === 'undefined') return 0.5
  const stored = Number(window.localStorage.getItem(PANEL_SPLIT_KEY))
  return Number.isFinite(stored) && stored >= 0.2 && stored <= 0.8 ? stored : 0.5
}

/**
 * 组合工作台（VSCode 式布局）：上排是控制 / 代码，下排是返回值 / 问题；
 * 两列共用一条水平分界，让业务输出与代码诊断各归其位。
 * 保存成功后留在原地（改 → 试跑 → 保存 → 再改的循环不被打断）。
 * 窄视口（<md）退化为单列堆叠，编辑器保底 420px 高、页面恢复滚动。
 */
export function PortfolioEditPage() {
  const { id } = useParams()
  const portfolioId = Number(id)
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
  const [resultOpen, setResultOpen] = useState(false)
  const [problemsOpen, setProblemsOpen] = useState(false)
  const [inspectorWidth, setInspectorWidth] = useState(initialInspectorWidth)
  const [resizingInspector, setResizingInspector] = useState(false)
  const [panelSplit, setPanelSplit] = useState(initialPanelSplit)
  const [resizingPanels, setResizingPanels] = useState(false)
  const editorRef = useRef<PythonEditorHandle>(null)
  const workbenchRef = useRef<HTMLDivElement>(null)
  const inspectorRef = useRef<HTMLDivElement>(null)
  const inspectorControlsRef = useRef<HTMLElement>(null)
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

  // 试跑状态机（与初始化向导共用）：上下文选择、结果、stale、Ctrl+Enter 的回调目标。
  const calc = useCustomCalcValidation(code)

  // 两列是独立 split pane：成功只展开返回值，失败只展开问题。
  useEffect(() => {
    if (!calc.editorResult) return
    if (calc.editorResult.valid) {
      setResultOpen(true)
      setProblemsOpen(false)
    } else {
      setProblemsOpen(true)
      setResultOpen(false)
    }
  }, [calc.editorResult])

  // 组合名 + 市场 chip 共享元素：详情 hero ↔ 本页左栏标题槽（同账户域「详情头 ↔ 标题槽」协议）。
  const tDetail = useViewTransitionState(`/portfolios/${portfolioId}`)

  const dirty = name.trim() !== original.name || code !== original.code
  // 只让当前代码的语法错误阻止保存；继续编辑后，旧试跑结果已 stale，不应误锁。
  const currentSyntaxError =
    !calc.stale && calc.editorResult?.valid === false && calc.editorResult.errorType === 'SyntaxError'
  const blocked =
    !name.trim() || !code.trim() || accounts == null || Boolean(accountsError) || currentSyntaxError

  const resizeInspector = (clientX: number) => {
    const bounds = workbenchRef.current?.getBoundingClientRect()
    if (!bounds) return
    setInspectorWidth(clampInspectorWidth(clientX - bounds.left, bounds.width))
  }

  const persistInspectorWidth = (width: number) => {
    window.localStorage.setItem(INSPECTOR_WIDTH_KEY, String(width))
  }

  const panelSplitAt = (clientY: number) => {
    const inspectorBounds = inspectorRef.current?.getBoundingClientRect()
    const controlsBounds = inspectorControlsRef.current?.getBoundingClientRect()
    if (!inspectorBounds || !controlsBounds) return panelSplit
    const available = inspectorBounds.bottom - controlsBounds.bottom - 5
    if (available <= 0) return panelSplit
    const minShare = Math.min(0.45, 120 / available)
    return Math.min(Math.max((clientY - controlsBounds.bottom) / available, minShare), 1 - minShare)
  }

  // 七条轨道始终同构：控制区 / 弹性留白 / 结果标题 / 结果正文 / 分隔条 / 问题标题 / 问题正文。
  // 标题的固定 36px 与正文 fr 分离，避免 minmax 在触及下限时切换算法造成高度回弹。
  const inspectorRows = resultOpen && problemsOpen
    ? `auto minmax(0, 0fr) 36px minmax(0, ${panelSplit}fr) 5px 36px minmax(0, ${1 - panelSplit}fr)`
    : resultOpen
      ? 'auto minmax(0, 0fr) 36px minmax(0, 1fr) 0px 36px minmax(0, 0fr)'
      : problemsOpen
        ? 'auto minmax(0, 0fr) 36px minmax(0, 0fr) 0px 36px minmax(0, 1fr)'
        : 'auto minmax(0, 1fr) 36px minmax(0, 0fr) 0px 36px minmax(0, 0fr)'

  // 保存后留在原地：toast 确认、基线更新为已保存态，迭代循环不跳出工作台。
  const publish = async (validated = false) => {
    const saveBlocked = !name.trim() || !code.trim() || accounts == null || Boolean(accountsError)
    if (saveBlocked || (!validated && currentSyntaxError) || saving || !dirty) return
    setSaving(true)
    setSaveError(null)
    try {
      await updatePortfolio(portfolioId, { name: name.trim(), custom_calc_py_code: code })
      toast('组合已更新')
      setOriginal({ name: name.trim(), code })
      void refreshPortfolios()
    } catch (error) {
      setSaveError(error instanceof Error ? error : new Error(String(error)))
    } finally {
      setSaving(false)
    }
  }

  const runAndPublish = async () => {
    if (saving) return
    const result = await calc.run()
    if (result?.valid) await publish(true)
  }

  // Ctrl/Cmd+S 保存（工作台肌肉记忆）；编辑器内按键同样冒泡到 window。
  const publishRef = useRef(publish)
  useEffect(() => {
    publishRef.current = publish
  })
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === 's') {
        event.preventDefault()
        void publishRef.current()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const paste = async () => {
    try {
      const text = await navigator.clipboard.readText()
      if (text) {
        setCode(text)
        setSaveError(null)
      }
    } finally {
      editorRef.current?.focus()
    }
  }

  const restore = () => {
    setName(original.name)
    setCode(original.code)
    setSaveError(null)
    editorRef.current?.focus()
  }

  if (portfolio.loading || (!pf && !portfolio.error) || (pf && !ready)) {
    return (
      <section className="mx-auto flex h-full w-full max-w-[1440px] flex-col">
        <div className="flex min-h-0 flex-1 flex-col gap-6 md:flex-row md:gap-8">
          <div className="w-full md:w-[264px] md:flex-none">
            <div className="flex items-center gap-2">
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-5 w-14" />
            </div>
            <Skeleton className="mt-6 h-4 w-16" />
            <Skeleton className="mt-2 h-[38px] w-full" />
          </div>
          <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="mt-2 min-h-[300px] w-full flex-1" />
            <Skeleton className="mt-3 h-9 w-full" />
          </div>
        </div>
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
    <section className="flex h-full w-full flex-col bg-canvas">
      <div
        ref={workbenchRef}
        className={`relative grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[var(--portfolio-inspector-width)_minmax(0,1fr)] ${
          resizingInspector || resizingPanels ? 'select-none' : ''
        }`}
        style={{ '--portfolio-inspector-width': `${inspectorWidth}px` } as CSSProperties}
      >
        <div
          ref={inspectorRef}
          className={`grid min-h-0 content-start transition-[grid-template-rows] duration-200 motion-reduce:transition-none ${
            resizingPanels ? '!transition-none' : ''
          }`}
          style={{ gridTemplateRows: inspectorRows }}
        >
          {/* 左上控制区：身份 → 元信息 → 控制，保存区钉在栏底。 */}
          <aside
            ref={inspectorControlsRef}
            className="flex min-h-0 w-full flex-col overflow-y-auto border-line bg-surface px-3 py-2.5 md:border-r"
          >
          <div className="group/name flex flex-none items-center gap-2">
            <input
              aria-label="组合名称"
              title="编辑组合名称"
              className="min-w-0 flex-1 border-b border-line/70 bg-transparent px-0 py-0.5 text-[15px] font-[640] leading-snug text-ink-1 outline-none transition-colors duration-200 hover:border-ink-3 focus:border-accent"
              style={tDetail ? { viewTransitionName: `portfolio-name-${portfolioId}` } : undefined}
              value={name}
              placeholder="组合名称"
              onChange={(event) => {
                setName(event.target.value)
                setSaveError(null)
              }}
            />
            {/* 市场是身份元数据：只读中性胶囊，与详情 hero 同位（不做编辑入口，依赖缺口是已知问题）。 */}
            {pf.market && (
              <Chip
                className="max-w-32 truncate"
                style={tDetail ? { viewTransitionName: `portfolio-market-${portfolioId}` } : undefined}
              >
                {pf.market}
              </Chip>
            )}
            {!dirty && (
              <Pencil
                size={13}
                aria-hidden
                className="pointer-events-none flex-none text-ink-3 transition-colors duration-200 group-hover/name:text-ink-2 group-focus-within/name:text-ink-3"
              />
            )}
          </div>

          <div className="flex-none">
            {followers.length > 0 && (
              <div className="mt-5">
                <div className="text-[12px] font-semibold tracking-wide text-ink-3">跟随账户 · {followers.length}</div>
                <ul className="mt-1.5 flex flex-col">
                  {followers.map((account) => (
                    <li key={account.account_id}>
                      <Link
                        to={`/accounts/${account.account_id}`}
                        className="group -mx-2 flex items-center gap-2 rounded-[8px] px-2 py-1.5 hover:bg-fill"
                      >
                        <span className="min-w-0 truncate text-[14px] text-ink-1">{account.name}</span>
                        <span className="flex-none rounded-chip bg-fill px-1.5 py-px text-[11.5px] text-ink-2">
                          {channelLabel(account.trade_channel, account.market)}
                        </span>
                        <span className="ml-auto flex-none text-ink-3 transition-colors group-hover:text-ink-1" aria-hidden>
                          ›
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="mt-4 flex flex-col gap-1.5">
                <Select<number | null>
                  ariaLabel="试跑数据来源"
                  value={calc.accountId}
                  onChange={calc.setAccountId}
                  options={calc.contextOptions}
                  className="w-full justify-between px-2.5 py-1.5 text-[13.5px]"
                />
                {/* 来源说明：同一槽位原地换字（InkRewrite 是单行槽，文案必须压进一行）。
                    账户名不重复——Select 触发器上已有。选真实账户升琥珀：主动交易有真实委托。 */}
                <p
                  className={`border-l-2 pl-2 text-[12.5px] leading-5 ${
                    calc.accountId == null ? 'border-transparent' : 'border-warn'
                  }`}
                >
                  <InkRewrite
                    text={
                      calc.accountId == null
                        ? '假数据 · 不连真实渠道 · 只验证逻辑'
                        : '真实数据 · 主动交易将产生真实委托'
                    }
                    tone="label"
                    textClassName={calc.accountId == null ? 'text-ink-3' : 'text-warn'}
                  />
                </p>
                <button
                  type="button"
                  className="inline-flex w-full cursor-pointer items-center justify-center gap-1.5 rounded-[6px] border-0 bg-ink-1 px-3 py-1.5 text-[14px] font-[550] text-surface disabled:cursor-default disabled:opacity-45"
                  onClick={() => void runAndPublish()}
                  disabled={!calc.canRun || saving || !name.trim() || accounts == null || Boolean(accountsError)}
                >
                  <Play size={14} />
                  <InkRewrite
                    tone="label"
                    text={calc.validating ? '试跑中…' : saving ? '保存中…' : '试跑并保存'}
                    textClassName="text-surface"
                  />
                </button>
            </div>

            <div className="mt-3 flex items-center gap-4">
                <button
                  type="button"
                  className="inline-flex cursor-pointer items-center gap-1.5 text-[14px] text-accent"
                  onClick={() => void paste()}
                >
                  <Clipboard size={14} /> 粘贴
                </button>
                <a className="text-[14px] text-accent" href="/docs/custom-calc" target="_blank" rel="noopener">
                  开发文档 ↗
                </a>
            </div>
          </div>

          </aside>

          <div aria-hidden />

          <PythonRunPanel
            kind="result"
            open={resultOpen}
            onToggle={() => setResultOpen((open) => !open)}
            className="border-line border-t md:border-r"
            running={calc.validating}
            result={calc.editorResult}
            stale={calc.stale}
            resultContent={calc.result?.valid && calc.result.target ? <WeightResult target={calc.result.target} /> : null}
          />

          <div
            role="separator"
            aria-label="调整试跑结果与问题的高度"
            aria-orientation="horizontal"
            aria-valuemin={20}
            aria-valuemax={80}
            aria-valuenow={Math.round(panelSplit * 100)}
            tabIndex={resultOpen && problemsOpen ? 0 : -1}
            inert={!(resultOpen && problemsOpen)}
            title="拖动分配面板高度 · 双击平均分配"
            className={`group relative z-10 cursor-row-resize touch-none outline-none md:border-r md:border-line ${
              resultOpen && problemsOpen ? 'block' : 'invisible'
            }`}
            onDoubleClick={() => {
              setPanelSplit(0.5)
              window.localStorage.setItem(PANEL_SPLIT_KEY, '0.5')
            }}
            onPointerDown={(event) => {
              if (!(resultOpen && problemsOpen)) return
              event.preventDefault()
              event.currentTarget.setPointerCapture(event.pointerId)
              setResizingPanels(true)
              setPanelSplit(panelSplitAt(event.clientY))
            }}
            onPointerMove={(event) => {
              if (event.currentTarget.hasPointerCapture(event.pointerId)) setPanelSplit(panelSplitAt(event.clientY))
            }}
            onPointerUp={(event) => {
              const finalSplit = panelSplitAt(event.clientY)
              if (event.currentTarget.hasPointerCapture(event.pointerId)) {
                event.currentTarget.releasePointerCapture(event.pointerId)
              }
              setPanelSplit(finalSplit)
              setResizingPanels(false)
              window.localStorage.setItem(PANEL_SPLIT_KEY, String(finalSplit))
            }}
            onPointerCancel={() => setResizingPanels(false)}
            onKeyDown={(event) => {
              let next = panelSplit
              if (event.key === 'ArrowUp') next -= 0.05
              else if (event.key === 'ArrowDown') next += 0.05
              else if (event.key === 'Home') next = 0.2
              else if (event.key === 'End') next = 0.8
              else return
              event.preventDefault()
              next = Math.min(Math.max(next, 0.2), 0.8)
              setPanelSplit(next)
              window.localStorage.setItem(PANEL_SPLIT_KEY, String(next))
            }}
          >
            <span className="absolute inset-x-0 top-1/2 h-px bg-line transition-colors duration-130 group-hover:bg-accent group-focus:bg-accent" />
          </div>

          <PythonRunPanel
            kind="problems"
            open={problemsOpen}
            onToggle={() => setProblemsOpen((open) => !open)}
            className="border-line border-t md:border-r"
            running={calc.validating}
            result={calc.editorResult}
            stale={calc.stale}
            onRevealError={(line) => editorRef.current?.revealLine(line)}
          />
        </div>

        {/* 右侧只承担代码阅读与编辑；运行上下文、返回值和问题全部收口在左列。 */}
        <div className="flex min-h-[420px] min-w-0 flex-1 flex-col bg-code-bg md:min-h-0">
          <div className="flex h-8 flex-none items-center border-b border-line bg-surface px-3 text-[12px] text-ink-2">
            <span className="font-[550] text-ink-1">目标函数</span>
            <span className="ml-auto font-mono text-[11px] text-ink-3">⌘/Ctrl+Enter 试跑</span>
          </div>
          <PythonFunctionEditor
            ref={editorRef}
            layout="workbench"
            fill
            code={code}
            onChange={(value) => {
              setCode(value)
              setSaveError(null)
            }}
            running={calc.validating}
            stale={calc.stale}
            result={calc.editorResult}
            onRun={() => void calc.run()}
          />
        </div>

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
            const finalWidth = bounds
              ? clampInspectorWidth(event.clientX - bounds.left, bounds.width)
              : inspectorWidth
            if (event.currentTarget.hasPointerCapture(event.pointerId)) {
              event.currentTarget.releasePointerCapture(event.pointerId)
            }
            setInspectorWidth(finalWidth)
            setResizingInspector(false)
            persistInspectorWidth(finalWidth)
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
          <span
            className={`absolute inset-y-0 left-1/2 w-px transition-colors duration-130 ${
              resizingInspector ? 'bg-accent' : 'bg-line group-hover:bg-accent group-focus:bg-accent'
            }`}
          />
          <span
            aria-hidden
            className={`absolute left-1/2 top-1/2 h-7 w-[3px] -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-surface transition-colors duration-130 ${
              resizingInspector
                ? 'bg-accent'
                : 'bg-ink-3 group-hover:bg-accent group-focus:bg-accent'
            }`}
          />
        </div>
      </div>

      {/* 工作台全局状态栏：固定占位，只承载编辑状态和保存动作。 */}
      <footer className="flex h-7 flex-none items-center border-t border-line bg-surface px-2 text-[12px]">
        <div
          className={`flex min-w-0 flex-1 items-center gap-1.5 truncate ${
            saveError || blocked ? 'text-warn' : 'text-ink-2'
          }`}
          title={saveError?.message}
        >
          <span className={saveError || blocked ? 'text-warn' : dirty ? 'text-accent' : 'text-ink-3'} aria-hidden>
            {saveError || blocked ? '△' : dirty ? '●' : '✓'}
          </span>
          <InkRewrite
            tone="label"
            text={
              saveError
                ? '保存失败'
                : saving
                  ? '保存中…'
                  : accountsError
                    ? '绑定关系不可用'
                    : currentSyntaxError
                      ? '有语法错误'
                      : !name.trim() || !code.trim()
                        ? '内容不完整'
                        : dirty
                          ? '未保存'
                          : '已保存'
            }
          />
        </div>
        <div className="ml-auto flex h-full flex-none items-center">
          <button
            type="button"
            className={`h-full px-2 text-ink-2 transition-opacity duration-200 hover:bg-fill hover:text-ink-1 ${
              dirty ? 'cursor-pointer opacity-100' : 'pointer-events-none opacity-0'
            }`}
            onClick={restore}
            tabIndex={dirty ? 0 : -1}
            aria-hidden={!dirty}
          >
            还原
          </button>
          <button
            type="button"
            title={
              followers.length > 0
                ? `保存（⌘/Ctrl+S）· ${followers.length} 个账户将在下次调仓使用新函数`
                : '保存（⌘/Ctrl+S）'
            }
            className="h-full px-2 font-[550] text-ink-1 hover:bg-fill disabled:cursor-default disabled:text-ink-3"
            onClick={() => void publish()}
            disabled={!dirty || blocked || saving}
          >
            保存
          </button>
        </div>
      </footer>
    </section>
  )
}
