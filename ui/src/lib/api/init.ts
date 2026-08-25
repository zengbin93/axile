/** 首启初始化向导接口。 */
import { apiGet, apiSend, apiUpload } from '@/lib/api/client'
import type { CalendarFunctionResult } from '@/lib/api/tradingCalendar'

export interface InitCalendarEntry {
  calendar_id: string
  cal_date: string
  is_open: boolean
}

export interface InitTradingCalendar {
  calendar_id: string
  refresh_kind: 'csv' | 'python'
  function_code?: string
  entries: InitCalendarEntry[]
}

export interface InitCalendarPreview {
  start: string
  end: string
  total: number
  entries: InitCalendarEntry[]
}

/** 向导各字段的预填值（对应后端 Settings 的向导字段）。 */
export interface InitValues {
  sqlalchemy_database_uri: string
  /** 执行错误告警飞书机器人 key（系统级，区别于账户各自的 `feishu_key`）；空串表示不推送。 */
  exe_err_feishu_key: string
  environment: string
  app_log_dir: string
  axile_log_rotation: string
  /** 只表示是否已配置；Token 本身永不经 API 返回。 */
  tushare_configured?: boolean
  /** 仅提交给保存接口；状态接口不会返回该字段。 */
  tushare_token?: string
  algorithm_modules: string[]
  algorithm_directories: string[]
  trading_calendars?: InitTradingCalendar[]
}

/** 初始化就绪状态与预填值。 */
export interface InitStatus {
  configured: boolean
  environment: string
  values: InitValues
}

/** 连通性测试 / 保存操作结果。 */
export interface TestResult {
  ok: boolean
  message: string
}

/**
 * 最近一次成功的 `/init/status` 预填值缓存。
 *
 * 启动时拉到的值与当前 `config.toml` 一致。缓存供系统配置页同步取用，免去二次
 * fetch 造成的加载闪屏；热更新配置成功后须同步维护这份缓存。
 */
let cachedInitValues: InitValues | null = null

/** 查询初始化就绪状态与预填值。`signal` 用于配合轮询取消。 */
export function initStatus(signal?: AbortSignal): Promise<InitStatus> {
  return apiGet<InitStatus>('/init/status', signal).then((status) => {
    cachedInitValues = status.values
    return status
  })
}

/** 同步读取上一次成功拉取的预填值；从未拉取成功时返回 `null`。 */
export function peekInitValues(): InitValues | null {
  return cachedInitValues
}

/** 测试数据库连通性。 */
export function testDb(uri: string): Promise<TestResult> {
  return apiSend<TestResult>('POST', '/init/test-db', { uri })
}

/** 测试执行告警飞书机器人连通性（向其推送一张联通测试卡片）。 */
export function testFeishu(key: string): Promise<TestResult> {
  return apiSend<TestResult>('POST', '/init/test-feishu', { key })
}

/** 保存系统级执行错误告警配置；成功后当前服务进程立即使用新值。 */
export function saveExecutionAlert(exeErrFeishuKey: string): Promise<TestResult> {
  return apiSend<TestResult>('PATCH', '/init/execution-alert', {
    exe_err_feishu_key: exeErrFeishuKey,
  }).then((result) => {
    if (result.ok && cachedInitValues) {
      cachedInitValues = { ...cachedInitValues, exe_err_feishu_key: exeErrFeishuKey }
    }
    return result
  })
}

export function previewInitCalendarCsv(calendarId: string, file: File): Promise<InitCalendarPreview> {
  return apiUpload<InitCalendarPreview>(`/init/trading-calendar-csv?calendarId=${encodeURIComponent(calendarId)}`, file)
}

export function testInitCalendarFunction(calendarId: string, functionCode: string): Promise<CalendarFunctionResult> {
  return apiSend<CalendarFunctionResult>('POST', '/init/test-trading-calendar-function', { calendarId, functionCode })
}

/** 保存初始化配置；成功后后端将自退出并由 supervisor 拉起重启。 */
export function saveInit(values: InitValues): Promise<TestResult> {
  return apiSend<TestResult>('POST', '/init/save', values)
}
