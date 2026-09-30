import { useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { PythonSaveBar } from '@/components/ui/PythonSaveBar'
import { usePythonSaveShortcut, type PythonSaveAction } from '@/components/ui/pythonSaveAction'

const DEFAULT_WIDTH = 320
const MIN_WIDTH = 260
const MAX_WIDTH = 480

function clampInspectorWidth(width: number, containerWidth = Number.POSITIVE_INFINITY) {
  return Math.min(Math.max(width, MIN_WIDTH), MAX_WIDTH, Math.max(MIN_WIDTH, containerWidth - 520))
}

/** 组合与通知共用的工作台外壳；左栏业务内容由页面填充。 */
export function PythonWorkbench({ storageKey, inspector, children, resizingPanels, saveAction, status }: {
  storageKey: string
  inspector: ReactNode
  children: ReactNode
  resizingPanels: boolean
  saveAction: PythonSaveAction
  status: ReactNode
}) {
  const container = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(() => {
    const stored = typeof window === 'undefined' ? null : window.localStorage.getItem(storageKey)
    return stored !== null && Number.isFinite(Number(stored)) && Number(stored) > 0
      ? clampInspectorWidth(Number(stored))
      : DEFAULT_WIDTH
  })
  const [resizing, setResizing] = useState(false)
  usePythonSaveShortcut(saveAction)

  const widthAt = (x: number) => {
    const bounds = container.current?.getBoundingClientRect()
    return bounds ? clampInspectorWidth(x - bounds.left, bounds.width) : width
  }
  const persist = (next: number) => {
    setWidth(next)
    window.localStorage.setItem(storageKey, String(next))
  }

  return (
    <section className="flex h-full w-full flex-col bg-canvas">
      <div
        ref={container}
        className={`relative grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[var(--python-inspector-width)_minmax(0,1fr)] ${resizing || resizingPanels ? 'select-none' : ''}`}
        style={{ '--python-inspector-width': `${width}px` } as CSSProperties}
      >
        {inspector}
        {children}
        <div
          role="separator"
          aria-label="调整运行检查器宽度"
          aria-orientation="vertical"
          aria-valuemin={MIN_WIDTH}
          aria-valuemax={MAX_WIDTH}
          aria-valuenow={Math.round(width)}
          tabIndex={0}
          title="左右拖动调整宽度 · 双击恢复默认"
          className="group absolute inset-y-0 z-20 hidden w-[7px] -translate-x-1/2 touch-none cursor-col-resize outline-none md:block"
          style={{ left: `${width}px` }}
          onDoubleClick={() => persist(DEFAULT_WIDTH)}
          onPointerDown={(event) => {
            event.preventDefault()
            event.currentTarget.setPointerCapture(event.pointerId)
            setResizing(true)
            setWidth(widthAt(event.clientX))
          }}
          onPointerMove={(event) => {
            if (event.currentTarget.hasPointerCapture(event.pointerId)) setWidth(widthAt(event.clientX))
          }}
          onPointerUp={(event) => {
            if (!event.currentTarget.hasPointerCapture(event.pointerId)) return
            event.currentTarget.releasePointerCapture(event.pointerId)
            persist(widthAt(event.clientX))
            setResizing(false)
          }}
          onPointerCancel={() => setResizing(false)}
          onKeyDown={(event) => {
            let next = width
            if (event.key === 'ArrowLeft') next -= 16
            else if (event.key === 'ArrowRight') next += 16
            else if (event.key === 'Home') next = MIN_WIDTH
            else if (event.key === 'End') next = MAX_WIDTH
            else return
            event.preventDefault()
            persist(clampInspectorWidth(next, container.current?.getBoundingClientRect().width))
          }}
        >
          <span className={`absolute inset-y-0 left-1/2 w-px transition-colors duration-130 ${resizing ? 'bg-accent' : 'bg-line group-hover:bg-accent group-focus:bg-accent'}`} />
          <span aria-hidden className={`absolute left-1/2 top-1/2 h-7 w-[3px] -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-surface transition-colors duration-130 ${resizing ? 'bg-accent' : 'bg-ink-3 group-hover:bg-accent group-focus:bg-accent'}`} />
        </div>
      </div>
      <PythonSaveBar action={saveAction} status={status} />
    </section>
  )
}
