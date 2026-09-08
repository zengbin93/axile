import { useState } from 'react'
import { ExternalLink, X } from 'lucide-react'
import { Link } from '@/components/ui/nav'
import { amount, quantityText, shanghaiLabel } from '@/features/history/costs'
import { executionState } from '@/features/history/executionSelection'
import { quantityUnit } from '@/features/history/executionEvidenceModel'
import { holdingAt, positionDirection } from '@/features/history/tradeAnnotations'
import { xPosition, type ChartScene } from '@/components/viz/performanceCanvas'
import type { ChartSelection } from '@/features/history/chartModel'
import { timeLabel } from '@/features/history/chartModel'
import type { CostExecutionRow, TransactionPreview } from '@/lib/api/performance'
import type { ChannelCapability } from '@/types/api'

interface Props {
  scene: ChartScene; rows: CostExecutionRow[]; accountId: number; currency: string; units?: ChannelCapability['units']
  cursor: { time: number; x: number; y: number } | null
  selection: ChartSelection; onSelect: (value: ChartSelection) => void
  onInspect: (cursor: { time: number; x: number; y: number } | null) => void
}

function PositionList({ row, units, currency, expanded }: { row: CostExecutionRow | null; units?: ChannelCapability['units']; currency: string; expanded: boolean }) {
  const positions = row?.positions
  return <div className="mt-2 border-t border-line pt-2">
    <div className="mb-1 text-ink-3">{row ? `执行后持仓 · ${shanghaiLabel(row.record.created_at)}` : '持仓快照'}</div>
    {positions == null ? <p>持仓状态未知</p> : positions.length === 0 ? <p>空仓</p> : <>
      {positions.slice(0, expanded ? undefined : 4).map((p, i) => <div key={`${p.symbol}:${i}`} className="flex justify-between gap-3 py-0.5"><span>{p.symbol} · {positionDirection(p.direction, p.quantity)}</span><span>{quantityText(Math.abs(p.quantity))} {quantityUnit(units, p.symbol, currency)}</span></div>)}
      {!expanded && positions.length > 4 && <p className="mt-1 text-ink-3">另 {positions.length - 4} 项持仓，点击固定后查看</p>}
    </>}
  </div>
}

function Transaction({ trade, row, currency, units, expanded }: { trade: TransactionPreview; row: CostExecutionRow; currency: string; units?: ChannelCapability['units']; expanded: boolean }) {
  const qty = (value: number | null) => `${quantityText(value)} ${quantityUnit(units, trade.symbol, currency)}`
  const loss = trade.summary.lossBp
  const side = trade.side === 'buy' ? '买入' : trade.side === 'sell' ? '卖出' : '方向未知'
  const after = row.positions?.filter(p => p.symbol === trade.symbol)
  const afterText = after == null ? '未知' : after.length === 0 ? qty(0) : after.map(p => `${positionDirection(p.direction, p.quantity)} ${qty(Math.abs(p.quantity))}`).join(' / ')
  return <div className="border-t border-line py-2">
    <div className="flex flex-wrap justify-between gap-x-3 gap-y-1 font-medium"><span>{trade.symbol}</span><span>{side} {qty(trade.quantity)}</span></div>
    <div className="mt-1 flex flex-wrap justify-between gap-x-3 text-ink-2"><span>均价 {amount(trade.price)}</span><span className={loss == null || loss === 0 ? 'text-ink-3' : loss > 0 ? 'text-warn' : 'text-accent'}>{loss == null ? '滑点未知' : `${loss > 0 ? '不利' : loss < 0 ? '有利' : '持平'} ${amount(Math.abs(loss))} BP`} · {trade.summary.covered < trade.summary.count ? '已知成本 ' : '成本 '}{amount(trade.summary.cost)} {currency}</span></div>
    {expanded && <div className="mt-1 space-y-1 text-ink-3"><p>原持仓 {qty(trade.before)} → 执行后 {afterText}</p><p>目标持仓 {qty(trade.target)} · {trade.referenceSource === 'last' ? '参考最新价' : '参考中间价'} {amount(trade.reference)}</p><p>{timeLabel(trade.time)}{trade.endTime !== trade.time ? ` → ${timeLabel(trade.endTime).slice(11)}` : ''}{trade.timeEstimated ? '（成交时间缺失，使用执行时间）' : ''}</p>{trade.summary.covered < trade.summary.count && <p>滑点仅覆盖 {trade.summary.covered}/{trade.summary.count} 笔成交</p>}</div>}
  </div>
}

export function ChartTradingOverlay({ scene, rows, accountId, currency, units, cursor, selection, onSelect, onInspect }: Props) {
  const [showPositions, setShowPositions] = useState(false)
  const pinned = selection?.kind === 'execution' ? rows.find(row => row.record.id === selection.recordId) ?? null : null
  const row = pinned ?? (cursor ? holdingAt(rows, cursor.time) : null)
  const visible = !!pinned || !!cursor
  const anchor = pinned && selection?.kind === 'execution' ? { x: xPosition(selection.time, scene.width, scene.viewport), y: 70 } : cursor ?? { x: 20, y: 20 }
  const width = Math.min(370, scene.width - 16)
  const left = Math.max(8, Math.min(scene.width - width - 8, anchor.x > scene.width / 2 ? anchor.x - width - 20 : anchor.x + 20))
  const preview = pinned?.transactions ?? []
  const close = () => { onInspect(null); onSelect(null) }
  return <div className="pointer-events-none absolute inset-0" data-testid="chart-trading-overlay">
    {visible && <div data-testid="chart-trade-card" role={pinned ? 'dialog' : 'tooltip'} aria-label={pinned ? '成交与持仓详情' : '成交与持仓预览'} className={`${pinned ? 'pointer-events-auto' : 'pointer-events-none'} absolute z-20 overflow-y-auto overscroll-contain rounded-md border border-line bg-surface px-3 py-2.5 text-xs text-ink-1 shadow-md`} style={{ left, top: Math.max(8, Math.min(90, anchor.y - 55)), width, maxHeight: pinned ? 400 : 340 }} onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); close() } }}>
      <div className="flex items-start justify-between gap-2"><div className="font-medium">{pinned ? `${shanghaiLabel(pinned.record.created_at)} · ${executionState(pinned)}` : timeLabel(cursor!.time)}</div>
        {pinned && <button type="button" aria-label="关闭成交浮层" className="-mr-1 -mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded hover:bg-fill" onClick={close}><X size={15} /></button>}
      </div>
      {row?.reason && <p className="mt-2 text-warn">{row.reason}</p>}
      {pinned?.attempts?.map(attempt => <div key={attempt.symbol} className="mt-2 border-t border-line pt-2"><div>{attempt.symbol} · 计划净交易 {quantityText(attempt.planned)} / 实际净成交 {quantityText(attempt.filled)} {quantityUnit(units, attempt.symbol, currency)}</div>{attempt.reason && <p className="mt-1 text-warn">{attempt.reason}</p>}</div>)}
      {pinned && preview.map((trade, i) => <Transaction key={`${trade.symbol}:${trade.side}:${i}`} trade={trade} row={pinned} currency={currency} units={units} expanded />)}
      {pinned && preview.length === 0 && <p className="mt-2 text-ink-3">{pinned.noop ? '本次无需交易' : '无可用成交明细'}</p>}
      {!pinned && row?.noop && <p className="mt-2 text-ink-3">{executionState(row)}</p>}
      <div inert={!!pinned && !showPositions} className={`grid transition-[grid-template-rows] duration-200 motion-reduce:transition-none ${!pinned || showPositions ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}><div className="min-h-0 overflow-hidden"><PositionList row={row} units={units} currency={currency} expanded={!!pinned} /></div></div>
      {pinned && <div className="sticky -bottom-2.5 -mx-3 mt-2 flex flex-wrap items-center gap-x-3 border-t border-line bg-surface px-3 pt-1"><button className="min-h-9 text-accent" onClick={() => setShowPositions(value => !value)}>{showPositions ? '收起持仓' : '全部持仓'}</button>{pinned.record.execution_id && <Link to={`/accounts/${accountId}/executions/${pinned.record.execution_id}`} state={{ performanceReturn: `/accounts/${accountId}/history` }} className="inline-flex min-h-9 items-center gap-1 text-accent">执行详情 <ExternalLink size={12} /></Link>}</div>}
      {!pinned && <p className="mt-2 text-[10px] text-ink-3">最近执行后快照 · 点击曲线查看成交</p>}
    </div>}
  </div>
}
