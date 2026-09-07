import type { ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'
import { Select } from '@/components/ui/Select'
import { bpsCls, fmtBps } from '@/lib/format'
import { journalAmount as amount, journalTime as time, type JournalSymbol, type Quality } from '@/features/account/executionJournal'

export const EXEC_COLS = 'grid grid-cols-2 gap-x-5 gap-y-2 xl:grid-cols-[145px_minmax(0,1fr)_80px_120px_140px_60px]'
export const SYMBOL_COLS = 'grid grid-cols-2 gap-x-5 gap-y-2 xl:grid-cols-[minmax(0,1fr)_140px_160px_80px_145px_20px]'
const TRADE_COLS = 'grid grid-cols-2 gap-x-4 gap-y-2 xl:grid-cols-[145px_48px_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_110px_60px]'
const SIDES = [{ value: 'all', label: '全部方向' }, { value: 'buy', label: '买入' }, { value: 'sell', label: '卖出' }]
export interface Expansion { open: boolean; count: number; side: string }
function quantity(value: number): string { return value.toLocaleString('zh-CN', { maximumFractionDigits: 8 }) }

export function Slip({ quality }: { quality: Quality }) {
  return <span className="inline-flex flex-col items-start xl:items-end">
    <span className={`num ${quality.slippage == null ? 'text-ink-3' : bpsCls(quality.slippage)}`}>{quality.slippage == null ? '—' : fmtBps(quality.slippage)}</span>
    {quality.nTrades > 0 && (quality.coverage < 1 || !quality.amountComplete) && <span className="text-[11px] text-ink-3">{quality.amountComplete ? `覆盖 ${(quality.coverage * 100).toFixed(0)}% 成交额` : '成交额数据不完整'}</span>}
  </span>
}
export function Field({ label, children }: { label: string; children: ReactNode }) {
  return <span className="block min-w-0 break-words xl:text-right"><span className="mr-2 text-xs text-ink-3 xl:hidden">{label}</span>{children}</span>
}

export function SymbolGroup({ row, expansion, update, detailLink }: {
  row: JournalSymbol; expansion: Expansion; update: (next: Expansion) => void
  detailLink: (id: string | null) => ReactNode
}) {
  const panelId = `symbol-${encodeURIComponent(row.symbol)}`
  const trades = row.trades.filter((t) => expansion.side === 'all' || t.side === expansion.side)
  return <div className="border-b border-line">
    <button type="button" aria-expanded={expansion.open} aria-controls={panelId}
      onClick={() => update({ ...expansion, open: !expansion.open })}
      className={`${SYMBOL_COLS} w-full items-baseline px-3 py-4 text-left text-[13px] hover:bg-bg-subtle ${expansion.open ? 'bg-bg-subtle' : ''}`}>
      <span className="col-span-2 flex min-w-0 items-center justify-between gap-2 font-medium xl:col-span-1"><span className="break-all">{row.symbol}</span><ChevronDown size={15} className={`shrink-0 transition-transform duration-200 motion-reduce:transition-none xl:hidden ${expansion.open ? 'rotate-180' : ''}`} aria-hidden /></span>
      <Field label="成交额"><span className="num">{row.amountComplete ? amount(row.value) : '—'}</span></Field>
      <Field label="滑点"><Slip quality={row} /></Field>
      <Field label="成交笔数"><span className="num">{row.nTrades}</span></Field>
      <Field label="最近成交"><span className="num text-xs text-ink-3">{time(row.lastTime)}</span></Field>
      <ChevronDown size={15} className={`hidden text-ink-3 transition-transform duration-200 motion-reduce:transition-none xl:block ${expansion.open ? 'rotate-180' : ''}`} aria-hidden />
    </button>
    <div id={panelId} inert={!expansion.open} className={`grid transition-[grid-template-rows] duration-200 motion-reduce:transition-none ${expansion.open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}>
      <div className="min-h-0 overflow-hidden">
        <div className="border-t border-line bg-bg-subtle/50 px-3 pb-4 xl:px-6">
          <div className="flex flex-wrap items-center justify-between gap-2 py-3">
            <span className="text-xs text-ink-3">逐笔成交 · {trades.length} 笔</span>
            <Select ariaLabel={`${row.symbol}成交方向`} value={expansion.side} options={SIDES} onChange={(side) => update({ ...expansion, side, count: 10 })} />
          </div>
          <div className={`${TRADE_COLS} hidden border-b border-line py-2 text-xs text-ink-3 xl:grid`}><span>时间</span><span>方向</span><span className="text-right">数量</span><span className="text-right">成交价</span><span className="text-right">成交额</span><span className="text-right">滑点</span><span /></div>
          {trades.slice(0, expansion.count).map((trade) => <div key={trade.key} className={`${TRADE_COLS} items-baseline border-b border-line py-3 text-[13px]`}>
            <span className="num text-xs text-ink-3">{time(trade.time)}</span><span>{trade.side === 'buy' ? '买入' : trade.side === 'sell' ? '卖出' : '方向未知'}</span>
            <Field label="数量"><span className="num">{quantity(trade.volume)}</span></Field>
            <Field label="成交价"><span className="num">{quantity(trade.price)}</span></Field>
            <Field label="成交额"><span className="num">{trade.value == null ? '—' : amount(trade.value)}</span></Field>
            <Field label="滑点"><span className={`num ${trade.slippageBps == null ? 'text-ink-3' : bpsCls(trade.slippageBps)}`}>{trade.slippageBps == null ? '—' : fmtBps(trade.slippageBps)}</span></Field>
            <span className="text-right">{detailLink(trade.executionId)}</span>
          </div>)}
          {trades.length === 0 && <p className="py-4 text-sm text-ink-3">无匹配成交</p>}
          <div className="mt-3 flex items-center gap-4 text-xs text-ink-3"><span>已展示 {Math.min(expansion.count, trades.length)} / {trades.length} 笔</span>
            {expansion.count < trades.length && <button type="button" className="text-accent hover:underline" onClick={() => update({ ...expansion, count: expansion.count + 10 })}>加载更多</button>}
          </div>
        </div>
      </div>
    </div>
  </div>
}
