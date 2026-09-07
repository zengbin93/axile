import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router'
import { RefreshCw, Save } from 'lucide-react'
import { useNavigate } from '@/components/ui/nav'
import { SectionLabel } from '@/components/ui/Card'
import { Segmented } from '@/components/ui/Segmented'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { PerformanceChart } from '@/components/viz/PerformanceChart'
import { AccountPageTitle } from '@/features/account/pageHead'
import { getAccount, getAccountActivity, getPortfolioRecords } from '@/lib/api/accounts'
import { getPerformance, savePerformanceSettings } from '@/lib/api/performance'
import { usePolling } from '@/lib/hooks/usePolling'
import { withViewTransition } from '@/lib/viewTransition'
import { aggregateStats, buildEvents, filterRecords, filterScheduleSkips, type RangeKey } from '@/features/history/derive'
import { returnText, settingsFromDraft, WEIGHT_MODES } from '@/features/history/performance'
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
  const [saveError, setSaveError] = useState<Error | null>(null)
  const mounted = useRef(true)
  const saveLock = useRef(false)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const account = usePolling(useCallback((s: AbortSignal) => getAccount(accountId, s), [accountId]), { queryKey: `account:${accountId}`, intervalMs: 0 })
  const performance = usePolling(useCallback((s: AbortSignal) => getPerformance(accountId, range, s), [accountId, range]), {
    queryKey: `performance:${accountId}:${range}`, intervalMs: 0,
  })
  const refreshPerformance = useRef(performance.refresh)
  useEffect(() => { refreshPerformance.current = performance.refresh }, [performance.refresh])
  const activity = usePolling(useCallback((s: AbortSignal) => getAccountActivity(accountId, { limit: 500 }, s), [accountId]), { queryKey: `account:${accountId}:activity:500`, intervalMs: 0 })
  const bindings = usePolling(useCallback((s: AbortSignal) => getPortfolioRecords(accountId, s), [accountId]), { queryKey: `account:${accountId}:portfolio-records`, intervalMs: 0 })
  const settings = saved ?? account.data ?? performance.data?.settings
  const mode = draft?.mode ?? settings?.backtest_weight_type ?? 'ts'
  const fee = draft?.fee ?? String((settings?.backtest_fee_rate ?? 0) * 10000)
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
      await account.refresh()
      if (mounted.current) await refreshPerformance.current()
    } catch (error) {
      if (mounted.current) setSaveError(error instanceof Error ? error : new Error(String(error)))
    } finally {
      saveLock.current = false
      if (mounted.current) setSaving(false)
    }
  }

  const data = performance.data
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
      <AccountPageTitle accountId={accountId} page="实盘绩效" name={account.data?.name} channel={account.data?.trade_channel} market={account.data?.market} />
      <Segmented size="sm" value={range} options={RANGES} onChange={value => withViewTransition(() => { setHover(null); setRange(value) })} />
    </div>
    <div className="border-y border-line py-4">
      <div className="flex flex-wrap items-end gap-4">
        <fieldset disabled={saving || !settings} className="flex flex-wrap items-end gap-4 disabled:opacity-60">
          <div><div className="mb-2 text-xs text-ink-3">回测模式</div><Segmented size="sm" value={mode} options={WEIGHT_MODES} onChange={value => setDraft({ mode: value, fee })} /></div>
          <label className="block text-xs text-ink-3">单边费率（BP）<input aria-label="单边费率（BP）" type="number" min="0" max="9999.99" step="any" value={fee}
            onChange={event => setDraft({ mode, fee: event.target.value })} className="num mt-2 block h-8 w-32 rounded border border-line bg-surface px-2 text-sm text-ink-1" /></label>
        </fieldset>
        <button type="button" disabled={!dirty || saving || !settings} onClick={() => void save()} className="flex h-8 items-center gap-2 rounded border border-line px-3 text-sm disabled:opacity-40"><Save size={14} />{saving ? '保存并计算中' : '保存并计算'}</button>
        <button type="button" aria-label="重新计算" title="重新计算" disabled={saving || performance.loading || performance.refreshing} onClick={() => { setHover(null); void performance.refresh() }} className="flex h-8 w-8 items-center justify-center rounded border border-line disabled:opacity-40"><RefreshCw size={14} /></button>
      </div>
      {!parsed && <p role="alert" className="mt-2 text-xs text-warn">费率须大于等于 0 且小于 10000 BP</p>}
      {draft && dirty && <p className="mt-2 text-xs text-ink-3">参数尚未保存</p>}
      <ErrorNotice title="参数保存失败" error={saveError} />
      <ErrorNotice title="账户设置读取失败" error={account.error} onRetry={account.refresh} />
    </div>
    <ErrorNotice title={saved ? '参数已保存，收益计算失败' : '收益计算失败'} error={performance.error} variant={data ? 'stale' : 'section'} onRetry={performance.refresh} />
    {performance.loading && <div className="flex h-[380px] items-center justify-center text-sm text-ink-3">正在计算收益</div>}
    {data && <div className="py-5" aria-busy={performance.refreshing}>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="text-xs text-ink-3">{data.settings.backtest_weight_type === 'ts' ? '时序' : '截面'} · 单边费率 {Number((data.settings.backtest_fee_rate * 10000).toFixed(8))} BP · 未调整出入金{performance.refreshing ? ' · 计算中' : ''}</div>
        <Segmented size="sm" value={view} options={VIEWS} onChange={value => withViewTransition(() => { setHover(null); setView(value) })} />
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {[['账户收益', accountReturn, '%', 'text-accent'], ['组合回测收益', portfolioReturn, '%', 'text-ink-2'], ['收益差额', difference, ' 个百分点', 'text-ink-1']].map(([label, value, unit, color]) =>
          <div key={String(label)} className={label === '收益差额' ? 'col-span-2 sm:col-span-1' : ''}><div className={`text-xs ${color}`}>{label}</div><div className="num mt-1 text-2xl font-semibold">{returnText(value as number | null | undefined, String(unit))}</div></div>)}
      </div>
      <div className="mt-3 h-5 text-xs text-ink-3">{active?.date.replace('T', ' ') ?? '暂无收益数据'}</div>
      <PerformanceChart data={data} daily={daily} hoverIndex={hover} onHover={setHover} />
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-3">
        <span>基准 {data.baseline?.replace('T', ' ') ?? '—'}</span><span>截止 {data.end?.replace('T', ' ') ?? '—'}</span><span>有效回测记录 {data.used_record_count} / 历史记录 {data.record_count}</span>
      </div>
      {data.gap && <p role="status" className="mt-3 break-words text-sm text-warn">组合收益自 {data.gap.time.replace('T', ' ')} 中断：{data.gap.reason}{data.gap.symbols.length ? `（${data.gap.symbols.join('、')}）` : ''}</p>}
      {data.invalid_asset_count > 0 && <p className="mt-2 text-xs text-warn">{data.invalid_asset_count} 条账户资产快照不可用</p>}
      {data.bindings.length > 0 && <div className="mt-3 flex flex-wrap gap-3 text-xs text-ink-3">{data.bindings.map((b, i) => <span key={i}>{b.time.replace('T', ' ')} · {b.portfolio_id == null ? '解绑' : `组合 #${b.portfolio_id}`}</span>)}</div>}
    </div>}
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
