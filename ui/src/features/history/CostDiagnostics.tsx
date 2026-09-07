import { memo, useEffect, useState } from 'react'
import { ChevronDown, ChevronLeft, ChevronRight, ExternalLink, X } from 'lucide-react'
import { Link } from '@/components/ui/nav'
import { Segmented } from '@/components/ui/Segmented'
import { getExecutionArtifacts } from '@/lib/api/executions'
import { buildExecutionDetail } from '@/features/account/executionDetail'
import type { ExecutionArtifact } from '@/types/api'
import { amount, coverageText, feeText, quantityText, shanghaiLabel, shanghaiTime, summarizeCosts, type CostExecution, type CostSummary, type CostTrade } from './costs'
import { selectedExecutions, selectionLabel, type ChartSelection } from '@/features/history/chartModel'
import { withViewTransition } from '@/lib/viewTransition'

function SummaryCells({ summary }: { summary: CostSummary }) {
  return <><td>{amount(summary.value)}{!summary.amountComplete && <small className="block text-ink-3">已知成交额</small>}</td>
    <td className={summary.cost == null || summary.cost === 0 ? '' : summary.cost > 0 ? 'text-warn' : 'text-accent'}>{amount(summary.cost)}<small className="block text-ink-3">{summary.covered < summary.count ? '已知成本 · ' : ''}{coverageText(summary)}</small></td>
    <td>{feeText(summary)}<small className="block text-ink-3">{summary.feeCovered}/{summary.count} 笔收费已知</small></td></>
}

function SymbolTable({ trades, names = [...new Set(trades.map(t => t.symbol))], detail = false }: { trades: CostTrade[]; names?: string[]; detail?: boolean }) {
  return <table className="w-full whitespace-nowrap text-left text-xs [&_td]:px-3 [&_td]:py-2 [&_th]:px-3 [&_th]:py-2"><thead className="text-ink-3"><tr><th>品种</th><th>买 / 卖数量</th>{detail && <><th>买一卖一均价</th><th>成交均价</th></>}<th>滑点损耗 BP</th><th>成交额</th><th>滑点成本</th><th>手续费</th></tr></thead>
    <tbody>{names.map(symbol => {
      const group = trades.filter(t => t.symbol === symbol), summary = summarizeCosts(group)
      const priced = group.filter(t => t.price != null && t.quantity != null)
      const volume = priced.reduce((sum, t) => sum + t.quantity!, 0)
      const refs = [...new Set(group.map(t => `${amount(t.reference)}${t.referenceSource === 'last' ? ' (最新价)' : ''}`))]
      return <tr key={symbol} className="border-t border-line"><td>{symbol}</td><td>{quantityText(group.filter(t => t.side === 'buy').reduce((sum, t) => sum + (t.quantity ?? 0), 0))} / {quantityText(group.filter(t => t.side === 'sell').reduce((sum, t) => sum + (t.quantity ?? 0), 0))}{group.some(t => t.side === 'none' || t.quantity == null) && <small className="block text-ink-3">仅已知数量</small>}</td>{detail && <><td>{refs.join(' · ')}</td><td>{amount(volume ? priced.reduce((sum, t) => sum + t.price! * t.quantity!, 0) / volume : null)}</td></>}<td>{amount(summary.lossBp)}</td><SummaryCells summary={summary} /></tr>
    })}</tbody></table>
}

function ExecutionRow({ execution, accountId, cache }: { execution: CostExecution; accountId: number; cache: Map<string, ExecutionArtifact[]> }) {
  const [open, setOpen] = useState(false)
  const [artifacts, setArtifacts] = useState<ExecutionArtifact[] | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const record = execution.record
  const load = async () => {
    if (!record.execution_id || busy) return
    const cached = cache.get(record.execution_id)
    if (cached) { setArtifacts(cached); return }
    setBusy(true); setError('')
    try {
      const response = await getExecutionArtifacts(record.execution_id)
      cache.set(record.execution_id, response.data); setArtifacts(response.data)
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }
  const symbols = artifacts ? buildExecutionDetail([], artifacts).symbols : []
  const status = record.raw_result.task_status === 'TERMINATED' ? '已终止' : execution.noop ? '成功 · 空跑' : record.raw_result.status === 'PARTIAL' ? '部分执行' : record.is_success === 1 ? '成功' : '失败'
  return <><tr className="border-t border-line"><td><button className="flex min-h-9 items-center gap-2 text-left" aria-expanded={open} onClick={() => { setOpen(!open); if (!open) void load() }}><ChevronDown size={14} className={open ? 'rotate-180' : ''} />{shanghaiLabel(record.created_at)}</button></td><td>{new Set(execution.trades.filter(t => t.quantity != null).map(t => t.symbol)).size}</td><SummaryCells summary={execution.summary} /><td className={record.is_success === 1 ? '' : 'text-warn'}>{status}</td></tr>
    <tr><td colSpan={6} className="!p-0"><div inert={!open} className={`grid transition-[grid-template-rows] duration-200 ${open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}><div className="min-h-0 overflow-hidden"><div className="border-l-2 border-accent px-3 py-2">
      {record.execution_id && <Link to={`/accounts/${accountId}/executions/${record.execution_id}`} className="inline-flex min-h-9 items-center gap-1 text-accent">执行详情 <ExternalLink size={14} /></Link>}
      {!record.execution_id && <p className="py-2 text-xs text-ink-3">历史记录无执行附件</p>}
      {busy && <p role="status">附件读取中</p>}{error && <button className="min-h-9 text-warn" onClick={() => void load()}>附件读取失败，重试：{error}</button>}
      {artifacts && !symbols.length && <p className="text-ink-3">无持仓对账附件</p>}
      {symbols.length > 0 && <p className="py-1 text-xs text-ink-3">执行前 → 目标 → 执行后</p>}
      {symbols.map(s => <div key={s.symbol} className="py-1 text-xs">{s.symbol} · {quantityText(s.before)} → {quantityText(s.target)} → {quantityText(s.after)}</div>)}
      <SymbolTable trades={execution.trades} detail />
    </div></div></div></td></tr></>
}

export const CostDiagnostics = memo(function CostDiagnostics({ executions, selection, onClear, accountId }: { executions: CostExecution[]; selection: ChartSelection; onClear: () => void; accountId: number }) {
  const [mode, setMode] = useState<'execution' | 'symbol'>('execution')
  const [sort, setSort] = useState<'time' | 'cost'>('time')
  const [page, setPage] = useState(0)
  const [cache] = useState(() => new Map<string, ExecutionArtifact[]>())
  useEffect(() => setPage(0), [selection])
  const filtered = [...selectedExecutions(executions, selection)].sort((a, b) => sort === 'cost' ? (b.summary.cost ?? -Infinity) - (a.summary.cost ?? -Infinity) : shanghaiTime(b.record.created_at) - shanghaiTime(a.record.created_at))
  const trades = filtered.flatMap(e => e.trades)
  const names = [...new Set(trades.map(t => t.symbol))].sort((a, b) => sort === 'cost'
    ? (summarizeCosts(trades.filter(t => t.symbol === b)).cost ?? -Infinity) - (summarizeCosts(trades.filter(t => t.symbol === a)).cost ?? -Infinity) : a.localeCompare(b))
  const count = mode === 'execution' ? filtered.length : names.length
  const pages = Math.max(1, Math.ceil(count / 20)), current = Math.min(page, pages - 1)
  const summary = summarizeCosts(trades)
  return <div data-testid="cost-diagnostics" className="border-t border-line py-4">
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><h2 className="text-sm font-semibold">执行成本诊断</h2><div className="flex flex-wrap items-center gap-2">
      {selection && <button aria-label="清除日期筛选" className="flex min-h-9 min-w-0 items-center gap-2 text-left text-xs text-accent" onClick={onClear}><span className="break-words">{selectionLabel(selection)}</span><X size={14} className="shrink-0" /></button>}
      <Segmented size="sm" className="[&_button]:min-h-9" value={mode} options={[{ value: 'execution', label: '按执行' }, { value: 'symbol', label: '按品种' }]} onChange={value => withViewTransition(() => { setMode(value); setPage(0) })} />
      <select aria-label="排序" className="h-9 border border-line bg-transparent px-2 text-xs" value={sort} onChange={e => { setSort(e.target.value as 'time' | 'cost'); setPage(0) }}><option value="time">{mode === 'execution' ? '时间降序' : '品种名称'}</option><option value="cost">成本降序</option></select>
    </div></div>
    <div data-testid="cost-diagnostics-summary" className="mb-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-ink-2"><span>成功 {filtered.filter(e => e.record.is_success === 1).length} 次，其中空跑 {filtered.filter(e => e.noop).length} 次</span><span>{summary.covered < summary.count ? '已知滑点成本' : '滑点成本'} {amount(summary.cost)}</span><span>手续费 {feeText(summary)}</span><span>{coverageText(summary)}</span>{trades.some(t => t.timeEstimated) && <span className="text-warn">{trades.filter(t => t.timeEstimated).length} 笔使用执行时间</span>}</div>
    <div className="overflow-x-auto">
      {mode === 'symbol' ? <SymbolTable names={names.slice(current * 20, current * 20 + 20)} trades={trades} /> : <table className="w-full whitespace-nowrap text-left text-xs [&_td]:px-3 [&_td]:py-2 [&_th]:px-3 [&_th]:py-2"><thead className="text-ink-3"><tr><th>执行时间</th><th>成交品种</th><th>成交额</th><th>滑点成本</th><th>手续费</th><th>状态</th></tr></thead><tbody>{filtered.slice(current * 20, current * 20 + 20).map(e => <ExecutionRow key={e.key} execution={e} accountId={accountId} cache={cache} />)}</tbody></table>}
    </div>
    {!count && <p className="py-4 text-sm text-ink-3">本区间无执行成交</p>}
    <div className="mt-2 flex items-center justify-end gap-3 text-xs text-ink-3"><span>{count} 项 · {current + 1} / {pages}</span><button aria-label="上一页" title="上一页" className="flex h-9 w-9 items-center justify-center disabled:opacity-30" disabled={current === 0} onClick={() => setPage(current - 1)}><ChevronLeft size={16} /></button><button aria-label="下一页" title="下一页" className="flex h-9 w-9 items-center justify-center disabled:opacity-30" disabled={current + 1 === pages} onClick={() => setPage(current + 1)}><ChevronRight size={16} /></button></div>
  </div>
})
