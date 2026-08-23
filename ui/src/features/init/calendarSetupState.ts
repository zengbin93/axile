import type { InitCalendarPreview, InitTradingCalendar } from '@/lib/api/init'
import type { CalendarRequirement } from '@/lib/api/system'
import type { CalendarFunctionResult } from '@/lib/api/tradingCalendar'

const DEFAULT_FUNCTION = `from datetime import date, timedelta

def get_trading_calendar(calendar_id: str, start: date, end: date) -> list[dict]:
    rows = []
    current = start
    while current <= end:
        rows.append({"calendar_id": calendar_id, "cal_date": current.isoformat(), "is_open": current.weekday() < 5})
        current += timedelta(days=1)
    return rows
`

export type CalendarMethod = 'python' | 'csv'
export const CALENDAR_METHODS: readonly CalendarMethod[] = ['python', 'csv']

export type CalendarState = CalendarRequirement & {
  expandedMethod: CalendarMethod | null
  selectedMethod: CalendarMethod | null
  fileName: string
  dragging: boolean
  csv: { busy: boolean; error: string | null; preview: InitCalendarPreview | null }
  python: { busy: boolean; error: string | null; code: string; result: CalendarFunctionResult | null }
}

export interface CalendarSetupSnapshot {
  calendars: InitTradingCalendar[]
  summary: string[]
}

export function initialCalendarState(requirement: CalendarRequirement): CalendarState {
  return {
    ...requirement,
    expandedMethod: null,
    selectedMethod: null,
    fileName: '',
    dragging: false,
    csv: { busy: false, error: null, preview: null },
    python: { busy: false, error: null, code: DEFAULT_FUNCTION, result: null },
  }
}

function selectedCalendar(calendar: CalendarState): InitTradingCalendar | null {
  if (calendar.selectedMethod === 'csv' && calendar.csv.preview) {
    return { calendar_id: calendar.calendar_id, refresh_kind: 'csv', entries: calendar.csv.preview.entries }
  }
  if (calendar.selectedMethod === 'python' && calendar.python.result?.valid) {
    return {
      calendar_id: calendar.calendar_id,
      refresh_kind: 'python',
      function_code: calendar.python.code,
      entries: calendar.python.result.entries,
    }
  }
  return null
}

export function calendarSetupSnapshot(calendars: CalendarState[]): CalendarSetupSnapshot {
  const configured = calendars.map(selectedCalendar)
  return {
    calendars: configured.filter((item): item is InitTradingCalendar => item !== null),
    summary: calendars.map((item) => `${item.label}：${selectedCalendar(item) ? (item.selectedMethod === 'csv' ? 'CSV' : '自定义函数自动刷新') : '未配置，自动排程继续执行'}`),
  }
}
