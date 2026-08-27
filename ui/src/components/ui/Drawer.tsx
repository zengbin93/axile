import { useEffect } from 'react'
import type { ReactNode } from 'react'

/** 右侧滑出抽屉 + 半透明遮罩。用于执行详情 / 持仓明细。 */
export function Drawer({
  open,
  onClose,
  children,
}: {
  open: boolean
  onClose: () => void
  children: ReactNode
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  return (
    <>
      <div
        className={`fixed inset-0 z-30 bg-scrim transition-opacity duration-200 ${
          open ? 'opacity-100' : 'pointer-events-none opacity-0'
        }`}
        onClick={onClose}
      />
      <aside
        className={`fixed top-0 right-0 z-30 flex h-full w-[460px] max-w-[92vw] flex-col bg-surface shadow-[-8px_0_30px_rgba(0,0,0,0.12)] transition-transform duration-200 ${
          open ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        {open && children}
      </aside>
    </>
  )
}

/** 抽屉头部容器。 */
export function DrawerHead({ children, onClose }: { children: ReactNode; onClose: () => void }) {
  return (
    <div className="border-b border-line p-6">
      <button
        className="float-right cursor-pointer text-[23px] leading-none text-ink-3 hover:text-ink-1"
        onClick={onClose}
        aria-label="关闭"
      >
        ✕
      </button>
      {children}
    </div>
  )
}

/** 抽屉可滚动主体。 */
export function DrawerBody({ children }: { children: ReactNode }) {
  return <div className="flex-1 overflow-y-auto p-6">{children}</div>
}
