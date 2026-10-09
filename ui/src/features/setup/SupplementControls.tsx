import { OptionStepper } from '@/components/ui/OptionStepper'
import { MOTION_LAYOUT } from '@/lib/viewTransition'

interface SupplementControlsProps {
  supN: number
  supM: number
  onN: (count: number) => void
  onM: (minutes: number) => void
}

/** 编辑页、向导与快捷弹层共用补发配置；关闭时保留间隔草稿。 */
export function SupplementControls({ supN, supM, onN, onM }: SupplementControlsProps) {
  const enabled = supN > 0
  return (
    <div>
      <div className="flex items-center gap-3 text-sm">
        <span className="w-8 shrink-0 text-ink-3">补发</span>
        <OptionStepper ariaLabel="补发次数" value={supN} options={[0, 1, 2, 3, 4]} onChange={onN}
          formatValue={(count) => count === 0 ? '不补' : `${count} 次`} />
      </div>
      <div inert={!enabled} aria-hidden={!enabled} className={`grid transition-[grid-template-rows] ${MOTION_LAYOUT} ${enabled ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}>
        <div className="min-h-0 overflow-hidden">
          <div className="mt-2 flex items-center gap-3 text-sm">
            <span className="w-8 shrink-0 text-ink-3">间隔</span>
            <OptionStepper ariaLabel="补发间隔分钟" value={supM} options={[1, 2, 3, 5]} onChange={onM}
              formatValue={(minutes) => `${minutes} 分`} disabled={!enabled} />
          </div>
        </div>
      </div>
    </div>
  )
}
