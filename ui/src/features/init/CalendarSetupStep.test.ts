import { describe, expect, test } from 'bun:test'
import {
  CALENDAR_METHODS,
  calendarSetupSnapshot,
  initialCalendarState,
  type CalendarState,
} from '@/features/init/calendarSetupState'

const requirement = {
  calendar_id: 'china',
  label: '中国交易日历',
  channels: ['ctp'],
  channel_labels: ['CTP'],
}

const entries = [{ calendar_id: 'china', cal_date: '2026-08-23', is_open: false }]

describe('初始化交易日历布局状态', () => {
  test('自定义函数在前且两张卡片初始折叠', () => {
    const state = initialCalendarState(requirement)
    expect(CALENDAR_METHODS).toEqual(['python', 'csv'])
    expect(state.expandedMethod).toBeNull()
    expect(state.selectedMethod).toBeNull()
  })

  test('未配置时允许空载荷并给出 fail-open 摘要', () => {
    const snapshot = calendarSetupSnapshot([initialCalendarState(requirement)])
    expect(snapshot.calendars).toEqual([])
    expect(snapshot.summary).toEqual(['中国交易日历：未配置，自动排程继续执行'])
  })

  test('即使两种候选数据都存在也只提交最终选中的一种', () => {
    const base = initialCalendarState(requirement)
    const state: CalendarState = {
      ...base,
      selectedMethod: 'python',
      csv: { busy: false, error: null, preview: { start: '2026-08-23', end: '2026-08-23', total: 1, entries } },
      python: { ...base.python, result: { valid: true, entries, error: null, traceback: null, errorLine: null, errorOffset: null, errorType: null, errorMessage: null } },
    }

    expect(calendarSetupSnapshot([state]).calendars).toEqual([{
      calendar_id: 'china',
      refresh_kind: 'python',
      function_code: state.python.code,
      entries,
    }])
    expect(calendarSetupSnapshot([{ ...state, selectedMethod: 'csv' }]).calendars).toEqual([{
      calendar_id: 'china',
      refresh_kind: 'csv',
      entries,
    }])
  })
})
