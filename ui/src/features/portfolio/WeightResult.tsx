import { Check } from 'lucide-react'
import { WeightBars } from '@/components/viz/WeightBars'

/** 试跑通过的返回权重清单；结果带 / panel 已提供分层，内容不套卡片壳。 */
export function WeightResult({ target }: { target: Record<string, number> }) {
  const entries = Object.entries(target).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
  const total = entries.reduce((sum, [, weight]) => sum + weight, 0)
  return (
    <div>
      <div className="mb-2.5 flex items-center justify-between text-[14px]">
        <span className="flex items-center gap-1.5 font-[550] text-accent"><Check size={14} /> 返回权重</span>
        <span className="text-ink-3">合计 <span className="num text-ink-2">{total.toFixed(2)}</span></span>
      </div>
      {entries.length === 0 ? (
        <p className="text-[14px] text-ink-3">返回空仓 {'{}'}</p>
      ) : (
        <WeightBars weights={entries} format="raw" />
      )}
    </div>
  )
}
