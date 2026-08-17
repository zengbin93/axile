/** 首启初始化向导接口。 */
import { apiGet, apiSend } from '@/lib/api/client'

/** 向导各字段的预填值（对应后端 Settings 的向导字段）。 */
export interface InitValues {
  sqlalchemy_database_uri: string
  quant_data_token: string
  quant_data_api: string
  /** 执行错误告警飞书机器人 key（系统级，区别于账户各自的 `feishu_key`）；空串表示不推送。 */
  exe_err_feishu_key: string
  environment: string
  app_log_dir: string
  axile_log_rotation: string
  algorithm_modules: string[]
  algorithm_directories: string[]
}

/** 初始化就绪状态与预填值。 */
export interface InitStatus {
  configured: boolean
  /** 量化数据源是否就绪（quant_data_api 非空）；false 时仅允许自定义组合。 */
  data_source_available: boolean
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
 * 运行期配置只会被系统配置向导自身修改（且改后必重启重读），因此启动时
 * 拉到的值恒等于当前 `config.toml`。缓存供系统配置页同步取用，免去二次
 * fetch 造成的加载闪屏。
 */
let cachedInitValues: InitValues | null = null

/**
 * 最近一次成功的 `/init/status` 的数据源能力位缓存。
 *
 * 与 {@link cachedInitValues} 同理：该值随配置改动必重启+reload，故启动时拉到的值恒等于
 * 当前有效配置。组合编辑器据此同步决定是否放开「策略组合」档，免去二次 fetch。
 */
let cachedDataSourceAvailable: boolean | null = null

/** 查询初始化就绪状态与预填值。`signal` 用于配合轮询取消。 */
export function initStatus(signal?: AbortSignal): Promise<InitStatus> {
  return apiGet<InitStatus>('/init/status', signal).then((status) => {
    cachedInitValues = status.values
    cachedDataSourceAvailable = status.data_source_available
    return status
  })
}

/** 同步读取上一次成功拉取的预填值；从未拉取成功时返回 `null`。 */
export function peekInitValues(): InitValues | null {
  return cachedInitValues
}

/**
 * 同步读取数据源能力位；从未拉取成功时返回 `null`。
 *
 * 调用方对 `null`（启动探测失败的降级）应按「允许」处理——真正的兜底由后端护栏
 * （无数据源时策略权重路径 422）负责，前端不因探测失败而误锁自定义。
 */
export function peekDataSourceAvailable(): boolean | null {
  return cachedDataSourceAvailable
}

/** 测试量化数据源连通性。 */
export function testQuantData(token: string, dataApi: string): Promise<TestResult> {
  return apiSend<TestResult>('POST', '/init/test-quant-data', { token, data_api: dataApi })
}

/** 测试数据库连通性。 */
export function testDb(uri: string): Promise<TestResult> {
  return apiSend<TestResult>('POST', '/init/test-db', { uri })
}

/** 测试执行告警飞书机器人连通性（向其推送一张联通测试卡片）。 */
export function testFeishu(key: string): Promise<TestResult> {
  return apiSend<TestResult>('POST', '/init/test-feishu', { key })
}

/** 保存初始化配置；成功后后端将自退出并由 supervisor 拉起重启。 */
export function saveInit(values: InitValues): Promise<TestResult> {
  return apiSend<TestResult>('POST', '/init/save', values)
}
