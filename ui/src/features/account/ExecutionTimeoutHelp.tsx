import { Tooltip } from '@/components/ui/Tooltip'

/** 账户执行超时的通用说明入口。 */
export function ExecutionTimeoutHelp() {
  return (
    <Tooltip
      arrow
      content={
        <div>
          <div className="font-medium text-ink-1">执行超时</div>
          <div className="mt-1 text-ink-2">
            一次执行跑满后中断，不再开新单；挂单留待下次执行前清理。
          </div>
          <div className="mt-1 text-ink-3">
            无法中断渠道内部卡死，与算法「最长等待」分属不同层级。
          </div>
        </div>
      }
    >
      <button
        type="button"
        aria-label="查看执行超时说明"
        className="grid h-7 w-7 cursor-help place-items-center rounded-md border-0 bg-transparent text-[16px] text-ink-3 transition-colors hover:bg-fill hover:text-ink-2"
      >
        ⓘ
      </button>
    </Tooltip>
  )
}
