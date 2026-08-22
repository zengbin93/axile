/** 账户相关接口。 */
import { apiGet, apiSend } from '@/lib/api/client'
import type {
  Account,
  AccountDashboard,
  AccountNextRun,
  AccountControlPolicyEditorModel,
  ExecuteRecordList,
  LatestWeights,
  Message,
  PortfolioAccountList,
} from '@/types/api'

/** 仪表盘聚合：一次拿到所有账户的舰队卡数据。 */
export function getDashboard(signal?: AbortSignal): Promise<AccountDashboard> {
  return apiGet<AccountDashboard>('/account/dashboard', signal)
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

/**
 * 账户当前的「执行器口径」目标权重（symbol → weight，可负=空头）。
 *
 * 与组合级 `getLatestWeights` 的区别：后端已按账户多空杠杆与 `weight_precision`
 * 缩放，展示口径与实际下单口径一致——持仓明细据此对照真实持仓（含杠杆）判定「到位」
 * 时不会因杠杆而误判。未绑定组合时返回空映射。
 */
export function getAccountTargetWeights(id: number, signal?: AbortSignal): Promise<LatestWeights> {
  return apiGet<LatestWeights>(`/account/${id}/target_weights`, signal)
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
