import { useEffect, useState } from 'react'
import type { DraftStrategy } from '@/features/portfolio/diff'
import { equalize, mergeImport, parseNames } from '@/features/portfolio/strategies'

interface ImportModalProps {
  open: boolean
  /** 当前组合内的策略行，用于去重与计数。 */
  existing: DraftStrategy[]
  onClose: () => void
  /** 并入并等权后的完整列表。 */
  onApply: (rows: DraftStrategy[]) => void
}

const PLACEHOLDER = `如：
BTC_1H_P11
ETH_4H_TREND  SOL_15M_REV
XRP_1D_MOM, DOGE_1H_BRK`

/**
 * 粘贴导入策略名弹窗.

 * 只解析、去重、计数（新增 / 已在组合），不做对错校验——组合无可查询策略池。
 * 「并入组合（等权）」后回调 `onApply`，权重由调用方等权分配。
 */
export function ImportModal({ open, existing, onClose, onApply }: ImportModalProps) {
  const [raw, setRaw] = useState('')

  useEffect(() => {
    if (open) setRaw('')
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  const names = parseNames(raw)
  const preview = mergeImport(existing, names)
  const canApply = preview.added > 0

  const apply = () => {
    onApply(equalize(preview.merged))
    onClose()
  }

  return (
    <>
      <div
        className={`fixed inset-0 z-[35] bg-scrim transition-opacity duration-150 ${
          open ? 'opacity-100' : 'pointer-events-none opacity-0'
        }`}
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        className={`fixed left-1/2 top-1/2 z-[36] flex max-h-[86vh] w-[560px] max-w-[92vw] -translate-x-1/2 flex-col rounded-[18px] bg-surface shadow-[0_24px_60px_rgba(0,0,0,0.24)] transition-all duration-150 ${
          open ? '-translate-y-1/2 opacity-100' : 'pointer-events-none -translate-y-[46%] opacity-0'
        }`}
      >
        {open && (
          <>
            <div className="flex items-start justify-between px-[22px] pt-5 pb-3">
              <div>
                <div className="text-[17px] font-[640]">粘贴导入策略名</div>
                <div className="mt-1 text-[13px] text-ink-2">
                  策略名一股脑贴进来，空格 / 换行 / 逗号 / 顿号任意隔开。只收名字，导入后默认等权。
                </div>
              </div>
              <button
                className="cursor-pointer text-[20px] leading-none text-ink-3 hover:text-ink-1"
                onClick={onClose}
                aria-label="关闭"
              >
                ✕
              </button>
            </div>
            <div className="px-[22px]">
              <textarea
                className="min-h-[200px] w-full resize-y rounded-[12px] border border-ink-3/30 bg-surface p-3.5 font-mono text-[13px] leading-relaxed outline-none focus:border-ink-2"
                spellCheck={false}
                autoFocus
                placeholder={PLACEHOLDER}
                value={raw}
                onChange={(e) => setRaw(e.target.value)}
              />
              <div className="mt-2 min-h-[20px] text-[13px] text-ink-2">
                {names.length > 0 && (
                  <>
                    共 <b>{names.length}</b> 个 · 新增 <b className="text-ok">{preview.added}</b>
                    {preview.dup > 0 && (
                      <> · 已在组合 <b className="text-ink-3">{preview.dup}</b></>
                    )}
                  </>
                )}
              </div>
            </div>
            <div className="mt-1 flex justify-end gap-2.5 border-t border-line px-5 py-3.5">
              <button
                className="cursor-pointer rounded-[9px] border border-line bg-surface px-4 py-2 text-sm text-ink-2"
                onClick={onClose}
              >
                取消
              </button>
              <button
                className="cursor-pointer rounded-[9px] border border-ink-1 bg-ink-1 px-[18px] py-2 text-sm font-[550] text-surface disabled:opacity-45"
                onClick={apply}
                disabled={!canApply}
              >
                并入组合（等权）
              </button>
            </div>
          </>
        )}
      </div>
    </>
  )
}
