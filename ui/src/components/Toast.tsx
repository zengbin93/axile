import { useToastStore } from '@/stores/ui'

/** 全局轻提示条，钉在视口顶部居中。由 useToastStore 驱动。 */
export function Toast() {
  const message = useToastStore((s) => s.message)
  return (
    <div
      className={`fixed top-7 left-1/2 z-40 max-w-[90vw] -translate-x-1/2 rounded-[10px] bg-ink-1 px-4 py-2.5 text-[13px] text-surface shadow-[0_8px_24px_rgba(0,0,0,0.18)] transition-all duration-200 ${
        message
          ? 'translate-y-0 opacity-100'
          : 'pointer-events-none -translate-y-3 opacity-0'
      }`}
      role="status"
    >
      {message}
    </div>
  )
}
