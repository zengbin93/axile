/** 组合相关接口。 */
import { apiGet, apiSend } from '@/lib/api/client'
import type {
  LatestWeights,
  Message,
  Portfolio,
  PortfolioList,
  StrategyConfigList,
  Strategy,
  TradeChannel,
  ValidateCustomCalcResult,
} from '@/types/api'

/** 组合列表（不含策略）。 */
export function getPortfolios(signal?: AbortSignal): Promise<PortfolioList> {
  return apiGet<PortfolioList>('/portfolio/', signal)
}

/** 组合详情（含当前策略与绑定账户）。 */
export function getPortfolio(id: number, signal?: AbortSignal): Promise<Portfolio> {
  return apiGet<Portfolio>(`/portfolio/${id}`, signal)
}

/** 组合策略更换记录。 */
export function getStrategyRecords(
  id: number,
  signal?: AbortSignal,
): Promise<StrategyConfigList> {
  return apiGet<StrategyConfigList>(`/portfolio/strategies_records/${id}`, signal)
}

/** 组合当前目标权重（symbol → weight，可负=空头）。 */
export function getLatestWeights(
  id: number,
  channel: TradeChannel,
  signal?: AbortSignal,
): Promise<LatestWeights> {
  return apiGet<LatestWeights>(
    `/portfolio/latest_weights/${id}?trade_channel=${channel}`,
    signal,
  )
}

/**
 * 试算一份策略配置合成后的目标权重（不落库）。
 *
 * 供编辑组合时「生效目标·前后对比」使用：对旧配置与草稿配置背靠背调用，
 * 落在同一根 bar 上，差异即可干净归因到配置改动本身。
 */
export function previewWeights(
  strategies: Strategy[],
  channel: TradeChannel,
): Promise<LatestWeights> {
  return apiSend<LatestWeights>('POST', '/portfolio/preview_weights', {
    strategies,
    trade_channel: channel,
  })
}

/**
 * 校验一段自定义组合脚本（不落库、不下单）。
 *
 * 执行用户脚本里的 `calculate_portfolio(context)` 一次并返回目标权重或错误信息。
 * 不传 `account_id` 走样例上下文（Dry-run）；传则借该账户构造真实上下文执行。
 * 脚本错误以 `{ valid: false }` 结构化返回（HTTP 200）；仅账户不存在等调用错误会抛 `ApiError`。
 */
export function validateCustomCalc(body: {
  custom_calc_py_code: string
  account_id?: number | null
}): Promise<ValidateCustomCalcResult> {
  return apiSend<ValidateCustomCalcResult>('POST', '/portfolio/validate_custom_calc', body)
}

/** 创建组合。 */
export function createPortfolio(body: {
  name: string
  market: string
  description?: string | null
  custom_calc_py_code?: string | null
  status?: string | null
  tag?: string | null
  strategies: Strategy[]
}): Promise<Portfolio> {
  // 后端 PortfolioCreate 要求这些字段「存在」（即便为 null），补齐默认值。
  return apiSend<Portfolio>('POST', '/portfolio/', {
    description: null,
    custom_calc_py_code: null,
    status: null,
    tag: null,
    ...body,
  })
}

/** 更新组合（局部）。 */
export function updatePortfolio(
  id: number,
  patch: Partial<{
    name: string
    market: string
    description: string | null
    custom_calc_py_code: string | null
    status: string | null
    tag: string | null
    strategies: Strategy[]
  }>,
): Promise<Portfolio> {
  return apiSend<Portfolio>('PATCH', `/portfolio/${id}`, patch)
}

/** 删除组合。 */
export function deletePortfolio(id: number): Promise<Message> {
  return apiSend<Message>('DELETE', `/portfolio/${id}`)
}
