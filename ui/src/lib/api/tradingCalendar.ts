import { apiGet, apiSend, apiUpload } from '@/lib/api/client'

export type CalendarRefreshKind = 'csv' | 'python' | 'shinny'
export type CalendarAvailability = 'available' | 'unavailable'
export type CalendarUnavailableReason = 'not_configured' | 'uncovered' | 'read_failed'

export interface CalendarStatus {
  calendarId: string
  availability: CalendarAvailability
  unavailableReason: CalendarUnavailableReason | null
  refreshKind: CalendarRefreshKind | null
  functionCode: string
  coverageStart: string | null
  coverageEnd: string | null
  overrideCount: number
  lastSyncAt: string | null
}

export interface CalendarPreview {
  start: string
  end: string
  total: number
  added: number
  changed: number
  unchanged: number
}

export interface CalendarFunctionResult {
  valid: boolean
  entries: { calendar_id: string; cal_date: string; is_open: boolean }[]
  error: string | null
  traceback: string | null
  errorLine: number | null
  errorOffset: number | null
  errorType: string | null
  errorMessage: string | null
}

export interface CalendarDiagnostic {
  calendarId: string
  calDate: string
  baseIsOpen: boolean | null
  overrideIsOpen: boolean | null
  isOpen: boolean | null
}

export interface CalendarOverride {
  calendarId: string
  calDate: string
  isOpen: boolean
  baseIsOpen: boolean | null
  updatedAt: string
}

const query = (calendarId: string) => `calendarId=${encodeURIComponent(calendarId)}`

export const getCalendarStatus = (calendarId = 'china', signal?: AbortSignal) =>
  apiGet<CalendarStatus>(`/market/trading-calendar/status?${query(calendarId)}`, signal)
export const getCalendarDiagnostics = (calendarId: string, start: string, end: string, signal?: AbortSignal) =>
  apiGet<CalendarDiagnostic[]>(`/market/trading-calendar/diagnostics?${query(calendarId)}&start=${start}&end=${end}`, signal)
export const previewCalendarCsv = (calendarId: string, file: File) =>
  apiUpload<CalendarPreview>(`/market/trading-calendar/csv/preview?${query(calendarId)}`, file)
export const importCalendarCsv = (calendarId: string, file: File) =>
  apiUpload<CalendarPreview>(`/market/trading-calendar/csv/import?${query(calendarId)}`, file)
export const validateCalendarFunction = (calendarId: string, functionCode: string, start: string, end: string) =>
  apiSend<CalendarFunctionResult>('POST', '/market/trading-calendar/python/validate', {
    calendarId,
    functionCode,
    start,
    end,
  })
export const saveCalendarFunction = (calendarId: string, functionCode: string) =>
  apiSend<CalendarStatus>('PUT', '/market/trading-calendar/python', { calendarId, functionCode })
export const saveShinnyCalendar = (calendarId = 'china') =>
  apiSend<CalendarStatus>('PUT', `/market/trading-calendar/shinny?${query(calendarId)}`)
export const refreshCalendar = (calendarId = 'china') =>
  apiSend<{ ok: boolean; message: string }>('POST', `/market/trading-calendar/refresh?${query(calendarId)}`)
export const saveCalendarOverrides = (calendarId: string, entries: { calDate: string; isOpen: boolean }[]) =>
  apiSend<{ ok: boolean; message: string }>('PUT', '/market/trading-calendar/overrides', {
    entries: entries.map((entry) => ({ calendarId, ...entry })),
  })
export const getCalendarOverrides = (calendarId = 'china', signal?: AbortSignal) =>
  apiGet<CalendarOverride[]>(`/market/trading-calendar/overrides?${query(calendarId)}`, signal)
export const restoreCalendarOverrides = (calendarId: string, dates: string[]) =>
  apiSend<{ ok: boolean; message: string }>('POST', '/market/trading-calendar/overrides/restore', {
    calendarId,
    dates,
  })
