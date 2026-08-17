/**
 * 页内状态切换的 View Transition 包装（L2/L3）与 panel-fade 入场闸门。
 *
 * 第一性原理：路由切换已由 `components/ui/nav.tsx` 统一走 View Transitions，页内的
 * 状态切换（如图表「每日/累计」、区间「30/90/全部」）同属「一次连续变化」，也应走同一
 * 套原生过渡，而非硬切。浏览器不支持时直接执行更新降级；``prefers-reduced-motion``
 * 由 `theme.css` 的 ``::view-transition`` 规则兜底关闭。
 *
 * 同页 Tab 内容区优先 ``panel-fade-in``（见 theme.css），勿与 Segmented 滑块抢 root VT。
 */
import { useEffect, useRef, type MutableRefObject } from 'react'
import { flushSync } from 'react-dom'

/** 带 `startViewTransition` 能力的 document（渐进增强，避免 TS 报缺方法）。 */
type ViewTransitionDocument = Document & {
  startViewTransition?: (callback: () => void) => unknown
}

/**
 * 在 View Transition 中执行一次状态更新。

 * React 的 ``setState`` 默认异步提交，若不同步 flush，过渡回调结束时 DOM 尚未变化，
 * 新旧快照相同便动不起来；故用 ``flushSync`` 强制在回调内同步提交 DOM。

 * Parameters
 * ----------
 * update : () => void
 *     触发状态变更的回调（通常是一个或多个 ``setState``）。

 * Notes
 * -----
 * 浏览器不支持 View Transitions API 时直接同步执行 ``update``，行为与硬切一致。
 */
export function withViewTransition(update: () => void): void {
  const doc = document as ViewTransitionDocument
  if (typeof doc.startViewTransition !== 'function') {
    update()
    return
  }
  doc.startViewTransition(() => flushSync(update))
}

/**
 * 首帧不播 ``panel-fade-in``，仅在组件已挂载后的 key 重挂才允许入场。
 *
 * 对齐动效铁律「首帧就位，不入场表演」：初次渲染返回空串；effect 之后
 * ``.current === true``，配合 ``key={...} className={allow.current ? 'panel-fade-in' : ''}``
 * 在 Tab/主锚 swap 时淡入。

 * Returns
 * -------
 * MutableRefObject<boolean>
 *     渲染期可读；勿对其赋值，由 hook 在 mount 后置 true。
 */
export function usePanelFadeReady(): MutableRefObject<boolean> {
  const allow = useRef(false)
  useEffect(() => {
    allow.current = true
  }, [])
  return allow
}

/** 标准 200ms 布局过渡（目录宽/透明度）；reduce 时由 utility 关掉。 */
export const MOTION_LAYOUT =
  'duration-200 ease-[cubic-bezier(0.4,0,0.2,1)] motion-reduce:transition-none'
