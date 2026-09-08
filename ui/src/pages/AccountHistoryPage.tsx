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
import { getAccount } from '@/lib/api/accounts'
import { getPortfolios } from '@/lib/api/portfolios'
import { shanghaiDay, shanghaiLabel } from '@/features/history/costs'
import { reconcileSelection, type ChartSelection } from '@/features/history/chartModel'
import { CostDiagnostics } from '@/features/history/CostDiagnostics'
import { getPerformanceCosts, selectionQuery, savePerformanceSettings } from '@/lib/api/performance'
import { usePerformanceSnapshot } from '@/features/history/usePerformanceSnapshot'
import { snapshotPending } from '@/features/history/performanceCache'
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
  const performance = usePerformanceSnapshot(accountId, range)
  const refreshPerformance = useRef(performance.refresh)
  useEffect(() => { refreshPerformance.current = performance.refresh }, [performance.refresh])
  const snapshot = performance.data
  const data = snapshot?.result
  useEffect(() => { if (data) setSelection(current => reconcileSelection(current, data.points)) }, [data])
  const selectionKey = JSON.stringify(selectionQuery(selection))
  const intervalCosts = usePolling(useCallback((s: AbortSignal) => getPerformanceCosts(accountId, { snapshot_id: snapshot!.snapshot_id!, range, dimension: 'summary', ...JSON.parse(selectionKey) }, s), [accountId, snapshot?.snapshot_id, range, selectionKey]), {
    queryKey: `performance-summary:${accountId}:${snapshot?.snapshot_id}:${range}:${selectionKey}`, intervalMs: 0, enabled: !!snapshot?.snapshot_id && selection?.kind === 'interval',
  })
  const portfolios = usePolling(useCallback((s: AbortSignal) => getPortfolios(s), []), { queryKey: 'performance-portfolios', intervalMs: 0 })
  const portfolioNames = useMemo(() => new Map(portfolios.data?.data.flatMap(p => p.id == null ? [] : [[p.id, p.name] as const]) ?? []), [portfolios.data])
  const settings = saved ?? account.data ?? data?.settings
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

  const backtestBusy = snapshotPending(snapshot) || performance.checking
  const active = data?.points[data.points.length - 1]
  const daily = view === 'daily'
  const accountReturn = active?.account_return
  const portfolioReturn = active?.portfolio_return
  const difference = accountReturn != null && portfolioReturn != null ? portfolioReturn - accountReturn : null
  const costs = useMemo(() => snapshot?.result ? new Map(Object.entries(snapshot.daily_costs)) : null, [snapshot?.result, snapshot?.daily_costs])
  const events = snapshot?.events ?? []
  const calculationError = snapshot?.error ? new Error(snapshot.error) : performance.error
  const pendingSettings = !!data && settings?.backtest_fee_rate !== data.settings.backtest_fee_rate

  const controls = <div data-testid="performance-controls" className="flex min-w-0 flex-wrap items-center gap-2 sm:ml-auto sm:justify-end">
        <fieldset disabled={saving || !settings} className="flex min-w-0 flex-wrap items-center gap-2 disabled:opacity-60">
          <FeeControl fee={fee} onChange={value => setDraft({ mode, fee: value })} onEditingChange={setEditingFee} />
        </fieldset>
        <div className="flex items-center gap-2">
          <button type="button" aria-label={saving ? '保存中' : '保存并计算'} title={dirty ? '参数已修改，保存并计算' : '保存并计算'} disabled={!dirty || saving || !settings} onClick={() => void save()} className="flex h-9 w-9 items-center justify-center rounded border border-line text-sm disabled:opacity-40"><Save size={14} /></button>
          <button type="button" aria-label="刷新绩效与成本" title="刷新绩效与成本" disabled={saving || backtestBusy} onClick={() => void performance.refresh()} className="flex h-9 w-9 items-center justify-center rounded border border-line disabled:opacity-40"><RefreshCw size={14} className={backtestBusy ? 'animate-spin motion-reduce:animate-none' : ''} /></button>
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
        {data ? <dl className="flex min-w-0 flex-wrap items-baseline text-xs text-ink-3">
          <div className="whitespace-nowrap"><dt className="sr-only">基准</dt><dd className="inline">{data.baseline ? <time dateTime={data.baseline} title={shanghaiLabel(data.baseline)}>{shanghaiDay(data.baseline)}</time> : '—'}</dd><span aria-hidden="true">&nbsp;→&nbsp;</span><dt className="sr-only">截止</dt><dd className="inline">{data.end ? <time dateTime={data.end} title={shanghaiLabel(data.end)}>{shanghaiDay(data.end)}</time> : '—'}</dd><span aria-hidden="true">&nbsp;·</span></div>
          <div className="whitespace-nowrap"><dt className="sr-only">有效回测记录</dt><dd className="inline">回测 {data.backtest_included ? data.used_record_count : 0}</dd><span aria-hidden="true">&nbsp;·</span></div>
          <div className="whitespace-nowrap"><dt className="sr-only">历史记录</dt><dd className="inline">历史 {data.record_count}</dd></div>
        </dl> : <span className="shrink-0 text-xs text-ink-3">{snapshot?.data_until ? `数据截止 ${shanghaiLabel(snapshot.data_until)}` : '暂无绩效快照'}</span>}
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
    {(backtestBusy || pendingSettings) && <div role="status" className="flex flex-wrap items-center gap-x-4 gap-y-1 py-1 text-xs text-ink-3" data-testid="performance-status">
      {backtestBusy && <span>{data ? '后台更新中' : '正在准备绩效'}</span>}
      {pendingSettings && <span className="text-warn">新费率 {Number(((settings?.backtest_fee_rate ?? 0) * 10000).toFixed(8))} BP 待计算</span>}
    </div>}
    <ErrorNotice title={data ? '更新失败，保留上次结果' : '绩效读取失败'} error={calculationError} variant="compact" onRetry={performance.refresh} />
    <ErrorNotice title="区间成本读取失败" error={intervalCosts.error} variant="compact" onRetry={intervalCosts.refresh} />
    {data && <div className="pb-4">
      <PerformanceChart key={range} data={data} daily={daily} costs={costs} intervalCost={intervalCosts.error || intervalCosts.loading ? null : intervalCosts.data?.summary ?? null} onSelect={setSelection} selection={selection} portfolioNames={portfolioNames} controls={controls} />
      {data.gap && <p role="status" className="mt-3 break-words text-sm text-warn">组合收益自 {data.gap.time.replace('T', ' ')} 中断：{data.gap.reason}{data.gap.symbols.length ? `（${data.gap.symbols.join('、')}）` : ''}</p>}
      {data.invalid_asset_count > 0 && <p className="mt-2 text-xs text-warn">{data.invalid_asset_count} 条账户资产快照不可用</p>}
    </div>}
    {snapshot?.snapshot_id && <CostDiagnostics key={`${snapshot.snapshot_id}:${range}`} snapshotId={snapshot.snapshot_id} range={range} selection={selection} onClear={clearSelection} accountId={accountId} onExpired={performance.check} />}
    <div className="border-t border-line py-4">
      <SectionLabel>账户时间线</SectionLabel>
      {events.length === 0 ? <p className="text-sm text-ink-3">本区间无异常事件</p> : events.slice(0, showEvents ? undefined : 8).map((event, i) => <div key={i} className="flex flex-wrap items-baseline gap-3 border-b border-line py-2 text-xs">
        <span className="text-ink-3">{shanghaiLabel(event.time)}</span><span className={event.tag === '失败' ? 'text-warn' : 'text-ink-2'}>{event.tag}</span>
        {event.executionId ? <button className="min-h-9 break-all text-left hover:underline" onClick={() => navigate(`/accounts/${accountId}/executions/${event.executionId}`)}>{event.text}</button> : <span>{event.text}</span>}
      </div>)}
      {events.length > 8 && <button className="min-h-9 text-xs text-accent" onClick={() => withViewTransition(() => setShowEvents(!showEvents))}>{showEvents ? '收起' : `展开全部 ${events.length} 条`}</button>}
      {(snapshot?.event_count ?? 0) > events.length && <p className="text-xs text-ink-3">共 {snapshot?.event_count} 条事件，显示最近 {events.length} 条</p>}
    </div>
  </section>
}
