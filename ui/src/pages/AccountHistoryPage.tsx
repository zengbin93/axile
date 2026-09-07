import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router'
import { RefreshCw, Save } from 'lucide-react'
import { useNavigate } from '@/components/ui/nav'
import { SectionLabel } from '@/components/ui/Card'
import { Segmented } from '@/components/ui/Segmented'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { PerformanceChart } from '@/components/viz/PerformanceChart'
import { AccountPageTitle } from '@/features/account/pageHead'
import { FeeControl } from '@/features/history/FeeControl'
import { getAccount, getPortfolioRecords } from '@/lib/api/accounts'
import { getPortfolios } from '@/lib/api/portfolios'
import { costExecutions, dailyCosts, loadPerformanceActivity, shanghaiLabel, shanghaiTime } from '@/features/history/costs'
import { reconcileSelection, type ChartSelection } from '@/features/history/chartModel'
import { performanceEvents } from '@/features/history/events'
import { CostDiagnostics } from '@/features/history/CostDiagnostics'
import { getPerformance, savePerformanceSettings } from '@/lib/api/performance'
import { usePolling } from '@/lib/hooks/usePolling'
import { withViewTransition } from '@/lib/viewTransition'
import { useDomainStore } from '@/stores/domain'
import { type RangeKey } from '@/features/history/derive'
import { settingsFromDraft } from '@/features/history/performance'
import type { PerformanceSettings } from '@/types/api'

const RANGES: Array<{ value: RangeKey; label: string }> = [
  { value: '30', label: '30 天' }, { value: '90', label: '90 天' }, { value: 'all', label: '全部' },
]
const VIEWS: Array<{ value: 'cumulative' | 'daily'; label: string }> = [
  { value: 'cumulative', label: '累计' }, { value: 'daily', label: '每日' },
]

export function AccountHistoryPage() {
  const { id } = useParams()
  return <AccountHistory key={id} accountId={Number(id)} />
}

function AccountHistory({ accountId }: { accountId: number }) {
  const navigate = useNavigate()
  const item = useDomainStore(s => s.accounts?.find(account => account.account_id === accountId))
  const [range, setRange] = useState<RangeKey>('all')
  const [view, setView] = useState<'cumulative' | 'daily'>('cumulative')
  const [selection, setSelection] = useState<ChartSelection>(null)
  const clearSelection = useCallback(() => setSelection(null), [])
  const [showEvents, setShowEvents] = useState(false)
  const [draft, setDraft] = useState<{ mode: 'ts' | 'cs'; fee: string } | null>(null)
  const [saved, setSaved] = useState<PerformanceSettings | null>(null)
  const [saving, setSaving] = useState(false)
  const [editingFee, setEditingFee] = useState(false)
  const [saveError, setSaveError] = useState<Error | null>(null)
  const mounted = useRef(true)
  const saveLock = useRef(false)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const account = usePolling(useCallback((s: AbortSignal) => getAccount(accountId, s), [accountId]), { queryKey: `account:${accountId}`, intervalMs: 0 })
  const performance = usePolling(useCallback((s: AbortSignal) => getPerformance(accountId, range, s), [accountId, range]), {
    queryKey: `performance:${accountId}:${range}:full`, intervalMs: 0,
  })
  const accountPerformance = usePolling(useCallback((s: AbortSignal) => getPerformance(accountId, range, s, false), [accountId, range]), {
    queryKey: `performance:${accountId}:${range}:account`, intervalMs: 0,
  })
  const refreshPerformance = useRef(performance.refresh)
  useEffect(() => { refreshPerformance.current = performance.refresh }, [performance.refresh])
  const data = performance.data ?? accountPerformance.data
  useEffect(() => { if (data) setSelection(current => reconcileSelection(current, data.points)) }, [data])
  const start = data?.baseline ? shanghaiTime(data.baseline) : null
  const end = data?.end ? shanghaiTime(data.end) + 1 : null
  const activity = usePolling(useCallback((s: AbortSignal) => loadPerformanceActivity(accountId, { start: start!, end: end! }, s), [accountId, start, end]), {
    queryKey: `performance-activity:${accountId}:${start}:${end}`, intervalMs: 0, enabled: start != null && end != null,
  })
  const portfolios = usePolling(useCallback((s: AbortSignal) => getPortfolios(s), []), { queryKey: 'performance-portfolios', intervalMs: 0 })
  const portfolioNames = useMemo(() => new Map(portfolios.data?.data.flatMap(p => p.id == null ? [] : [[p.id, p.name] as const]) ?? []), [portfolios.data])
  const bindings = usePolling(useCallback((s: AbortSignal) => getPortfolioRecords(accountId, s), [accountId]), { queryKey: `account:${accountId}:portfolio-records`, intervalMs: 0 })
  const settings = saved ?? account.data ?? performance.data?.settings ?? accountPerformance.data?.settings
  const mode = 'cs'
  const fee = draft?.fee ?? String(Number(((settings?.backtest_fee_rate ?? 0) * 10000).toFixed(8)))
  const parsed = settingsFromDraft(mode, fee)
  const dirty = parsed != null && parsed.backtest_fee_rate !== settings?.backtest_fee_rate

  const save = async () => {
    if (!parsed || saveLock.current) return
    saveLock.current = true
    setSaving(true)
    setSaveError(null)
    try {
      const next = await savePerformanceSettings(accountId, parsed)
      if (!mounted.current) return
      setSaved(next)
      setDraft(null)
      void account.refresh()
      void refreshPerformance.current()
    } catch (error) {
      if (mounted.current) setSaveError(error instanceof Error ? error : new Error(String(error)))
    } finally {
      saveLock.current = false
      if (mounted.current) setSaving(false)
    }
  }

  const backtestBusy = performance.loading || performance.refreshing
  const active = data?.points[data.points.length - 1]
  const daily = view === 'daily'
  const accountReturn = active?.account_return
  const portfolioReturn = active?.portfolio_return
  const difference = accountReturn != null && portfolioReturn != null ? portfolioReturn - accountReturn : null
  const executions = useMemo(() => costExecutions(activity.error || activity.refreshing ? [] : activity.data ?? []), [activity.data, activity.error, activity.refreshing])
  const costs = useMemo(() => activity.data && !activity.error && !activity.refreshing ? dailyCosts(executions) : null, [activity.data, activity.error, activity.refreshing, executions])
  const events = start != null && end != null ? performanceEvents(bindings.data?.data ?? [], activity.error ? [] : activity.data ?? [], { start, end }, portfolioNames) : []

  const controls = <div data-testid="performance-controls" className="flex min-w-0 flex-wrap items-center gap-2 sm:ml-auto sm:justify-end">
        <fieldset disabled={saving || !settings} className="flex min-w-0 flex-wrap items-center gap-2 disabled:opacity-60">
          <FeeControl fee={fee} onChange={value => setDraft({ mode, fee: value })} onEditingChange={setEditingFee} />
        </fieldset>
        <div className="flex items-center gap-2">
          <button type="button" aria-label={saving ? '保存中' : '保存并计算'} title={dirty ? '参数已修改，保存并计算' : '保存并计算'} disabled={!dirty || saving || !settings} onClick={() => void save()} className="flex h-9 w-9 items-center justify-center rounded border border-line text-sm disabled:opacity-40"><Save size={14} /></button>
          <button type="button" aria-label="刷新绩效与成本" title="刷新绩效与成本" disabled={saving || backtestBusy} onClick={() => { void performance.refresh(); void accountPerformance.refresh(); void activity.refresh(); void bindings.refresh(); void portfolios.refresh() }} className="flex h-9 w-9 items-center justify-center rounded border border-line disabled:opacity-40"><RefreshCw size={14} className={backtestBusy ? 'animate-spin motion-reduce:animate-none' : ''} /></button>
          <span role="status" className="sr-only">{dirty && !saving ? '参数已修改，待计算' : ''}</span>
        </div>
        <Segmented size="sm" value={view} options={VIEWS} onChange={value => withViewTransition(() => setView(value))} />
        </div>

  return <section className="min-w-0 [&_button]:min-h-9">
    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
      <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
        <AccountPageTitle
          accountId={accountId}
          page="实盘绩效"
          name={account.data?.name ?? item?.name}
          channel={account.data?.trade_channel ?? item?.trade_channel}
          market={account.data?.market ?? item?.market}
        />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Segmented size="sm" value={range} options={RANGES} onChange={value => withViewTransition(() => { setSelection(null); setRange(value) })} />
      </div>
    </div>
    <div className="border-t border-line pt-2">
      {!data && controls}
      {difference != null && difference < 0 && <p className="mt-1 text-xs text-warn">账户收益高于回测，待核对差异</p>}
      {!parsed && !editingFee && <p role="alert" className="mt-2 text-xs text-warn">费率须大于等于 0 且小于 10000 BP</p>}
      <ErrorNotice title="参数保存失败" error={saveError} />
      <ErrorNotice title="账户设置读取失败" error={account.error} onRetry={account.refresh} />
    </div>
    <ErrorNotice title="账户收益读取失败" error={performance.data ? null : accountPerformance.error} variant="compact" onRetry={accountPerformance.refresh} />
    {data && <div className="pb-4">
      <ErrorNotice title={saved ? '参数已保存，组合回测失败' : '组合回测失败'} error={performance.error} variant="compact" onRetry={performance.refresh} />
      <PerformanceChart key={range} data={data} daily={daily} costs={costs} executions={executions} onSelect={setSelection} selection={selection} portfolioNames={portfolioNames} controls={controls} />
      <details className="mt-2 text-xs text-ink-3"><summary className="min-h-9 cursor-pointer py-2">数据明细</summary><div className="flex flex-wrap gap-x-4 gap-y-1">
        <span>基准 {data.baseline?.replace('T', ' ') ?? '—'}</span><span>截止 {data.end?.replace('T', ' ') ?? '—'}</span><span>{data.backtest_included ? `有效回测记录 ${data.used_record_count} / ` : ''}历史记录 {data.record_count}</span>
      </div></details>
      {data.gap && <p role="status" className="mt-3 break-words text-sm text-warn">组合收益自 {data.gap.time.replace('T', ' ')} 中断：{data.gap.reason}{data.gap.symbols.length ? `（${data.gap.symbols.join('、')}）` : ''}</p>}
      {data.invalid_asset_count > 0 && <p className="mt-2 text-xs text-warn">{data.invalid_asset_count} 条账户资产快照不可用</p>}
    </div>}
    {!data && <ErrorNotice title="组合回测失败" error={performance.error} variant="compact" onRetry={performance.refresh} />}
    <ErrorNotice title="执行成本读取失败，汇总未发布" error={activity.error} onRetry={activity.refresh} />
    {activity.loading || activity.refreshing ? <p role="status" className="py-4 text-sm text-ink-3">正在读取完整执行区间</p> : costs && <CostDiagnostics key={`${start}:${end}`} executions={executions} selection={selection} onClear={clearSelection} accountId={accountId} />}
    <div className="border-t border-line py-4">
      <SectionLabel>账户时间线</SectionLabel>
      <ErrorNotice title="绑定记录读取失败" error={bindings.error} onRetry={bindings.refresh} />
      {events.length === 0 ? <p className="text-sm text-ink-3">本区间无异常事件</p> : events.slice(0, showEvents ? undefined : 8).map((event, i) => <div key={i} className="flex flex-wrap items-baseline gap-3 border-b border-line py-2 text-xs">
        <span className="text-ink-3">{shanghaiLabel(event.time)}</span><span className={event.tag === '失败' ? 'text-warn' : 'text-ink-2'}>{event.tag}</span>
        {event.executionId ? <button className="min-h-9 break-all text-left hover:underline" onClick={() => navigate(`/accounts/${accountId}/executions/${event.executionId}`)}>{event.text}</button> : <span>{event.text}</span>}
      </div>)}
      {events.length > 8 && <button className="min-h-9 text-xs text-accent" onClick={() => withViewTransition(() => setShowEvents(!showEvents))}>{showEvents ? '收起' : `展开全部 ${events.length} 条`}</button>}
    </div>
  </section>
}
