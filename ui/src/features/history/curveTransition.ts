import { curvePath, type CurvePoint } from '@/components/viz/sparklineGeometry'
import { curveDurationMs, fitCurve, interpolateCurve, translateCurve } from '@/features/history/curveTransitionGeometry'
import { openFullPerformance } from '@/features/dashboard/performance'
import type { PerformancePoint } from '@/types/api'

/** 路由外的临时视觉状态，不进入绩效缓存，也不成为收益/指标的数据来源。 */
export interface CurveEndpoint {
  accountId: number
  kind: 'sparkline' | 'chart'
  identity: string
  element: SVGSVGElement | HTMLElement
  points: PerformancePoint[]
  snapshotId: string | null
  coordinates: (points: PerformancePoint[]) => CurvePoint[]
  canReturn?: boolean
  preview?: boolean
}
interface Visit { sourceKey: string; sourcePath: string; identity: string; accountId: number; scroll: number }
interface Flight {
  direction: 'open' | 'close'
  visit: Visit
  points: PerformancePoint[]
  from: CurvePoint[]
  snapshotId: string | null
  svg: SVGSVGElement
  path: SVGPathElement
  width: number
  opacity: number
  frame: number
  timer: ReturnType<typeof setTimeout>
  restore: (() => void)[]
  concealed: Set<Element>
  target?: CurveEndpoint
  started: boolean
  destination?: string
  committed?: boolean
}

const endpoints = new Map<string, CurveEndpoint>()
const visits = new Map<string, Visit>()
let flight: Flight | null = null
let currentKey = 'default'
let currentPath = '/'
const workspace = () => document.querySelector<HTMLElement>('main.app-workspace')
const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

function visible(element: Element) {
  const rect = element.getBoundingClientRect()
  const bounds = workspace()?.getBoundingClientRect()
  return rect.width > 0 && rect.height > 0 && rect.bottom > Math.max(0, bounds?.top ?? 0)
    && rect.top < Math.min(window.innerHeight, bounds?.bottom ?? window.innerHeight)
    && rect.right > 0 && rect.left < window.innerWidth
}

function screenCoordinates(endpoint: CurveEndpoint, points = endpoint.points) {
  const rect = endpoint.element.getBoundingClientRect()
  return translateCurve(endpoint.coordinates(points), rect.left, rect.top)
}

function conceal(endpoint: CurveEndpoint, active: Flight) {
  const element = endpoint.element
  if (active.concealed.has(element)) return
  active.concealed.add(element)
  const opacity = element.style.opacity
  const inert = element instanceof HTMLElement ? element.inert : false
  element.style.opacity = '0'
  if (element instanceof HTMLElement) element.inert = true
  active.restore.push(() => {
    element.style.opacity = opacity
    if (element instanceof HTMLElement) element.inert = inert
  })
}

export function cancelCurveTransition(reason = 'navigation') {
  const active = flight
  if (!active) return
  active.svg.dataset.endReason = reason
  flight = null
  cancelAnimationFrame(active.frame)
  clearTimeout(active.timer)
  active.restore.forEach(restore => restore())
  active.svg.remove()
}

export function cancelAccountCurveTransition(accountId: number) {
  if (flight?.visit.accountId === accountId) cancelCurveTransition('view-change')
}

function capture(endpoint: CurveEndpoint, visit: Visit, direction: Flight['direction']): Flight | null {
  cancelCurveTransition()
  if (reducedMotion() || typeof endpoint.element.animate !== 'function' || !visible(endpoint.element)) return null
  const from = screenCoordinates(endpoint)
  if (from.filter(Boolean).length < 2) return null
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  svg.classList.add('performance-curve-flight')
  svg.dataset.direction = direction
  svg.setAttribute('aria-hidden', 'true')
  const path = document.createElementNS(svg.namespaceURI, 'path') as SVGPathElement
  path.setAttribute('fill', 'none')
  path.setAttribute('stroke', getComputedStyle(endpoint.element).getPropertyValue('--color-accent').trim())
  path.setAttribute('stroke-linecap', 'round')
  path.setAttribute('stroke-linejoin', 'round')
  const width = direction === 'open' ? 1.6 : 1.8
  let opacity = 1
  for (let node: Element | null = endpoint.element; node && node !== document.body; node = node.parentElement) {
    opacity *= Number(getComputedStyle(node).opacity)
  }
  path.setAttribute('stroke-width', String(width))
  path.setAttribute('d', curvePath(from))
  path.style.opacity = String(opacity)
  svg.append(path)
  document.body.append(svg)
  const active: Flight = {
    direction, visit, points: endpoint.points.map(point => ({ ...point })), from, snapshotId: endpoint.snapshotId,
    svg, path, width, opacity, frame: 0, timer: setTimeout(() => cancelCurveTransition('target-timeout'), 700), restore: [], concealed: new Set(), started: false,
  }
  flight = active
  conceal(endpoint, active)
  const interrupt = () => cancelCurveTransition('interrupted')
  const media = window.matchMedia('(prefers-reduced-motion: reduce)')
  const interruptKey = (event: KeyboardEvent) => {
    if (['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', ' '].includes(event.key)) interrupt()
  }
  window.addEventListener('keydown', interruptKey)
  window.addEventListener('pointerdown', interrupt)
  window.addEventListener('resize', interrupt)
  window.addEventListener('wheel', interrupt, { passive: true })
  window.addEventListener('touchmove', interrupt, { passive: true })
  media.addEventListener('change', interrupt)
  active.restore.push(() => {
    window.removeEventListener('keydown', interruptKey)
    window.removeEventListener('pointerdown', interrupt)
    window.removeEventListener('resize', interrupt)
    window.removeEventListener('wheel', interrupt)
    window.removeEventListener('touchmove', interrupt)
    media.removeEventListener('change', interrupt)
  })
  return active
}

/** 点击前捕获当前可见线；只有普通同标签页链接激活才调用。 */
export function beginCurveNavigation(identity: string): boolean {
  const endpoint = endpoints.get(identity)
  if (!endpoint) return false
  const visit: Visit = { sourceKey: currentKey, sourcePath: currentPath, identity, accountId: endpoint.accountId, scroll: workspace()?.scrollTop ?? 0 }
  // 减少动态效果也保留返回滚动位置；没有几何动画时不创建临时层。
  visits.set(`pending:${endpoint.accountId}`, visit)
  return capture(endpoint, visit, 'open') != null
}

function start(active: Flight, target: CurveEndpoint) {
  if (active.started || flight !== active) return
  if (!target.element.isConnected || !visible(target.element)) { cancelCurveTransition('target-invisible'); return }
  if (screenCoordinates(target).filter(Boolean).length < 2) { cancelCurveTransition('target-empty'); return }
  active.started = true
  active.svg.dataset.phase = 'moving'
  clearTimeout(active.timer)
  active.target = target
  conceal(target, active)
  const to = active.snapshotId && active.snapshotId === target.snapshotId
    ? screenCoordinates(target, active.points)
    : fitCurve(active.from, screenCoordinates(target))
  if (to.filter(Boolean).length < 2) { cancelCurveTransition(); return }
  const css = getComputedStyle(document.documentElement)
  const duration = curveDurationMs(css.getPropertyValue(active.direction === 'open' ? '--curve-open-duration' : '--curve-close-duration'), active.direction === 'open' ? 360 : 280)
  const finalWidth = active.direction === 'open' ? 1.8 : 1.6
  const started = performance.now()
  const tick = (now: number) => {
    if (flight !== active) return
    const elapsed = Math.min(1, (now - started) / duration)
    // CSS 标准缓动由同一 token 驱动 WAAPI；几何读取其计算进度，不采样 DOM 布局。
    const progress = easing.effect?.getComputedTiming().progress ?? elapsed
    active.path.setAttribute('d', curvePath(interpolateCurve(active.from, to, progress)))
    active.path.setAttribute('stroke-width', String(active.width + (finalWidth - active.width) * progress))
    const handoff = Math.max(0, (elapsed * duration - (duration - 80)) / 80)
    active.path.style.opacity = String((active.opacity + (1 - active.opacity) * progress) * (1 - handoff))
    if (active.target?.element.isConnected) active.target.element.style.opacity = String(handoff)
    if (elapsed < 1) active.frame = requestAnimationFrame(tick)
    else {
      const focus = active.direction === 'close' ? active.target?.element.closest('a') : null
      cancelCurveTransition('finished')
      focus?.focus({ preventScroll: true })
    }
  }
  const easing = active.svg.animate([{ offset: 0 }, { offset: 1 }], { duration, easing: css.getPropertyValue('--curve-easing').trim() || 'cubic-bezier(.4,0,.2,1)', fill: 'both' })
  active.restore.push(() => easing.cancel())
  const cancelResize = () => cancelCurveTransition('resize')
  const cancelScroll = () => cancelCurveTransition('scroll')
  const cancelMotion = () => cancelCurveTransition('reduced-motion')
  window.addEventListener('resize', cancelResize)
  const main = workspace()
  main?.addEventListener('scroll', cancelScroll, { passive: true })
  const media = window.matchMedia('(prefers-reduced-motion: reduce)')
  media.addEventListener('change', cancelMotion)
  const initialSize = { width: target.element.clientWidth, height: target.element.clientHeight }
  const resize = new ResizeObserver(() => {
    if (target.element.isConnected && active.target?.element === target.element
      && (target.element.clientWidth !== initialSize.width || target.element.clientHeight !== initialSize.height)) cancelResize()
  })
  resize.observe(target.element)
  active.restore.push(() => {
    window.removeEventListener('resize', cancelResize)
    main?.removeEventListener('scroll', cancelScroll)
    media.removeEventListener('change', cancelMotion)
    resize.disconnect()
  })
  active.frame = requestAnimationFrame(tick)
}

export function registerCurveEndpoint(endpoint: CurveEndpoint): () => void {
  endpoints.set(endpoint.identity, endpoint)
  const active = flight
  if (active && endpoint.accountId === active.visit.accountId) {
    const matches = active.direction === 'open' ? endpoint.kind === 'chart' : endpoint.identity === active.visit.identity
    if (matches) {
      conceal(endpoint, active)
      if (active.started) {
        active.target = endpoint
      } else {
        cancelAnimationFrame(active.frame)
        active.frame = requestAnimationFrame(() => {
          if (flight !== active) return
          const main = workspace()
          if (main) main.scrollTo({ top: active.direction === 'close' ? active.visit.scroll : 0, behavior: 'instant' })
          if (active.direction === 'close') endpoint.element.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'instant' })
          // 等浏览器布局与滚动恢复落定，且开始后不重新量几何。
          active.frame = requestAnimationFrame(() => start(active, endpoint))
        })
      }
    }
  }
  return () => { if (endpoints.get(endpoint.identity) === endpoint) endpoints.delete(endpoint.identity) }
}

export function curvePreviewPoints(accountId: number): PerformancePoint[] {
  return flight?.direction === 'open' && flight.visit.accountId === accountId ? flight.points : []
}

/** 落点由本次目的页面决定，与最初进入绩效的入口无关。 */
export function curveReturnDestination(source: string, destination: string) {
  const match = /^\/accounts\/(\d+)\/history\/?$/.exec(source)
  if (!match) return null
  const accountId = Number(match[1])
  const path = destination.replace(/\/$/, '') || '/'
  const kind = path === '/' ? 'fleet' : path === `/accounts/${accountId}` ? 'detail' : null
  return kind ? { accountId, identity: `performance-source-${kind}-${accountId}` } : null
}

/** 小图入口与侧栏共用同一次准备；从概览进入时展开已有的同账户曲线。 */
export function prepareCurveNavigation(destination: string): boolean {
  const source = curveReturnDestination(destination, currentPath)
  if (!source) return prepareCurveReturn(destination)
  const animated = beginCurveNavigation(source.identity)
  openFullPerformance(source.accountId)
  return animated
}

/** 路由提交前捕获；成功后调用方须禁用本次原生 View Transition。 */
export function prepareCurveReturn(destination: string): boolean {
  const target = curveReturnDestination(currentPath, destination)
  if (!target) return false
  cancelCurveTransition()
  const chart = [...endpoints.values()].find(endpoint => endpoint.kind === 'chart' && endpoint.accountId === target.accountId && endpoint.canReturn && !endpoint.preview)
  if (!chart) return false
  const recorded = visits.get(currentKey)
  const visit: Visit = { sourceKey: '', sourcePath: destination, ...target,
    scroll: recorded?.sourcePath === destination ? recorded.scroll : 0 }
  const active = capture(chart, visit, 'close')
  if (active) active.destination = destination
  return active != null
}

function rememberVisit(location: { key: string; pathname: string }) {
  const pending = [...visits.entries()].find(([key, value]) => key.startsWith('pending:') && location.pathname === `/accounts/${value.accountId}/history`)
  if (pending) visits.set(location.key, pending[1])
  for (const key of visits.keys()) if (key.startsWith('pending:')) visits.delete(key)
  // 会话内有界；不把曲线点写进 history.state 或 localStorage。
  while (visits.size > 32) visits.delete(visits.keys().next().value!)
}

/** Router 在提交 React 新页面前通知，POP 时仍能捕获当前 Canvas 对应的收益线。 */
export function observeCurveNavigation(location: { key: string; pathname: string }, action: string) {
  if (location.key === currentKey && location.pathname === currentPath) return
  const opening = flight?.direction === 'open' && location.pathname === `/accounts/${flight.visit.accountId}/history`
  if (opening && flight) {
    visits.set(location.key, flight.visit)
    const fade = workspace()?.animate([{ opacity: .3 }, { opacity: 1 }], { duration: 180, easing: 'cubic-bezier(.4,0,.2,1)' })
    if (fade) flight.restore.push(() => fade.cancel())
  } else if (flight?.direction === 'close' && !flight.committed && flight.destination === location.pathname) {
    flight.committed = true
  } else {
    cancelCurveTransition()
    if (action === 'POP' && prepareCurveReturn(location.pathname) && flight) flight.committed = true
  }
  rememberVisit(location)
  currentKey = location.key
  currentPath = location.pathname
}
