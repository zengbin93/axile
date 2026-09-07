import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router'
import { RefreshCw, Save } from 'lucide-react'
import { useNavigate } from '@/components/ui/nav'
import { SectionLabel } from '@/components/ui/Card'
import { Segmented } from '@/components/ui/Segmented'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { InkRewrite } from '@/components/ui/InkRewrite'
import { PerformanceChart } from '@/components/viz/PerformanceChart'
import { AccountPageTitle } from '@/features/account/pageHead'
import { FeeControl } from '@/features/history/FeeControl'
import { getAccount, getAccountActivity, getPortfolioRecords } from '@/lib/api/accounts'
import { getPerformance, savePerformanceSettings } from '@/lib/api/performance'
import { usePolling } from '@/lib/hooks/usePolling'
import { withViewTransition } from '@/lib/viewTransition'
import { aggregateStats, buildEvents, filterRecords, filterScheduleSkips, type RangeKey } from '@/features/history/derive'
import { returnColor, returnText, settingsFromDraft, WEIGHT_MODES } from '@/features/history/performance'
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
  const [range, setRange] = useState<RangeKey>('all')
  const [view, setView] = useState<'cumulative' | 'daily'>('cumulative')
  const [hover, setHover] = useState<number | null>(null)
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
  const activity = usePolling(useCallback((s: AbortSignal) => getAccountActivity(accountId, { limit: 500 }, s), [accountId]), { queryKey: `account:${accountId}:activity:500`, intervalMs: 0 })
  const bindings = usePolling(useCallback((s: AbortSignal) => getPortfolioRecords(accountId, s), [accountId]), { queryKey: `account:${accountId}:portfolio-records`, intervalMs: 0 })
  const settings = saved ?? account.data ?? performance.data?.settings ?? accountPerformance.data?.settings
  const mode = draft?.mode ?? settings?.backtest_weight_type ?? 'ts'
  const fee = draft?.fee ?? String(Number(((settings?.backtest_fee_rate ?? 0) * 10000).toFixed(8)))
  const parsed = settingsFromDraft(mode, fee)
  const dirty = parsed != null && (parsed.backtest_weight_type !== settings?.backtest_weight_type || parsed.backtest_fee_rate !== settings?.backtest_fee_rate)

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
      setHover(null)
      void account.refresh()
      void refreshPerformance.current()
    } catch (error) {
      if (mounted.current) setSaveError(error instanceof Error ? error : new Error(String(error)))
    } finally {
      saveLock.current = false
      if (mounted.current) setSaving(false)
    }
  }

  const data = performance.data ?? accountPerformance.data
  const backtestBusy = performance.loading || performance.refreshing
  const active = data?.points[hover ?? data.points.length - 1]
  const daily = view === 'daily'
  const accountReturn = daily ? active?.account_daily_return : active?.account_return
  const portfolioReturn = daily ? active?.portfolio_daily_return : active?.portfolio_return
  const difference = accountReturn != null && portfolioReturn != null ? accountReturn - portfolioReturn : null
  const records = activity.data?.data.flatMap(item => item.kind === 'execution' ? [item.record] : []) ?? []
  const skips = activity.data?.data.flatMap(item => item.kind === 'schedule_skip' ? [item] : []) ?? []
  const ranged = filterRecords(records, range)
  const stats = aggregateStats(ranged, [])
  const events = buildEvents(bindings.data?.data ?? [], ranged, filterScheduleSkips(skips, records, range))

  return <section>
    <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
      <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1"><AccountPageTitle accountId={accountId} page="实盘绩效" name={account.data?.name} channel={account.data?.trade_channel} market={account.data?.market} /></div>
      <Segmented size="sm" value={range} options={RANGES} onChange={value => withViewTransition(() => { setHover(null); setRange(value) })} />
    </div>
    <div className="border-y border-line py-4">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <fieldset disabled={saving || !settings} className="flex min-w-0 flex-wrap items-center gap-x-6 gap-y-3 disabled:opacity-60">
          <div role="group" aria-label="回测模式" className="flex items-center gap-2"><span className="shrink-0 text-xs text-ink-3">回测模式</span><Segmented size="sm" value={mode} options={WEIGHT_MODES} onChange={value => setDraft({ mode: value, fee })} /></div>
          <FeeControl fee={fee} onChange={value => setDraft({ mode, fee: value })} onEditingChange={setEditingFee} />
        </fieldset>
        <div className="flex items-center gap-3">
          <button type="button" disabled={!dirty || saving || !settings} onClick={() => void save()} className="flex h-8 w-32 items-center justify-center gap-2 rounded border border-line text-sm disabled:opacity-40"><Save size={14} /><InkRewrite text={saving ? '保存中' : '保存并计算'} tone="label" /></button>
          <button type="button" aria-label="重新计算" title="重新计算" disabled={saving || backtestBusy} onClick={() => { setHover(null); void performance.refresh() }} className="flex h-8 w-8 items-center justify-center rounded border border-line disabled:opacity-40"><RefreshCw size={14} className={backtestBusy ? 'animate-spin motion-reduce:animate-none' : ''} /></button>
          <span role="status" className="w-12 shrink-0 text-xs text-ink-3"><InkRewrite text={dirty && !saving ? '待计算' : ''} tone="label" /></span>
        </div>
      </div>
      {!parsed && !editingFee && <p role="alert" className="mt-2 text-xs text-warn">费率须大于等于 0 且小于 10000 BP</p>}
      <ErrorNotice title="参数保存失败" error={saveError} />
      <ErrorNotice title="账户设置读取失败" error={account.error} onRetry={account.refresh} />
    </div>
    <ErrorNotice title="账户收益读取失败" error={performance.data ? null : accountPerformance.error} variant="compact" onRetry={accountPerformance.refresh} />
    {data && <div className="py-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
        <div className="flex min-w-0 flex-wrap items-center gap-x-6 gap-y-2">
          {([['账户收益', accountReturn, '%'], ['组合回测收益', portfolioReturn, '%'], ['收益差额', difference, ' 个百分点']] as const).map(([label, value, unit], index) =>
            <div key={label} className="flex flex-wrap items-baseline gap-2">
              <span className="flex items-center gap-1.5 text-xs text-ink-2">{index < 2 && <span aria-hidden className={`inline-block h-0.5 w-3 ${index === 0 ? 'bg-accent' : 'bg-ink-2'}`} />}{label}</span>
              <span className={`num inline-flex items-baseline gap-1 text-lg font-semibold ${index === 2 ? 'min-w-[14ch]' : 'min-w-[8ch]'} ${returnColor(value)}`}>
                {returnText(value, index === 2 ? '' : unit)}
                {index === 2 && <span className={`text-xs font-normal ${value == null ? 'invisible' : ''}`}>个百分点</span>}
              </span>
              {index === 1 && <span role="status" className="inline-block w-12 text-xs text-ink-3">{backtestBusy ? '计算中' : ''}</span>}
            </div>)}
        </div>
        <Segmented size="sm" value={view} options={VIEWS} onChange={value => withViewTransition(() => { setHover(null); setView(value) })} />
      </div>
      <div className="flex min-h-5 flex-wrap gap-x-2 text-xs text-ink-3">
        <span>{active?.date.replace('T', ' ') ?? '暂无收益数据'}</span>
        <span>· {data.settings.backtest_weight_type === 'ts' ? '时序' : '截面'} · 单边费率 {Number((data.settings.backtest_fee_rate * 10000).toFixed(8))} BP</span>
        <span>· 未调整出入金</span>
      </div>
      <ErrorNotice title={saved ? '参数已保存，组合回测失败' : '组合回测失败'} error={performance.error} variant="compact" onRetry={performance.refresh} />
      <PerformanceChart data={data} daily={daily} hoverIndex={hover} onHover={setHover} />
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-3">
        <span>基准 {data.baseline?.replace('T', ' ') ?? '—'}</span><span>截止 {data.end?.replace('T', ' ') ?? '—'}</span><span>{data.backtest_included ? `有效回测记录 ${data.used_record_count} / ` : ''}历史记录 {data.record_count}</span>
      </div>
      {data.gap && <p role="status" className="mt-3 break-words text-sm text-warn">组合收益自 {data.gap.time.replace('T', ' ')} 中断：{data.gap.reason}{data.gap.symbols.length ? `（${data.gap.symbols.join('、')}）` : ''}</p>}
      {data.invalid_asset_count > 0 && <p className="mt-2 text-xs text-warn">{data.invalid_asset_count} 条账户资产快照不可用</p>}
      {data.bindings.length > 0 && <div className="mt-3 flex flex-wrap gap-3 text-xs text-ink-3">{data.bindings.map((b, i) => <span key={i}>{b.time.replace('T', ' ')} · {b.portfolio_id == null ? '解绑' : `组合 #${b.portfolio_id}`}</span>)}</div>}
    </div>}
    {!data && <ErrorNotice title="组合回测失败" error={performance.error} variant="compact" onRetry={performance.refresh} />}
    <div className="border-t border-line py-4">
      <SectionLabel>近期执行</SectionLabel>
      <ErrorNotice title="执行记录读取失败" error={activity.error} onRetry={activity.refresh} />
      <div className="text-sm text-ink-2">成功 {stats.fills} · 空跑 {stats.noops} · 失败 {stats.fails} · 终止 {stats.terminated} · 跳过 {filterScheduleSkips(skips, records, range).length} · 手续费 {stats.fee.toFixed(4)} {stats.currency}</div>
      <SectionLabel>账户时间线</SectionLabel>
      <ErrorNotice title="绑定记录读取失败" error={bindings.error} onRetry={bindings.refresh} />
      {events.length === 0 ? <p className="text-sm text-ink-3">本区间无异常事件</p> : events.map((event, i) => <div key={i} className="flex flex-wrap items-baseline gap-3 border-b border-line py-3 text-sm">
        <span className="text-xs text-ink-3">{event.date}</span><span className={event.kind === 'fail' ? 'text-warn' : 'text-ink-2'}>{event.tag}</span>
        {event.kind === 'fail' && event.executionId ? <button className="text-left hover:underline" onClick={() => navigate(`/accounts/${accountId}/executions/${event.executionId}`)}>{event.text}</button> : <span>{event.text}</span>}
      </div>)}
    </div>
  </section>
}
