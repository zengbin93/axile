import type { AccountPerformance, PerformancePoint } from '@/types/api'
import { axisPercent, niceReturnAxis } from '@/features/history/performance'
import { amount, shanghaiTime, type CostSummary } from '@/features/history/costs'
import { pointTime, timeLabel, type ChartSelection, type Viewport } from '@/features/history/chartModel'

export const CHART_HEIGHT = 510
export const PLOT = { left: 12, right: 78, top: 16, bottom: 254, binding: 283, bindingHeight: 24, costTop: 339, costBottom: 414, navTop: 458, navBottom: 492 }
export type SeriesKey = 'account_return' | 'portfolio_return' | 'account_daily_return' | 'portfolio_daily_return'
export interface CanvasTheme { bg: string; surface: string; ink: string; muted: string; line: string; accent: string; warn: string; fill: string; font: string }
export interface ChartScene {
  domain?: Viewport
  data: AccountPerformance
  times: number[]
  width: number
  viewport: Viewport
  daily: boolean
  returnRange?: { min: number; max: number } | null
  costs: Map<string, CostSummary> | null
  portfolioNames: Map<number, string>
  theme: CanvasTheme
}

export function readCanvasTheme(element: HTMLElement): CanvasTheme {
  const css = getComputedStyle(element)
  const color = (name: string) => css.getPropertyValue(`--color-${name}`).trim()
  return { bg: color('bg'), surface: color('surface'), ink: color('ink-2'), muted: color('ink-3'), line: color('line'), accent: color('accent'), warn: color('warn'), fill: color('fill'), font: css.fontFamily }
}

export function prepareCanvas(canvas: HTMLCanvasElement, width: number): CanvasRenderingContext2D | null {
  const ratio = window.devicePixelRatio || 1
  const w = Math.round(width * ratio), h = Math.round(CHART_HEIGHT * ratio)
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h }
  const ctx = canvas.getContext('2d')
  if (!ctx) return null
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
  ctx.clearRect(0, 0, width, CHART_HEIGHT)
  return ctx
}

export const seriesKeys = (daily: boolean): [SeriesKey, SeriesKey] => daily ? ['account_daily_return', 'portfolio_daily_return'] : ['account_return', 'portfolio_return']
export const plotRight = (width: number) => width - PLOT.right
export const xPosition = (time: number, width: number, view: Viewport) => PLOT.left + (time - view.start) / (view.end - view.start || 1) * (plotRight(width) - PLOT.left)
export const xTime = (x: number, width: number, view: Viewport) => view.start + (x - PLOT.left) / (plotRight(width) - PLOT.left) * (view.end - view.start)

export function chartAxis(scene: ChartScene) {
  if (scene.returnRange) {
    const { min, max } = scene.returnRange
    const rough = (max - min) / 5
    const power = 10 ** Math.floor(Math.log10(rough))
    const step = ([1, 2, 2.5, 5, 10].find(n => n * power >= rough) ?? 10) * power
    const first = Math.ceil(min / step) * step
    const ticks = Array.from({ length: Math.max(0, Math.floor((max - first) / step) + 1) }, (_, i) => first + i * step)
    return { min, max, step, ticks }
  }
  const keys = seriesKeys(scene.daily)
  const values = scene.data.points.flatMap((p, i) => scene.times[i] >= scene.viewport.start && scene.times[i] <= scene.viewport.end || !scene.daily && (scene.times[i] < scene.viewport.start && (scene.times[i + 1] ?? Infinity) >= scene.viewport.start || scene.times[i] > scene.viewport.end && (scene.times[i - 1] ?? -Infinity) <= scene.viewport.end)
    ? keys.flatMap(key => typeof p[key] === 'number' && Number.isFinite(p[key]) ? [p[key]!] : []) : [])
  return niceReturnAxis(values)
}

export function returnY(value: number, axis: ReturnType<typeof niceReturnAxis>) {
  return PLOT.top + (axis.max - value) / (axis.max - axis.min) * (PLOT.bottom - PLOT.top)
}

function line(ctx: CanvasRenderingContext2D, x1: number, y1: number, x2: number, y2: number, color: string) {
  ctx.strokeStyle = color; ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke()
}

function textFit(ctx: CanvasRenderingContext2D, text: string, width: number): string {
  if (ctx.measureText(text).width <= width) return text
  let end = text.length
  while (end > 0 && ctx.measureText(`${text.slice(0, end)}…`).width > width) end--
  return end ? `${text.slice(0, end)}…` : ''
}

function drawBindings(ctx: CanvasRenderingContext2D, scene: ChartScene) {
  const { data, width, viewport, theme } = scene
  ctx.fillStyle = theme.muted; ctx.fillText('组合绑定', PLOT.left, 271)
  data.bindings.forEach((binding, i) => {
    const start = Math.max(PLOT.left, xPosition(shanghaiTime(binding.time), width, viewport))
    const end = Math.min(plotRight(width), xPosition(i + 1 < data.bindings.length ? shanghaiTime(data.bindings[i + 1].time) : viewport.end, width, viewport))
    if (end <= start) return
    line(ctx, start, PLOT.binding + PLOT.bindingHeight - 1, end, PLOT.binding + PLOT.bindingHeight - 1, theme.line)
    const boundary = xPosition(shanghaiTime(binding.time), width, viewport)
    if (boundary >= PLOT.left) line(ctx, boundary, PLOT.binding + 4, boundary, PLOT.binding + PLOT.bindingHeight - 1, theme.muted)
  })
}

function drawReturns(ctx: CanvasRenderingContext2D, scene: ChartScene) {
  const { data, width, viewport, theme, times } = scene
  const axis = chartAxis(scene)
  axis.ticks.forEach(value => {
    const y = returnY(value, axis)
    line(ctx, PLOT.left, y, plotRight(width), y, theme.line)
    ctx.fillStyle = theme.muted; ctx.fillText(textFit(ctx, axisPercent(value, axis.step), PLOT.right - 12), plotRight(width) + 9, y + 4)
  })
  ctx.save(); ctx.beginPath(); ctx.rect(PLOT.left, PLOT.top, plotRight(width) - PLOT.left, PLOT.bottom - PLOT.top); ctx.clip()
  const count = times.filter(t => t >= viewport.start && t <= viewport.end).length
  const barWidth = Math.max(1, Math.min(9, (plotRight(width) - PLOT.left) / Math.max(2, count) / 3))
  seriesKeys(scene.daily).forEach((key, series) => {
    ctx.strokeStyle = ctx.fillStyle = series === 0 ? theme.accent : theme.ink
    ctx.lineWidth = series === 0 ? 1.8 : 1.5
    ctx.setLineDash(series === 1 ? [5, 3] : [])
    ctx.beginPath(); let connected = false
    data.points.forEach((point, i) => {
      const value = point[key]
      if (value == null || !Number.isFinite(value)) { connected = false; return }
      const x = xPosition(times[i], width, viewport), y = returnY(value, axis)
      if (scene.daily) {
        const zero = returnY(0, axis)
        ctx.fillRect(x + (series - 1) * barWidth, Math.min(zero, y), barWidth, Math.max(1, Math.abs(y - zero)))
      } else {
        if (connected) ctx.lineTo(x, y)
        else ctx.moveTo(x, y)
        connected = true
      }
    })
    if (!scene.daily) ctx.stroke()
  })
  ctx.restore(); ctx.lineWidth = 1
}

function drawCosts(ctx: CanvasRenderingContext2D, scene: ChartScene) {
  const { data, times, costs, width, viewport, theme } = scene
  ctx.fillStyle = theme.muted; ctx.fillText('每日滑点成本', PLOT.left, 329)
  const days = data.points.flatMap((p, i) => (i === data.points.length - 1 || p.date.slice(0, 10) !== data.points[i + 1].date.slice(0, 10)) && times[i] >= viewport.start && times[i] <= viewport.end ? [{ p, time: times[i] }] : [])
  const values = days.flatMap(({ p }) => { const v = costs?.get(p.date.slice(0, 10))?.cost; return v == null ? [] : [v] })
  if (!values.length) {
    const missing = days.some(({ p }) => costs?.has(p.date.slice(0, 10)))
    ctx.fillText(costs == null ? '成本数据未就绪' : missing ? '成本缺失' : '本区间无成交记录', PLOT.left, (PLOT.costTop + PLOT.costBottom) / 2)
    return
  }
  const low = Math.min(0, ...values), high = Math.max(0, ...values)
  const y = (v: number) => high === low ? (PLOT.costTop + PLOT.costBottom) / 2 : PLOT.costTop + (high - v) / (high - low) * (PLOT.costBottom - PLOT.costTop)
  line(ctx, PLOT.left, y(0), plotRight(width), y(0), theme.line)
  ctx.fillStyle = theme.muted
  for (const value of new Set([low, high])) ctx.fillText(textFit(ctx, amount(value), PLOT.right - 12), plotRight(width) + 9, y(value) + 4)
  const w = Math.max(1, Math.min(16, (plotRight(width) - PLOT.left) / Math.max(2, days.length) * 0.6))
  ctx.save(); ctx.beginPath(); ctx.rect(PLOT.left, PLOT.costTop - 1, plotRight(width) - PLOT.left, PLOT.costBottom - PLOT.costTop + 3); ctx.clip()
  days.forEach(({ p, time }) => {
    const summary = costs?.get(p.date.slice(0, 10)), value = summary?.cost
    const x = xPosition(time, width, viewport)
    if (value == null) { ctx.fillStyle = theme.muted; ctx.fillText('·', x - 2, PLOT.costBottom); return }
    ctx.globalAlpha = summary!.covered < summary!.count ? 0.5 : 0.9
    ctx.fillStyle = value > 0 ? theme.warn : value < 0 ? theme.accent : theme.muted
    ctx.fillRect(x - w / 2, Math.min(y(0), y(value)), w, Math.max(1, Math.abs(y(value) - y(0))))
  })
  ctx.restore()
}

function drawTimeAxis(ctx: CanvasRenderingContext2D, scene: ChartScene, exclude?: { left: number; right: number }) {
  const { width, viewport, theme } = scene
  const available = plotRight(width) - PLOT.left
  const count = Math.max(1, Math.floor(available / 145))
  const intraday = viewport.end - viewport.start < 864e5
  ctx.fillStyle = theme.muted
  for (let i = 0; i <= count; i++) {
    const time = viewport.start + (viewport.end - viewport.start) * i / count
    const label = timeLabel(time).slice(intraday ? 11 : 0, intraday ? 16 : 10)
    ctx.textAlign = i === 0 ? 'left' : i === count ? 'right' : 'center'
    const x = PLOT.left + available * i / count, textWidth = ctx.measureText(label).width
    const left = x - (i === 0 ? 0 : i === count ? textWidth : textWidth / 2)
    if (!exclude || left + textWidth < exclude.left || left > exclude.right) ctx.fillText(label, x, 439)
  }
  ctx.textAlign = 'left'
}

function drawNavigator(ctx: CanvasRenderingContext2D, scene: ChartScene) {
  const { width, viewport, times, data, theme } = scene
  const full = scene.domain ?? { start: times[0], end: times[times.length - 1] }
  ctx.fillStyle = theme.line; ctx.fillRect(PLOT.left, PLOT.navTop, plotRight(width) - PLOT.left, PLOT.navBottom - PLOT.navTop)
  const values = data.points.flatMap(p => p.account_return == null ? [] : [p.account_return])
  const low = Math.min(0, ...values), high = Math.max(0.01, ...values)
  ctx.strokeStyle = theme.muted; ctx.beginPath(); let connected = false
  data.points.forEach((p, i) => {
    if (p.account_return == null) { connected = false; return }
    const x = xPosition(times[i], width, full), y = PLOT.navBottom - 4 - (p.account_return - low) / (high - low) * 25
    if (connected) ctx.lineTo(x, y); else ctx.moveTo(x, y)
    connected = true
  })
  ctx.stroke()
  const a = xPosition(viewport.start, width, full), b = xPosition(viewport.end, width, full)
  ctx.fillStyle = theme.bg; ctx.globalAlpha = 0.65
  ctx.fillRect(PLOT.left, PLOT.navTop, a - PLOT.left, PLOT.navBottom - PLOT.navTop)
  ctx.fillRect(b, PLOT.navTop, plotRight(width) - b, PLOT.navBottom - PLOT.navTop)
  ctx.globalAlpha = 1; ctx.strokeStyle = theme.accent; ctx.strokeRect(a, PLOT.navTop, b - a, PLOT.navBottom - PLOT.navTop)
  for (const x of [a, b]) { ctx.fillStyle = theme.accent; ctx.fillRect(x - 2, PLOT.navTop + 8, 4, 18) }
}

export function drawScene(canvas: HTMLCanvasElement, scene: ChartScene) {
  const ctx = prepareCanvas(canvas, scene.width)
  if (!ctx) return
  ctx.font = `11px ${scene.theme.font}`
  drawReturns(ctx, scene); drawBindings(ctx, scene); drawCosts(ctx, scene); drawTimeAxis(ctx, scene); drawNavigator(ctx, scene)
}

export function drawOverlay(canvas: HTMLCanvasElement, scene: ChartScene, hover: number | null, selection: ChartSelection, bindingTime: number | null = null, cursor: { time: number; x: number; y: number } | null = null) {
  const ctx = prepareCanvas(canvas, scene.width)
  if (!ctx) return
  const { width, viewport, theme, times, data } = scene
  const right = plotRight(width)
  ctx.font = `11px ${theme.font}`
  const binding = bindingTime == null ? null : bindingAt(data, bindingTime)
  if (binding) {
    const a = Math.max(PLOT.left, xPosition(shanghaiTime(binding.binding.time), width, viewport))
    const b = Math.min(right, xPosition(shanghaiTime(binding.end), width, viewport))
    ctx.fillStyle = theme.accent; ctx.globalAlpha = 0.1
    ctx.fillRect(a, PLOT.binding, Math.max(0, b - a), PLOT.bindingHeight)
    ctx.globalAlpha = 1
    line(ctx, a, PLOT.binding + PLOT.bindingHeight - 1, b, PLOT.binding + PLOT.bindingHeight - 1, theme.accent)
  }
  if (selection) {
    const a = xPosition(selection.kind !== 'interval' ? selection.time : selection.start, width, viewport)
    const b = selection.kind === 'interval' ? xPosition(selection.end, width, viewport) : a
    ctx.save(); ctx.beginPath(); ctx.rect(PLOT.left, PLOT.top, right - PLOT.left, PLOT.costBottom - PLOT.top); ctx.clip()
    if (selection.kind === 'interval') { ctx.fillStyle = theme.accent; ctx.globalAlpha = 0.08; ctx.fillRect(a, PLOT.top, b - a, PLOT.costBottom - PLOT.top); ctx.globalAlpha = 1 }
    for (const x of new Set([a, b])) {
      line(ctx, x, PLOT.top, x, PLOT.costBottom, theme.accent)
      ctx.fillStyle = theme.accent; ctx.fillRect(x - 3, PLOT.top, 6, 15)
    }
    ctx.restore()
  }
  if (cursor && selection?.kind !== 'execution') {
    const x = xPosition(cursor.time, width, viewport)
    ctx.setLineDash([3, 3]); line(ctx, x, PLOT.top, x, PLOT.costBottom, theme.muted)
    line(ctx, PLOT.left, cursor.y, right, cursor.y, theme.muted); ctx.setLineDash([])
    const axis = chartAxis(scene)
    const value = axis.max - (cursor.y - PLOT.top) / (PLOT.bottom - PLOT.top) * (axis.max - axis.min)
    ctx.fillStyle = theme.bg; ctx.fillRect(right + 2, cursor.y - 10, PLOT.right - 2, 20)
    ctx.fillStyle = theme.ink; ctx.fillText(axisPercent(value, axis.step), right + 8, cursor.y + 4)
    const label = timeLabel(cursor.time), labelWidth = ctx.measureText(label).width + 12
    const labelX = Math.max(PLOT.left, Math.min(right - labelWidth, x - labelWidth / 2))
    ctx.fillStyle = theme.ink; ctx.fillRect(labelX, 424, labelWidth, 22)
    ctx.fillStyle = theme.bg; ctx.fillText(label, labelX + 6, 439)
    return
  }
  if (hover == null || !data.points[hover] || selection?.kind === 'execution') return
  const x = xPosition(times[hover], width, viewport)
  if (x < PLOT.left || x > right) return
  ctx.setLineDash([3, 3]); line(ctx, x, PLOT.top, x, PLOT.costBottom, theme.muted); ctx.setLineDash([])
  const axis = chartAxis(scene)
  const marks = seriesKeys(scene.daily).flatMap((key, series) => {
    const value = data.points[hover][key]
    return value == null ? [] : [{ value, series, y: returnY(value, axis) }]
  }).sort((a, b) => a.y - b.y)
  marks.forEach(({ series, y }) => {
    const color = series === 0 ? theme.accent : theme.ink
    ctx.fillStyle = theme.bg; ctx.strokeStyle = color; ctx.lineWidth = 2
    ctx.beginPath(); ctx.arc(x, y, 3, 0, Math.PI * 2); ctx.fill(); ctx.stroke(); ctx.lineWidth = 1
  })
  const label = timeLabel(times[hover])
  const labelWidth = ctx.measureText(label).width + 12
  const labelX = Math.max(PLOT.left, Math.min(right - labelWidth, x - labelWidth / 2))
  ctx.fillStyle = theme.bg; ctx.fillRect(PLOT.left, 423, right - PLOT.left, 25)
  drawTimeAxis(ctx, scene, { left: labelX - 8, right: labelX + labelWidth + 8 })
  ctx.fillStyle = theme.ink; ctx.fillRect(labelX, 424, labelWidth, 22)
  ctx.fillStyle = theme.bg; ctx.fillText(label, labelX + 6, 439)
}

export function bindingAt(data: AccountPerformance, time: number) {
  const index = data.bindings.findLastIndex(b => shanghaiTime(b.time) <= time)
  return index < 0 ? null : { binding: data.bindings[index], end: data.bindings[index + 1]?.time ?? data.end }
}

export function pointLabel(point: PerformancePoint): string {
  return point.observed_at ? timeLabel(pointTime(point)) : point.date.replace('T', ' ')
}
