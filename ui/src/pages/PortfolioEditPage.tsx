import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { useParams, useViewTransitionState } from 'react-router'
import { Clipboard, ChevronDown, Pencil, Play, RefreshCw, Zap } from 'lucide-react'
import { Link } from '@/components/ui/nav'
import { Chip } from '@/components/ui/Card'
import { Skeleton } from '@/components/ui/Skeleton'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { InkRewrite } from '@/components/ui/InkRewrite'
import { Select } from '@/components/ui/Select'
import { Segmented } from '@/components/ui/Segmented'
import { Tooltip } from '@/components/ui/Tooltip'
import { ConfirmModal, type ConfirmSpec } from '@/components/ui/ConfirmModal'
import { PythonFunctionEditor, type PythonEditorHandle } from '@/components/ui/PythonFunctionEditor'
import { PythonRunPanel } from '@/components/ui/PythonRunPanel'
import { channelLabel } from '@/features/dashboard/display'
import { WeightResult } from '@/features/portfolio/WeightResult'
import { SnapshotResult } from '@/features/portfolio/SnapshotResult'
import { targetSnapshotText } from '@/features/portfolio/targetSnapshotDisplay'
import { targetWeightSummary } from '@/features/portfolio/portfolioCardSummary'
import { useCustomCalcValidation } from '@/features/portfolio/useCustomCalcValidation'
import { usePolling } from '@/lib/hooks/usePolling'
import { useTargetSnapshot } from '@/lib/hooks/useTargetSnapshot'
import {
  getPortfolio,
  getPortfolioTargetSnapshot,
  refreshPortfolioTargetSnapshot,
  updatePortfolio,
} from '@/lib/api/portfolios'
import { triggerExecute } from '@/lib/api/executions'
import { useDomainStore } from '@/stores/domain'
import { useLiveExecStore } from '@/stores/liveExec'
import { useToastStore } from '@/stores/ui'
import type { ExecutionTrigger } from '@/types/api'

const DEFAULT_INSPECTOR_WIDTH = 320
const MIN_INSPECTOR_WIDTH = 260
const MAX_INSPECTOR_WIDTH = 480
const INSPECTOR_WIDTH_KEY = 'axon.portfolioWorkbench.inspectorWidth'
const PANEL_SPLIT_KEY = 'axon.portfolioWorkbench.panelSplit'
const EDITOR_SPLIT_KEY = 'axon.portfolioWorkbench.editorSplit'

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

function initialEditorSplit() {
  if (typeof window === 'undefined') return 0.35
  const stored = Number(window.localStorage.getItem(EDITOR_SPLIT_KEY))
  return Number.isFinite(stored) && stored >= 0.2 && stored <= 0.8 ? stored : 0.35
}

/**
 * 组合工作台（VSCode 式布局）：左列是控制 / 试跑结果 / 跟随账户，
 * 右列是代码 / 问题（问题贴代码底部，共用一条水平 split）；
 * 业务输出与代码诊断各归其位。
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
  const portfolios = useDomainStore((state) => state.portfolios)
  const pf = portfolio.data
  // 组合列表已在共享 store 里：先用 lite 预填工作台（L1 消闪，标题槽即时挂上共享名），
  // 详情到位后再对齐服务端真值。
  const lite = portfolios?.find((p) => p.id === portfolioId) ?? null
  const head = pf ?? lite
  const [ready, setReady] = useState(false)
  const [name, setName] = useState(() => lite?.name ?? '')
  const [code, setCode] = useState(() => lite?.custom_calc_py_code ?? '')
  const [original, setOriginal] = useState(() => ({ name: lite?.name ?? '', code: lite?.custom_calc_py_code ?? '' }))
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<Error | null>(null)
  const [confirm, setConfirm] = useState<ConfirmSpec | null>(null)
  const [actionError, setActionError] = useState<Error | null>(null)
  // 「目标」面板默认展开生效 tab：这是组合域的「当前事实」，多数进来是为看它或试跑。
  const [resultOpen, setResultOpen] = useState(true)
  const [targetTab, setTargetTab] = useState<'effective' | 'trial'>('effective')
  const [problemsOpen, setProblemsOpen] = useState(false)
  const [followersOpen, setFollowersOpen] = useState(true)
  const [inspectorWidth, setInspectorWidth] = useState(initialInspectorWidth)
  const [resizingInspector, setResizingInspector] = useState(false)
  const [panelSplit, setPanelSplit] = useState(initialPanelSplit)
  const [editorSplit, setEditorSplit] = useState(initialEditorSplit)
  const [resizingPanels, setResizingPanels] = useState(false)
  const editorRef = useRef<PythonEditorHandle>(null)
  const workbenchRef = useRef<HTMLDivElement>(null)
  const editorPaneRef = useRef<HTMLDivElement>(null)
  const inspectorRef = useRef<HTMLDivElement>(null)
  const inspectorControlsRef = useRef<HTMLElement>(null)

  // 基线同步：lite 先预填，详情到位后再对齐服务端真值；用户已动过的输入不覆盖，
  // 只把基线对齐，避免 dirty 误判。
  useEffect(() => {
    if (ready) return
    const source = pf ?? lite
    if (!source) return
    const untouched = name === original.name && code === original.code
    setOriginal({ name: source.name, code: source.custom_calc_py_code })
    if (untouched) {
      setName(source.name)
      setCode(source.custom_calc_py_code)
    }
    if (pf) setReady(true)
  }, [pf, lite, ready, name, code, original])

  const followers = useMemo(
    () => (accounts ?? []).filter((account) => account.portfolio_id === portfolioId),
    [accounts, portfolioId],
  )
  const anyFollowerRunning = useLiveExecStore((state) =>
    followers.some((follower) => state.running.has(follower.account_id)),
  )

  // 生效目标：持久快照（账户下次调仓实际使用的权重），与试跑结果分属两个来源，
  // 由「目标」面板的 生效/试跑 分段显式命名。
  const weights = useTargetSnapshot(
    useCallback((s: AbortSignal) => getPortfolioTargetSnapshot(portfolioId, s), [portfolioId]),
    useCallback(() => refreshPortfolioTargetSnapshot(portfolioId), [portfolioId]),
    `portfolio:${portfolioId}:target-snapshot`,
  )

  // 试跑状态机（与初始化向导共用）：上下文选择、结果、stale、Ctrl+Enter 的回调目标。
  const calc = useCustomCalcValidation(code)

  // 成功只展开返回值（左列）并切到试跑分段，失败只展开问题（右列贴代码）；两列是独立 split pane。
  useEffect(() => {
    if (!calc.editorResult) return
    if (calc.editorResult.valid) {
      setResultOpen(true)
      setTargetTab('trial')
      setProblemsOpen(false)
    } else {
      setProblemsOpen(true)
      setResultOpen(false)
    }
  }, [calc.editorResult])

  // 组合名 + 市场 chip 共享元素：列表卡 ↔ 本页左栏标题槽（匹配过渡的任一端，列表直达工作台）。
  const tDetail = useViewTransitionState(`/portfolios/${portfolioId}/edit`)

  // 通知全部跟随账户立即按最新目标调仓：逐个触发、结果汇总（与在途执行合并 / 失败计数）。
  const runFanout = () => {
    if (followers.length === 0) return
    const names = followers.map((follower) => follower.name).join('、')
    setConfirm({
      title: '全部跟随账户立即执行',
      body: `通知跟随本组合的账户（${names}）立即按最新目标调仓。若目标未变，多数会空跑、几乎不增成本。`,
      okText: '通知执行',
      onConfirm: async () => {
        setActionError(null)
        const results = await Promise.allSettled(followers.map((follower) => triggerExecute(follower.account_id)))
        const failed = results.filter((result): result is PromiseRejectedResult => result.status === 'rejected')
        const coalesced = results.filter(
          (result): result is PromiseFulfilledResult<ExecutionTrigger> =>
            result.status === 'fulfilled' && result.value.accepted === 'coalesced',
        ).length
        if (failed.length > 0) {
          const queued = failed.every((result) => String(result.reason).includes('已有调仓'))
          setActionError(
            new Error(
              queued ? '账户正在清仓或无法再排队，请稍后再试' : `${failed.length} 个账户通知失败，请稍后再试`,
            ),
          )
          return
        }
        toast(
          coalesced > 0
            ? `已通知调仓，${coalesced} 个与等待中的执行合并`
            : `已通知 ${followers.length} 个账户立即调仓`,
        )
      },
    })
  }

  const snapshotContextName =
    accounts?.find((account) => account.account_id === weights.data?.context_account_id)?.name
    ?? (weights.data?.context_account_id != null ? `#${weights.data.context_account_id}` : null)
  const snapshotStatusText = weights.data?.calculated_at
    ? weights.error
      ? '目标更新失败'
      : `目标更新于 ${weights.data.calculated_at.slice(11, 16)}`
    : weights.error
      ? '目标不可用'
      : weights.loading
        ? '正在读取目标…'
        : '目标未计算'
  // 生效 tab 时头部状态行改述快照新旧（不是试跑的 pass/fail），重算入口贴着它影响的状态。
  const snapshotStatus = (
    <span className="ml-auto flex items-center gap-1 px-3.5 text-[12.5px]">
      <span
        title={targetSnapshotText(weights.data, snapshotContextName)}
        className={weights.error ? 'text-warn' : 'text-ink-3'}
      >
        <InkRewrite text={snapshotStatusText} tone="label" />
      </span>
      <Tooltip
        content={
          anyFollowerRunning
            ? '账户正在执行，结束后可重新计算'
            : weights.recalculating
              ? '正在重新计算目标权重'
              : '重新计算当前目标权重'
        }
      >
        <span className="inline-flex flex-none">
          <button
            type="button"
            onClick={() => void weights.recalculate()}
            disabled={anyFollowerRunning || weights.loading || weights.recalculating}
            aria-label={weights.recalculating ? '正在重新计算目标权重' : '重新计算当前目标权重'}
            className="grid h-6 w-6 cursor-pointer place-items-center rounded-md text-ink-3 hover:bg-fill hover:text-ink-1 disabled:cursor-default disabled:opacity-40 disabled:hover:bg-transparent"
          >
            <RefreshCw size={14} className={weights.recalculating ? 'animate-spin motion-reduce:animate-none' : undefined} />
          </button>
        </span>
      </Tooltip>
    </span>
  )

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

  // 左列 split：从上顶（控制区底）量指针位置，panelSplit 是返回值占可用高度的份额；
  // 与右列的从底量法互成镜像。
  const panelSplitAt = (clientY: number) => {
    const inspectorBounds = inspectorRef.current?.getBoundingClientRect()
    const controlsBounds = inspectorControlsRef.current?.getBoundingClientRect()
    if (!inspectorBounds || !controlsBounds) return panelSplit
    const available = inspectorBounds.bottom - controlsBounds.bottom - 5
    if (available <= 0) return panelSplit
    const minShare = Math.min(0.45, 120 / available)
    return Math.min(Math.max((clientY - controlsBounds.bottom) / available, minShare), 1 - minShare)
  }

  // 右列 split：问题面板贴底（VSCode Problems 位），editorSplit 是问题区占可用高度
  // （列高 − 分隔条 − 面板标题）的份额；从底部量指针位置。
  const editorSplitAt = (clientY: number) => {
    const bounds = editorPaneRef.current?.getBoundingClientRect()
    if (!bounds) return editorSplit
    const available = bounds.height - 5 - 36
    if (available <= 0) return editorSplit
    const minShare = Math.min(0.45, 120 / available)
    return Math.min(Math.max((bounds.bottom - clientY - 41) / available, minShare), 1 - minShare)
  }

  // 七条轨道始终同构：控制区 / 弹性留白 / 结果标题 / 结果正文 / 分隔条 / 跟随账户标题 / 跟随账户正文。
  // 正文高度由内容驱动：有真内容（权重列表 / 跟随账户）的轨道才 fr 分高，否则 auto 贴
  // 内容一行、剩余空间沉底；弹性留白只在两侧都不分高时 1fr（把面板钉在列底，与双收起的
  // 待遇一致），其余时间 0fr 让位。标题的固定 36px 与正文轨分离，避免 minmax 在触及下限
  // 时切换算法造成高度回弹。
  // 生效 tab 的加载骨架 / 错误提示属占位内容，同样占位分高；空仓与未试跑只有一行文案。
  // 坑（实测）：grid 里所有 fr 系数之和 < 1 时，fr 轨只吸收系数占比的剩余空间，余下的会被
  // auto 轨（Stretch auto Tracks 步）吃掉——所以单独成轨时必须用 1fr，只有双方都分高时才
  // 用 panelSplit / 1-panelSplit（两者恒和为 1）。
  const resultContentful =
    targetTab === 'effective'
      ? (weights.loading && weights.data == null) ||
        weights.error != null ||
        weights.recalculateError != null ||
        (weights.data?.calculated_at != null &&
          targetWeightSummary(weights.data.weights).entries.length > 0)
      : Boolean(calc.result?.valid && calc.result?.target)
  const resultFr = resultOpen && resultContentful
  const followersFr = followersOpen && followers.length > 0
  const inspectorRows = `auto minmax(0, ${resultFr || followersFr ? '0fr' : '1fr'}) 36px ${
    !resultOpen ? 'minmax(0, 0fr)' : resultFr ? `minmax(0, ${followersFr ? panelSplit : 1}fr)` : 'auto'
  } ${resultFr && followersFr ? '5px' : '0px'} 36px ${
    !followersOpen ? 'minmax(0, 0fr)' : followersFr ? `minmax(0, ${resultFr ? 1 - panelSplit : 1}fr)` : 'auto'
  }`

  // 右列轨道：代码区 / 分隔条 / 问题标题 / 问题正文；收起时正文归零、分隔条让位。
  const editorRows = problemsOpen
    ? `minmax(0, ${1 - editorSplit}fr) 5px 36px minmax(0, ${editorSplit}fr)`
    : 'minmax(0, 1fr) 0px 36px minmax(0, 0fr)'

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

  // 有 lite 即可渲染工作台（标题槽即时挂共享名）；全空才骨架，加载失败且无 lite 才报错。
  if (!pf && !lite && !portfolio.error) {
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
  if (portfolio.error && !pf) {
    return (
      <section>
        <ErrorNotice title="组合加载失败" error={portfolio.error} onRetry={portfolio.refresh} />
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
            {/* 市场是身份元数据：只读中性胶囊，与列表卡同位（不做编辑入口，依赖缺口是已知问题）。 */}
            {head?.market && (
              <Chip
                className="max-w-32 truncate"
                style={tDetail ? { viewTransitionName: `portfolio-market-${portfolioId}` } : undefined}
              >
                {head.market}
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
          {/* 描述是身份说明、不可编辑（接口只收名称与代码）：名称下一行小字，不占工作台的注意力预算。 */}
          {head?.description && (
            <p className="mt-1.5 text-[12.5px] leading-5 text-ink-3">{head.description}</p>
          )}

          <div className="flex-none">
            <div className="mt-4 flex flex-col gap-1.5">
                <Select<number | null>
                  ariaLabel="试跑数据来源"
                  value={calc.accountId}
                  onChange={calc.setAccountId}
                  options={calc.contextOptions}
                  className="w-full justify-between px-2.5 py-1.5 text-[13.5px]"
                />
                {/* 来源警示：选真实账户才升琥珀（主动交易有真实委托）。
                    样例来源不再加说明——Select 选项本身已写「不连接真实渠道」，此处零信号。 */}
                {calc.accountId != null && (
                <p className="border-l-2 border-warn pl-2 text-[12.5px] leading-5">
                  <InkRewrite
                    text="真实数据 · 主动交易将产生真实委托"
                    tone="label"
                    textClassName="text-warn"
                  />
                </p>
                )}
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

          </div>

          </aside>

          <div aria-hidden />

          {/* 「目标」面板：一个槽位、两个显式命名的来源——生效（持久快照，事实）/ 试跑（假设）。
              头部状态行随分段切换语义；试跑成功自动切到试跑分段（对应当前的自动展开）。 */}
          <PythonRunPanel
            kind="result"
            title="目标"
            open={resultOpen}
            onToggle={() => setResultOpen((open) => !open)}
            className="border-line border-t md:border-r"
            running={calc.validating}
            result={calc.editorResult}
            stale={targetTab === 'trial' && calc.stale}
            headerExtra={(
              <div className="flex flex-none items-center px-2">
                <Segmented
                  size="sm"
                  value={targetTab}
                  options={[
                    { value: 'effective', label: '生效' },
                    { value: 'trial', label: '试跑' },
                  ]}
                  onChange={setTargetTab}
                />
              </div>
            )}
            statusOverride={targetTab === 'effective' ? snapshotStatus : undefined}
            contentOverride={targetTab === 'effective' ? <SnapshotResult weights={weights} /> : undefined}
            resultContent={calc.result?.valid && calc.result.target ? <WeightResult target={calc.result.target} /> : null}
          />

          <div
            role="separator"
            aria-label="调整目标面板与跟随账户的高度"
            aria-orientation="horizontal"
            aria-valuemin={20}
            aria-valuemax={80}
            aria-valuenow={Math.round(panelSplit * 100)}
            tabIndex={resultFr && followersFr ? 0 : -1}
            inert={!(resultFr && followersFr)}
            title="拖动分配面板高度 · 双击平均分配"
            className={`group relative z-10 cursor-row-resize touch-none outline-none md:border-r md:border-line ${
              resultFr && followersFr ? 'block' : 'invisible'
            }`}
            onDoubleClick={() => {
              setPanelSplit(0.5)
              window.localStorage.setItem(PANEL_SPLIT_KEY, '0.5')
            }}
            onPointerDown={(event) => {
              if (!(resultFr && followersFr)) return
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

          {/* 跟随账户占原问题位：跟随关系是组合的静态元数据，跟试跑结果同属左列上下文。
              面板 chrome 与 PythonRunPanel 同构（36px 标题 + chevron 收放 + subgrid 正文）。 */}
          <section
            aria-label="跟随账户"
            className="row-span-2 grid min-h-0 overflow-hidden border-t border-line bg-surface [grid-template-rows:subgrid] md:border-r"
          >
            <header className={`flex h-9 flex-none items-stretch ${followersOpen ? 'border-b border-line' : ''}`}>
              <button
                type="button"
                aria-expanded={followersOpen}
                className={`flex cursor-pointer items-center gap-1.5 px-3.5 text-[12px] font-semibold tracking-wide text-ink-1 ${
                  followersOpen ? 'border-b border-accent' : ''
                }`}
                onClick={() => setFollowersOpen((open) => !open)}
              >
                <ChevronDown
                  size={13}
                  aria-hidden
                  className={`text-ink-3 transition-transform duration-200 motion-reduce:transition-none ${
                    followersOpen ? '' : '-rotate-90'
                  }`}
                />
                跟随账户 · {followers.length}
              </button>
              {/* 动作贴着它的作用对象：通知全部跟随账户立即调仓；有账户在途执行时禁用。 */}
              {followers.length > 0 && (
                <Tooltip
                  content={
                    anyFollowerRunning
                      ? '账户正在执行，结束后可通知'
                      : '通知全部跟随账户按最新目标立即调仓'
                  }
                >
                  <span className="ml-auto inline-flex flex-none items-center pr-2">
                    <button
                      type="button"
                      onClick={runFanout}
                      disabled={anyFollowerRunning}
                      className="flex cursor-pointer items-center gap-1 rounded-md px-2 py-1 text-[12px] font-semibold text-ink-2 hover:bg-fill hover:text-ink-1 disabled:cursor-default disabled:opacity-40 disabled:hover:bg-transparent"
                    >
                      <Zap size={12} aria-hidden />
                      立即执行
                    </button>
                  </span>
                </Tooltip>
              )}
            </header>
            <div inert={!followersOpen} className="min-h-0 flex-1 overflow-auto px-1.5 py-1.5 [scrollbar-gutter:stable]">
              <ErrorNotice title="触发执行失败" error={actionError} variant="mutation" onRetry={runFanout} />
              {followers.length > 0 ? (
                <ul className="flex flex-col">
                  {followers.map((account) => (
                    <li key={account.account_id}>
                      <Link
                        to={`/accounts/${account.account_id}`}
                        className="group flex items-center gap-2 rounded-[8px] px-2 py-1.5 hover:bg-fill"
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
              ) : (
                <p className="px-2 py-1.5 text-[13.5px] text-ink-3">暂无账户跟随该组合。</p>
              )}
            </div>
          </section>
        </div>

        {/* 右列：代码 + 问题面板共用一条水平分界（VSCode 底部 Problems 位），
            问题贴着它诊断的代码，错误行点击就地滚入可视区。 */}
        <div
          ref={editorPaneRef}
          className={`grid min-h-0 transition-[grid-template-rows] duration-200 motion-reduce:transition-none ${
            resizingPanels ? '!transition-none' : ''
          }`}
          style={{ gridTemplateRows: editorRows }}
        >
          <div className="flex min-h-[420px] min-w-0 flex-col bg-code-bg md:min-h-0">
          {/* 编辑辅助动作（粘贴 / 文档）与代码同列：console 布局里它们住代码上方工具条，
              workbench 无工具条，就落在代码页头栏；粘贴与空态大按钮互斥，只在有代码时出现。 */}
          <div className="flex h-8 flex-none items-center gap-3 border-b border-line bg-surface px-3 text-[12px] text-ink-2">
            <span className="font-[550] text-ink-1">目标函数</span>
            {code.trim() && (
              <button
                type="button"
                className="inline-flex cursor-pointer items-center gap-1 text-accent"
                onClick={() => void paste()}
              >
                <Clipboard size={12} /> 粘贴
              </button>
            )}
            <a className="text-accent" href="/docs/custom-calc" target="_blank" rel="noopener">
              开发文档 ↗
            </a>
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
            aria-label="调整代码与问题的高度"
            aria-orientation="horizontal"
            aria-valuemin={20}
            aria-valuemax={80}
            aria-valuenow={Math.round(editorSplit * 100)}
            tabIndex={problemsOpen ? 0 : -1}
            inert={!problemsOpen}
            title="拖动分配代码与问题的高度 · 双击平均分配"
            className={`group relative z-10 cursor-row-resize touch-none outline-none ${
              problemsOpen ? 'block' : 'invisible'
            }`}
            onDoubleClick={() => {
              setEditorSplit(0.35)
              window.localStorage.setItem(EDITOR_SPLIT_KEY, '0.35')
            }}
            onPointerDown={(event) => {
              if (!problemsOpen) return
              event.preventDefault()
              event.currentTarget.setPointerCapture(event.pointerId)
              setResizingPanels(true)
              setEditorSplit(editorSplitAt(event.clientY))
            }}
            onPointerMove={(event) => {
              if (event.currentTarget.hasPointerCapture(event.pointerId)) setEditorSplit(editorSplitAt(event.clientY))
            }}
            onPointerUp={(event) => {
              const finalSplit = editorSplitAt(event.clientY)
              if (event.currentTarget.hasPointerCapture(event.pointerId)) {
                event.currentTarget.releasePointerCapture(event.pointerId)
              }
              setEditorSplit(finalSplit)
              setResizingPanels(false)
              window.localStorage.setItem(EDITOR_SPLIT_KEY, String(finalSplit))
            }}
            onPointerCancel={() => setResizingPanels(false)}
            onKeyDown={(event) => {
              let next = editorSplit
              if (event.key === 'ArrowUp') next += 0.05
              else if (event.key === 'ArrowDown') next -= 0.05
              else if (event.key === 'Home') next = 0.2
              else if (event.key === 'End') next = 0.8
              else return
              event.preventDefault()
              next = Math.min(Math.max(next, 0.2), 0.8)
              setEditorSplit(next)
              window.localStorage.setItem(EDITOR_SPLIT_KEY, String(next))
            }}
          >
            <span className="absolute inset-x-0 top-1/2 h-px bg-line transition-colors duration-130 group-hover:bg-accent group-focus:bg-accent" />
          </div>

          <PythonRunPanel
            kind="problems"
            open={problemsOpen}
            onToggle={() => setProblemsOpen((open) => !open)}
            className="border-t border-line"
            running={calc.validating}
            result={calc.editorResult}
            stale={calc.stale}
            onRevealError={(line) => editorRef.current?.revealLine(line)}
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

      <ConfirmModal spec={confirm} onClose={() => setConfirm(null)} />
    </section>
  )
}
