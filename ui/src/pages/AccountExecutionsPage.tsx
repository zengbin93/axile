import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useParams, useSearchParams } from 'react-router'
import { ChevronRight, RefreshCw, Search } from 'lucide-react'
import { Link } from '@/components/ui/nav'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { Skeleton } from '@/components/ui/Skeleton'
import { Segmented } from '@/components/ui/Segmented'
import { Select } from '@/components/ui/Select'
import { AccountPageTitle } from '@/features/account/pageHead'
import { journalAmount as amount, journalTime as time, journalExecutions, journalSymbols, journalWindow, loadJournal, qualityOf, type JournalRange } from '@/features/account/executionJournal'
import { Field, Slip, SymbolGroup, EXEC_COLS, SYMBOL_COLS, type Expansion } from '@/features/account/JournalRows'
import { displayCurrencyUnit } from '@/lib/format'
import { usePolling } from '@/lib/hooks/usePolling'
import { useRemountFade } from '@/lib/viewTransition'
import { useDomainStore } from '@/stores/domain'

const VIEWS = [{ value: 'executions', label: '按执行' }, { value: 'symbols', label: '按品种' }]
const RANGES: { value: JournalRange; label: string }[] = [
  { value: '7', label: '近 7 天' }, { value: '30', label: '近 30 天' },
  { value: '90', label: '近 90 天' }, { value: 'custom', label: '自定义' },
]
const STATUSES = ['全部状态', '已完成', '部分到位', '失败', '已终止', '已跳过', '无成交'].map((label) => ({ value: label, label }))
const SORTS = [{ value: 'value', label: '成交额从高到低' }, { value: 'slippage', label: '不利滑点优先' }]
const INPUT = 'min-w-0 rounded-lg border border-line bg-surface px-3 py-1.5 text-[13px] text-ink-1 outline-none focus:border-accent'
interface Visit { search: string; expanded: Record<string, Expansion>; count: number; scroll: number }
// 返回详情前的视图只保存在当前标签页内；URL 承载可分享的筛选条件。
const visits = new Map<number, Visit>()
function today(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function AccountExecutionsPage() {
  const { id } = useParams()
  return <ExecutionJournal key={id} accountId={Number(id)} />
}

function ExecutionJournal({ accountId }: { accountId: number }) {
  const [params, setParams] = useSearchParams()
  const location = useLocation()
  const item = useDomainStore((s) => s.accounts?.find((a) => a.account_id === accountId))
  const view = params.get('view') === 'symbols' ? 'symbols' : 'executions'
  const range: JournalRange = RANGES.some((r) => r.value === params.get('range')) ? params.get('range') as JournalRange : '30'
  const from = params.get('from') ?? today()
  const to = params.get('to') ?? today()
  const keyword = params.get('symbol') ?? ''
  const status = STATUSES.some((s) => s.value === params.get('status')) ? params.get('status')! : '全部状态'
  const sort = params.get('sort') === 'slippage' ? 'slippage' : 'value'
  const initial = useRef(visits.get(accountId))
  const restored = initial.current?.search === location.search ? initial.current : undefined
  const [expanded, setExpanded] = useState<Record<string, Expansion>>(restored?.expanded ?? {})
  const [count, setCount] = useState(restored?.count ?? 50)
  const restoreScroll = useRef(restored?.scroll ?? 0)
  const window = journalWindow(range, from, to)
  const start = window?.start ?? 0
  const end = window?.end ?? 0
  const poll = usePolling(useCallback((signal: AbortSignal) => loadJournal(accountId, { start, end }, signal), [accountId, start, end]), {
    queryKey: `account:${accountId}:journal:${start}:${end}`, intervalMs: 0, enabled: window != null,
  })
  const executions = useMemo(() => journalExecutions(poll.data ?? []), [poll.data])
  const symbols = useMemo(() => journalSymbols(executions, keyword).sort((a, b) => sort === 'slippage'
    ? (a.slippage ?? Infinity) - (b.slippage ?? Infinity) || b.value - a.value : b.value - a.value), [executions, keyword, sort])
  const filtered = useMemo(() => executions.filter((e) => (status === '全部状态' || e.status === status)
    && (!keyword.trim() || e.symbols.some((s) => s.toLowerCase().includes(keyword.trim().toLowerCase())))), [executions, status, keyword])
  const summary = useMemo(() => qualityOf(symbols.flatMap((s) => s.trades)), [symbols])
  const fade = useRemountFade(view)
  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    next.set(key, value)
    setParams(next, { replace: true, preventScrollReset: true })
    setCount(50)
  }
  const snapshot = useRef<Visit>({ search: location.search, expanded, count, scroll: 0 })
  useEffect(() => { snapshot.current = { ...snapshot.current, search: location.search, expanded, count } }, [location.search, expanded, count])
  useEffect(() => {
    const main = document.querySelector('main.app-workspace')
    const saveScroll = () => { snapshot.current.scroll = main?.scrollTop ?? 0 }
    main?.addEventListener('scroll', saveScroll, { passive: true })
    return () => { main?.removeEventListener('scroll', saveScroll); visits.set(accountId, snapshot.current) }
  }, [accountId])
  useLayoutEffect(() => {
    if (!poll.data || !restoreScroll.current) return
    const main = document.querySelector('main.app-workspace')
    if (main) main.scrollTop = restoreScroll.current
    snapshot.current.scroll = restoreScroll.current
    restoreScroll.current = 0
  }, [poll.data])
  const detailLink = (executionId: string | null) => executionId ? <Link
    to={`/accounts/${accountId}/executions/${executionId}`}
    state={{ journalReturn: `${location.pathname}${location.search}` }}
    onClick={() => { visits.set(accountId, { ...snapshot.current, scroll: document.querySelector('main.app-workspace')?.scrollTop ?? 0 }) }}
    className="inline-flex items-center text-accent hover:underline" aria-label={`查看执行 ${executionId}`}>
    详情<ChevronRight size={13} aria-hidden />
  </Link> : <span className="text-ink-3">—</span>

  return <section>
    <div className="mb-5 flex items-center justify-between gap-3">
      <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1"><AccountPageTitle accountId={accountId} page="执行记录" name={item?.name} channel={item?.trade_channel} market={item?.market} /></div>
      <button type="button" aria-label="刷新执行记录" title="刷新执行记录" disabled={poll.loading || poll.refreshing || !window} onClick={() => void poll.refresh()} className="flex size-8 shrink-0 items-center justify-center rounded-md text-ink-3 hover:bg-fill disabled:opacity-40"><RefreshCw size={16} className={poll.refreshing ? 'animate-spin motion-reduce:animate-none' : ''} /></button>
    </div>
    <div className="flex flex-wrap items-center gap-3 border-b border-line pb-4">
      <Segmented size="sm" value={view} options={VIEWS} onChange={(v) => update('view', v)} />
      <Select ariaLabel="时间范围" value={range} options={RANGES} onChange={(v) => update('range', v)} />
      <label className="relative min-w-0 flex-1 sm:max-w-64"><Search size={14} className="pointer-events-none absolute left-2.5 top-2.5 text-ink-3" aria-hidden /><input aria-label="搜索品种" placeholder="搜索品种" value={keyword} onChange={(e) => update('symbol', e.target.value)} className={`${INPUT} w-full pl-8`} /></label>
      {view === 'executions' ? <Select ariaLabel="执行状态" value={status} options={STATUSES} onChange={(v) => update('status', v)} /> : <Select ariaLabel="品种排序" value={sort} options={SORTS} onChange={(v) => update('sort', v)} />}
    </div>
    <div inert={range !== 'custom'} className={`grid transition-[grid-template-rows] duration-200 motion-reduce:transition-none ${range === 'custom' ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}>
      <div className="min-h-0 overflow-hidden"><div className="flex flex-wrap items-center gap-3 py-3">
        <label className="flex min-w-0 items-center gap-2 text-xs text-ink-3">开始<input aria-label="开始日期" type="date" value={from} max={to} onChange={(e) => update('from', e.target.value)} className={INPUT} /></label>
        <label className="flex min-w-0 items-center gap-2 text-xs text-ink-3">结束<input aria-label="结束日期" type="date" value={to} min={from} onChange={(e) => update('to', e.target.value)} className={INPUT} /></label>
      </div></div>
    </div>
    {!window && <p role="alert" className="py-4 text-sm text-warn">请选择有效的起止日期，结束日期不能早于开始日期。</p>}
    <ErrorNotice title="执行记录加载失败" error={poll.error} variant={poll.data ? 'stale' : 'section'} updatedAt={poll.updatedAt} onRetry={poll.refresh} />
    {poll.loading && <div aria-busy="true" aria-label="正在加载执行记录">{Array.from({ length: 7 }, (_, i) => <div key={i} className="flex min-h-20 items-center gap-6 border-b border-line"><Skeleton className="h-3 w-28" /><Skeleton className="h-3 w-1/3" /></div>)}</div>}
    {poll.data && <div key={view} className={fade ? 'panel-fade-in' : ''}>
      <div className="flex min-h-14 flex-wrap items-center justify-between gap-x-6 gap-y-2 py-3 text-xs text-ink-3">
        <span>{view === 'executions' ? `${filtered.length} 条记录` : `${symbols.length} 个品种 · ${summary.nTrades} 笔成交 · 成交额 ${summary.amountComplete ? amount(summary.value) : '—'} ${displayCurrencyUnit(item?.currency ?? '')}`}</span>
        <span title="按成交额加权；覆盖率为具有参考价和方向的有效成交额占比。到达报价不完整时使用到达最新价。">滑点相对到达价 · 正值为价格改善{view === 'symbols' && summary.nTrades > 0 ? ` · ${summary.amountComplete ? `有效覆盖 ${(summary.coverage * 100).toFixed(0)}%` : '成交额数据不完整'}` : ''}</span>
      </div>
      {view === 'executions' ? <>
        <div className={`${EXEC_COLS} hidden border-y border-line px-3 py-2 text-xs text-ink-3 xl:grid`}><span>时间</span><span>执行摘要</span><span>状态</span><span className="text-right">成交额</span><span className="text-right">平均滑点</span><span /></div>
        {filtered.slice(0, count).map((row) => {
          const q = qualityOf(row.trades)
          return <div key={row.key} className={`${EXEC_COLS} items-baseline border-b border-line px-3 py-4 text-[13px]`}>
            <span className="num text-xs text-ink-3">{time(row.time)}</span>
            <span className="col-span-2 min-w-0 break-words text-ink-2 xl:col-span-1">{row.description}</span>
            <span className={row.warning ? 'text-warn' : 'text-ink-2'}>{row.status}</span>
            <Field label="成交额"><span className="num">{q.nTrades && q.amountComplete ? amount(q.value) : '—'}</span></Field>
            <Field label="滑点"><Slip quality={q} /></Field>
            <span className="text-right">{detailLink(row.executionId)}</span>
          </div>
        })}
        {filtered.length === 0 && <p className="py-16 text-center text-sm text-ink-3">所选范围内无匹配记录</p>}
        {filtered.length > 0 && <div className="flex items-center gap-4 py-4 text-xs text-ink-3"><span>已展示 {Math.min(count, filtered.length)} / {filtered.length} 条</span>{count < filtered.length && <button type="button" onClick={() => setCount(count + 50)} className="text-accent hover:underline">加载更多</button>}</div>}
      </> : <>
        <div className={`${SYMBOL_COLS} hidden border-y border-line px-3 py-2 text-xs text-ink-3 xl:grid`}><span>品种</span><span className="text-right">成交额</span><span className="text-right">平均滑点</span><span className="text-right">成交笔数</span><span className="text-right">最近成交</span><span /></div>
        {symbols.map((row) => <SymbolGroup key={row.symbol} row={row} expansion={expanded[row.symbol] ?? { open: false, count: 10, side: 'all' }} update={(next) => setExpanded((prev) => ({ ...prev, [row.symbol]: next }))} detailLink={detailLink} />)}
        {symbols.length === 0 && <p className="py-16 text-center text-sm text-ink-3">所选范围内无匹配成交</p>}
      </>}
    </div>}
  </section>
}
