import type { CalendarRange, PerformancePoint } from '@/types/api'

export type TimeScaleMode = 'observations' | 'natural'

export interface TimeScale {
  mode: TimeScaleMode
  anchors: number[]
  project: (time: number) => number
  invert: (coordinate: number) => number
}

const bisect = (values: number[], value: number) => {
  let low = 0, high = values.length
  while (low < high) {
    const middle = (low + high) >>> 1
    if (values[middle] <= value) low = middle + 1
    else high = middle
  }
  return Math.max(0, Math.min(values.length - 2, low - 1))
}

export function createTimeScale(mode: TimeScaleMode, rawAnchors: number[]): TimeScale {
  const anchors = [...new Set(rawAnchors.filter(Number.isFinite))].sort((a, b) => a - b)
  if (mode === 'natural' || anchors.length < 2) return { mode, anchors, project: time => time, invert: coordinate => coordinate }
  const step = 86_400_000
  const project = (time: number) => {
    const index = bisect(anchors, time)
    return (index + (time - anchors[index]) / (anchors[index + 1] - anchors[index])) * step
  }
  const invert = (coordinate: number) => {
    const position = coordinate / step
    const index = Math.max(0, Math.min(anchors.length - 2, Math.floor(position)))
    return anchors[index] + (position - index) * (anchors[index + 1] - anchors[index])
  }
  return { mode, anchors, project, invert }
}

const dayStart = (day: string) => new Date(`${day}T00:00:00+08:00`).getTime()

export function closedDaysBetween(start: number, end: number, ranges: CalendarRange[]): number {
  let count = 0
  for (const range of ranges) {
    let day = dayStart(range.start)
    const last = dayStart(range.end)
    while (day <= last) {
      if (day >= start && day + 86_400_000 <= end) count++
      day += 86_400_000
    }
  }
  return count
}

export function observationAnchors(points: PerformancePoint[]): number[] {
  return points.map(point => new Date(`${point.observed_at ?? point.date}${/[zZ]|[+-]\d\d:\d\d$/.test(point.observed_at ?? point.date) ? '' : '+08:00'}`).getTime())
}
