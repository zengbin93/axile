import { memo, useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronLeft, ChevronRight, ExternalLink, X } from 'lucide-react'
import { Link } from '@/components/ui/nav'
import { Segmented } from '@/components/ui/Segmented'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { getExecutionArtifacts } from '@/lib/api/executions'
import { buildExecutionDetail } from '@/features/account/executionDetail'
import { ApiError } from '@/lib/api/client'
import { getPerformanceCosts, selectionQuery, type CostExecutionRow, type CostSymbolRow, type CostPage, type CostQuery, type PerformanceRange } from '@/lib/api/performance'
import type { ExecutionArtifact } from '@/types/api'
import { amount, coverageText, feeText, quantityText, shanghaiLabel, type CostSummary, type CostTrade } from './costs'
import { selectionLabel, type ChartSelection } from './chartModel'
import { withViewTransition } from '@/lib/viewTransition'

function SummaryCells({ summary }: { summary: CostSummary }) {
  return <><td>{amount(summary.value)}{!summary.amountComplete && <small className="block text-ink-3">已知成交额</small>}</td>
    <td className={summary.cost == null || summary.cost === 0 ? '' : summary.cost > 0 ? 'text-warn' : 'text-accent'}>{amount(summary.cost)}<small className="block text-ink-3">{summary.covered < summary.count ? '已知成本 · ' : ''}{coverageText(summary)}</small></td>
    <td>{feeText(summary)}<small className="block text-ink-3">{summary.feeCovered}/{summary.count} 笔收费已知</small></td></>
}
const tableClass = 'w-full whitespace-nowrap text-left text-xs [&_td]:px-3 [&_td]:py-2 [&_th]:px-3 [&_th]:py-2'

function Pager({ count, cursors, next, onPrevious, onNext }: { count: number; cursors: (string | undefined)[]; next: string | null; onPrevious: () => void; onNext: () => void }) {
  return <div className="mt-2 flex items-center justify-end gap-3 text-xs text-ink-3"><span>{count} 项 · 第 {cursors.length} 页</span>
    <button aria-label="上一页" title="上一页" className="flex h-9 w-9 items-center justify-center disabled:opacity-30" disabled={cursors.length === 1} onClick={onPrevious}><ChevronLeft size={16} /></button>
    <button aria-label="下一页" title="下一页" className="flex h-9 w-9 items-center justify-center disabled:opacity-30" disabled={!next} onClick={onNext}><ChevronRight size={16} /></button></div>
}

function useCostPage<T>(accountId: number, query: CostQuery, enabled: boolean, onExpired: () => Promise<void>) {
  const [response, setResponse] = useState<{ key: string; data: CostPage<T> } | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [revision, setRevision] = useState(0)
  const key = JSON.stringify(query)
  useEffect(() => {
    if (!enabled) return
    const controller = new AbortController()
    setError(null)
    void getPerformanceCosts<T>(accountId, JSON.parse(key), controller.signal).then(data => { if (!controller.signal.aborted) setResponse({ key, data }) }).catch(error => {
      if (controller.signal.aborted) return
      if (error instanceof ApiError && error.status === 410) { setError(new Error('快照已更新，正在重新读取绩效')); void onExpired() }
      else setError(error instanceof Error ? error : new Error(String(error)))
    })
    return () => controller.abort()
  }, [accountId, key, enabled, revision, onExpired])
  return { data: response?.key === key ? response.data : null, error, retry: () => setRevision(value => value + 1) }
}

function ExecutionRow({ execution, accountId, query, onExpired }: { execution: CostExecutionRow; accountId: number; query: CostQuery; onExpired: () => Promise<void> }) {
  const [open, setOpen] = useState(false)
  const [cursors, setCursors] = useState<(string | undefined)[]>([undefined])
  const fills = useCostPage<CostTrade>(accountId, { ...query, dimension: 'trade', record_id: execution.record.id, cursor: cursors.at(-1) }, open, onExpired)
  const [artifacts, setArtifacts] = useState<ExecutionArtifact[] | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [retry, setRetry] = useState(0)
  const record = execution.record
  useEffect(() => {
    if (!open || !record.execution_id || artifacts) return
    let disposed = false
    setError(null)
    void getExecutionArtifacts(record.execution_id).then(response => { if (!disposed) setArtifacts(response.data) }).catch(error => { if (!disposed) setError(error) })
    return () => { disposed = true }
  }, [open, record.execution_id, artifacts, retry])
  const symbols = artifacts ? buildExecutionDetail([], artifacts).symbols : []
  const status = record.raw_result.task_status === 'TERMINATED' ? '已终止' : execution.noop ? '成功 · 空跑' : record.raw_result.status === 'PARTIAL' ? '部分执行' : record.is_success === 1 ? '成功' : '失败'
  return <><tr className="border-t border-line"><td><button className="flex min-h-9 items-center gap-2 text-left" aria-expanded={open} onClick={() => setOpen(!open)}><ChevronDown size={14} className={open ? 'rotate-180' : ''} />{shanghaiLabel(record.created_at)}</button></td><td>{execution.symbolCount}</td><SummaryCells summary={execution.summary} /><td className={record.is_success === 1 ? '' : 'text-warn'}>{status}</td></tr>
    <tr><td colSpan={6} className="!p-0"><div inert={!open} className={`grid transition-[grid-template-rows] duration-200 motion-reduce:transition-none ${open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}><div className="min-h-0 overflow-hidden"><div className="border-l-2 border-accent px-3 py-2">
      {record.execution_id && <Link to={`/accounts/${accountId}/executions/${record.execution_id}`} className="inline-flex min-h-9 items-center gap-1 text-accent">执行详情 <ExternalLink size={14} /></Link>}
      {!record.execution_id && <p className="py-2 text-xs text-ink-3">历史记录无执行附件</p>}
      <ErrorNotice title="附件读取失败" error={error} onRetry={() => setRetry(value => value + 1)} />
      {symbols.length > 0 && <p className="py-1 text-xs text-ink-3">执行前 → 目标 → 执行后</p>}
      {symbols.map(s => <div key={s.symbol} className="py-1 text-xs">{s.symbol} · {quantityText(s.before)} → {quantityText(s.target)} → {quantityText(s.after)}</div>)}
      <ErrorNotice title="成交读取失败" error={fills.error} onRetry={fills.retry} />
      {open && !fills.data && !fills.error && <p role="status">成交读取中</p>}
      <table className={tableClass}><thead className="text-ink-3"><tr><th>成交时间</th><th>品种</th><th>方向 / 数量</th><th>参考价</th><th>成交价</th><th>滑点成本</th><th>手续费</th></tr></thead><tbody>
        {fills.data?.data.map((trade, index) => <tr key={index} className="border-t border-line"><td>{shanghaiLabel(new Date(trade.time).toISOString())}{trade.timeEstimated && <small className="block text-warn">使用执行时间</small>}</td><td>{trade.symbol}</td><td>{trade.side === 'buy' ? '买' : trade.side === 'sell' ? '卖' : '未知'} / {quantityText(trade.quantity)}</td><td>{amount(trade.reference)}{trade.referenceSource === 'last' && ' (最新价)'}</td><td>{amount(trade.price)}</td><td>{amount(trade.cost)}</td><td>{amount(trade.fee)} {trade.feeCurrency ?? ''}</td></tr>)}
      </tbody></table>
      {fills.data && <Pager count={fills.data.count} cursors={cursors} next={fills.data.next_cursor} onPrevious={() => setCursors(value => value.slice(0, -1))} onNext={() => setCursors(value => [...value, fills.data!.next_cursor!])} />}
    </div></div></div></td></tr></>
}

interface Props { snapshotId: string; range: PerformanceRange; selection: ChartSelection; onClear: () => void; accountId: number; onExpired: () => Promise<void> }
export const CostDiagnostics = memo(function CostDiagnostics(props: Props) {
  const root = useRef<HTMLDivElement>(null)
  const [visible, setVisible] = useState(false)
  useEffect(() => {
    const observer = new IntersectionObserver(entries => { if (entries.some(entry => entry.isIntersecting)) { setVisible(true); observer.disconnect() } })
    if (root.current) observer.observe(root.current)
    return () => observer.disconnect()
  }, [])
  return <div ref={root} data-testid="cost-diagnostics" className="min-h-40 border-t border-line py-4">
    {visible ? <DiagnosticsBody key={JSON.stringify(selectionQuery(props.selection))} {...props} /> : <h2 className="text-sm font-semibold">执行成本诊断</h2>}
  </div>
})

function DiagnosticsBody({ snapshotId, range, selection, onClear, accountId, onExpired }: Props) {
  const [mode, setMode] = useState<'execution' | 'symbol'>('execution')
  const [sort, setSort] = useState<'time' | 'cost'>('time')
  const [symbol, setSymbol] = useState('')
  const [cursors, setCursors] = useState<(string | undefined)[]>([undefined])
  const query: CostQuery = { snapshot_id: snapshotId, range, dimension: mode, sort, ...selectionQuery(selection), symbol: symbol || undefined, cursor: cursors.at(-1) }
  const page = useCostPage<CostExecutionRow | CostSymbolRow>(accountId, query, true, onExpired)
  const data = page.data
  const summary = data?.summary
  return <>
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><h2 className="text-sm font-semibold">执行成本诊断</h2><div className="flex flex-wrap items-center gap-2">
      {selection && <button aria-label="清除日期筛选" className="flex min-h-9 min-w-0 items-center gap-2 text-left text-xs text-accent" onClick={onClear}><span className="break-words">{selectionLabel(selection)}</span><X size={14} className="shrink-0" /></button>}
      <input aria-label="品种筛选" placeholder="品种" className="h-9 w-28 border border-line bg-transparent px-2 text-xs" value={symbol} onChange={event => { setSymbol(event.target.value); setCursors([undefined]) }} />
      <Segmented size="sm" className="[&_button]:min-h-9" value={mode} options={[{ value: 'execution', label: '按执行' }, { value: 'symbol', label: '按品种' }]} onChange={value => withViewTransition(() => { setMode(value); setCursors([undefined]) })} />
      <select aria-label="排序" className="h-9 border border-line bg-transparent px-2 text-xs" value={sort} onChange={event => { setSort(event.target.value as 'time' | 'cost'); setCursors([undefined]) }}><option value="time">{mode === 'execution' ? '时间降序' : '品种名称'}</option><option value="cost">成本降序</option></select>
    </div></div>
    <ErrorNotice title="成本读取失败" error={page.error} onRetry={page.retry} />
    {!data && !page.error && <p role="status" className="py-4 text-sm text-ink-3">成本读取中</p>}
    {summary && data && <div data-testid="cost-diagnostics-summary" className="mb-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-ink-2"><span>成功 {data.successful} 次，其中空跑 {data.noop} 次</span><span>{summary.covered < summary.count ? '已知滑点成本' : '滑点成本'} {amount(summary.cost)}</span><span>手续费 {feeText(summary)}</span><span>{coverageText(summary)}</span>{summary.estimated > 0 && <span className="text-warn">{summary.estimated} 笔使用执行时间</span>}</div>}
    <div className="overflow-x-auto"><table className={tableClass}><thead className="text-ink-3"><tr>{mode === 'execution' ? <><th>执行时间</th><th>成交品种</th></> : <><th>品种</th><th>买 / 卖数量</th><th>滑点损耗 BP</th></>}<th>成交额</th><th>滑点成本</th><th>手续费</th>{mode === 'execution' && <th>状态</th>}</tr></thead><tbody>
      {data?.data.map(row => 'record' in row ? <ExecutionRow key={`${row.key}:${JSON.stringify(query)}`} execution={row} accountId={accountId} query={query} onExpired={onExpired} /> : <tr key={row.symbol} className="border-t border-line"><td>{row.symbol}</td><td>{quantityText(row.buy)} / {quantityText(row.sell)}{row.quantityIncomplete && <small className="block text-ink-3">仅已知数量</small>}</td><td>{amount(row.summary.lossBp)}</td><SummaryCells summary={row.summary} /></tr>)}
    </tbody></table></div>
    {data?.count === 0 && <p className="py-4 text-sm text-ink-3">本区间无执行成交</p>}
    {data && <Pager count={data.count} cursors={cursors} next={data.next_cursor} onPrevious={() => setCursors(value => value.slice(0, -1))} onNext={() => setCursors(value => [...value, data.next_cursor!])} />}
  </>
}
