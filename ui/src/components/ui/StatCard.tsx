import { Card } from '@/components/ui/Card'

/** 概览统计卡：标签 + 大数字（可选单位/着色）+ 副行（可琥珀、可点）。 */
export function StatCard({
  k,
  v,
  vUnit,
  vClass = '',
  sub,
  subWarn,
  onSub,
}: {
  k: string
  v: string
  vUnit?: string
  vClass?: string
  sub: string
  subWarn?: boolean
  onSub?: () => void
}) {
  const subCls = `mt-0.5 text-xs ${subWarn ? 'text-warn' : 'text-ink-3'}`
  return (
    <Card className="px-4 py-4">
      <div className="text-xs text-ink-3">{k}</div>
      <div className={`num mt-0.5 text-[21px] font-[640] ${vClass}`}>
        {v}
        {vUnit && <span className="ml-1 text-[14px] font-normal text-ink-3">{vUnit}</span>}
      </div>
      {onSub ? (
        <button className={`${subCls} cursor-pointer border-0 bg-transparent p-0 hover:underline`} onClick={onSub}>
          {sub}
        </button>
      ) : (
        <div className={subCls}>{sub}</div>
      )}
    </Card>
  )
}
