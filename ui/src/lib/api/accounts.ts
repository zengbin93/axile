/** 账户相关接口。 */
import { apiGet, apiSend } from '@/lib/api/client'
import type {
  Account,
  AccountDashboard,
  AccountNextRun,
  AccountControlPolicyEditorModel,
  AccountAssetSnapshot,
  AccountAssetSnapshotList,
  ExecuteRecordList,
  Message,
  PortfolioAccountList,
  TargetWeightSnapshot,
} from '@/types/api'

export type ScheduleCalendarStatus = 'not_required' | 'available_open' | 'available_closed' | 'unavailable'
export type ScheduleUnavailableReason = 'not_configured' | 'uncovered' | 'read_failed'

export interface SchedulePreview {
  timezone: 'Asia/Shanghai'
  evaluated_at: string
  calendar: {
    requirement: 'required' | 'not_required'
    availability: 'available' | 'unavailable' | 'not_required'
    unavailable_reason: ScheduleUnavailableReason | null
    calendar_id: string | null
    label: string | null
    coverage_start: string | null
    coverage_end: string | null
  }
  next_cursor: string | null
  has_more: boolean
  items: Array<{
    scheduled_at: string
    calendar_day: string
    calendar_status: ScheduleCalendarStatus
    action: 'execute' | 'skip'
    unavailable_reason: ScheduleUnavailableReason | null
    calendar_id: string | null
    label: string | null
    using_legacy_fallback: boolean
    reason_code: 'CALENDAR.CLOSED' | 'CALENDAR.NO_NIGHT_SESSION' | null
  }>
}

export interface ScheduleSkipActivity {
  kind: 'schedule_skip'
  occurred_at: string
  id: number
  channel: string
  reason_code: 'CALENDAR.CLOSED' | 'CALENDAR.NO_NIGHT_SESSION'
  calendar_day: string
  calendar_id: string
  calendar_label: string
}

export interface ExecutionActivity {
  kind: 'execution'
  occurred_at: string
  record: ExecuteRecordList['data'][number]
}

export type AccountActivity = ExecutionActivity | ScheduleSkipActivity

export interface AccountActivityList {
  data: AccountActivity[]
  count: number
}

/** 仪表盘聚合：一次拿到所有账户的舰队卡数据。 */
export function getDashboard(signal?: AbortSignal): Promise<AccountDashboard> {
  return apiGet<AccountDashboard>('/account/dashboard', signal)
}

/** 从交易渠道主动查询并保存最新账户资产。 */
export function refreshAccountAssets(id: number): Promise<AccountAssetSnapshot> {
  return apiSend<AccountAssetSnapshot>('POST', `/account/${id}/assets/refresh`)
}

/** 账户资产观测历史（最新在前）。 */
export function getAccountAssetSnapshots(
  id: number,
  params: { skip?: number; limit?: number } = {},
  signal?: AbortSignal,
): Promise<AccountAssetSnapshotList> {
  const q = new URLSearchParams()
  if (params.skip != null) q.set('skip', String(params.skip))
  if (params.limit != null) q.set('limit', String(params.limit))
  const qs = q.toString()
  return apiGet<AccountAssetSnapshotList>(`/account/${id}/asset_snapshots${qs ? `?${qs}` : ''}`, signal)
}

/** 账户详情。 */
export function getAccount(id: number, signal?: AbortSignal): Promise<Account> {
  return apiGet<Account>(`/account/${id}`, signal)
}

/** 读取账户流控编辑模型；presetKey 用于无副作用预览另一预设方案。 */
export function getAccountControlPolicy(
  id: number,
  presetKey?: string,
  signal?: AbortSignal,
): Promise<AccountControlPolicyEditorModel> {
  const query = presetKey ? `?preset_key=${encodeURIComponent(presetKey)}` : ''
  return apiGet<AccountControlPolicyEditorModel>(`/account/${id}/control/policy${query}`, signal)
}

/** 账户下次调度执行时间。 */
export function getNextRun(id: number, signal?: AbortSignal): Promise<AccountNextRun> {
  return apiGet<AccountNextRun>(`/account/${id}/next_run_time`, signal)
}

/** 只读预览未来原始 Cron 触发点及其日历动作；after 严格续接其后的时间线。 */
export function previewSchedule(
  tradeChannel: string,
  cronExpr: string,
  params: { after?: string | null; limit?: number } = {},
  signal?: AbortSignal,
): Promise<SchedulePreview> {
  return apiSend<SchedulePreview>('POST', '/account/schedule-preview', {
    trade_channel: tradeChannel,
    cron_expr: cronExpr,
    after: params.after ?? null,
    limit: params.limit ?? 5,
  }, signal)
}

/** 执行与休市跳过组成的账户活动流。 */
export function getAccountActivity(
  id: number,
  params: { skip?: number; limit?: number } = {},
  signal?: AbortSignal,
): Promise<AccountActivityList> {
  const query = new URLSearchParams()
  if (params.skip != null) query.set('skip', String(params.skip))
  if (params.limit != null) query.set('limit', String(params.limit))
  const suffix = query.size ? `?${query}` : ''
  return apiGet<AccountActivityList>(`/account/${id}/activity${suffix}`, signal)
}

/** 只读账户当前组合下最近一次成功计算的执行器口径目标快照。 */
export function getAccountTargetSnapshot(id: number, signal?: AbortSignal): Promise<TargetWeightSnapshot> {
  return apiGet<TargetWeightSnapshot>(`/account/${id}/target_snapshot`, signal)
}

/** 使用真实账户上下文主动重新计算并保存目标快照。 */
export function refreshAccountTargetSnapshot(id: number): Promise<TargetWeightSnapshot> {
  return apiSend<TargetWeightSnapshot>('POST', `/account/${id}/target_snapshot/refresh`)
}

/**
 * 绩效页「全量」执行记录缓存（limit=500 全量口径，按 account 键）。
 *
 * 用于「小卡 → 回看页」的即时跳转：hover 预取写入此缓存，绩效页首帧直接
 * 复用，避免落地即骨架屏，也让金额共享元素 FLIP 有真实落点。缓存随下一次成功取数刷新。
 */
const execRecordsCache = new Map<number, ExecuteRecordList>()
const execRecordsInflight = new Map<number, Promise<ExecuteRecordList>>()

/** 读取已缓存的全量执行记录（无则 ``undefined``）。 */
export function getCachedExecuteRecords(id: number): ExecuteRecordList | undefined {
  return execRecordsCache.get(id)
}

/** 预取账户全量执行记录进缓存（hover 时调用；已缓存或在途则跳过，失败静默）。 */
export function prefetchExecuteRecords(id: number): void {
  if (execRecordsCache.has(id) || execRecordsInflight.has(id)) return
  const p = getExecuteRecords(id, { limit: 500 })
  execRecordsInflight.set(id, p)
  p.finally(() => execRecordsInflight.delete(id)).catch(() => {})
}

/** 账户执行记录（分页，默认最近 100 条）。全量口径（limit=500）结果入缓存。 */
export function getExecuteRecords(
  id: number,
  params: { skip?: number; limit?: number } = {},
  signal?: AbortSignal,
): Promise<ExecuteRecordList> {
  const q = new URLSearchParams()
  if (params.skip != null) q.set('skip', String(params.skip))
  if (params.limit != null) q.set('limit', String(params.limit))
  const qs = q.toString()
  const promise = apiGet<ExecuteRecordList>(`/account/execute_records/${id}${qs ? `?${qs}` : ''}`, signal)
  if (params.limit === 500 && params.skip == null) {
    promise.then((r) => execRecordsCache.set(id, r)).catch(() => {})
  }
  return promise
}

/** 账户组合更换记录。 */
export function getPortfolioRecords(
  id: number,
  signal?: AbortSignal,
): Promise<PortfolioAccountList> {
  return apiGet<PortfolioAccountList>(`/account/portfolio_records/${id}`, signal)
}

/** 创建账户。 */
export function createAccount(body: Record<string, unknown>): Promise<Account> {
  return apiSend<Account>('POST', '/account/', body)
}

/** 更新账户（局部）。 */
export function updateAccount(id: number, patch: Partial<Account>): Promise<Account> {
  return apiSend<Account>('PATCH', `/account/${id}`, patch)
}

/** 删除账户。 */
export function deleteAccount(id: number): Promise<Message> {
  return apiSend<Message>('DELETE', `/account/${id}`)
}
