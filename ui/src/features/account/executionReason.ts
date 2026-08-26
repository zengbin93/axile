/** 执行审计内部原因码的人读文案；原始代码只应出现在原始证据中。 */
const REASON_CODE_LABEL: Record<string, string> = {
  'COMMON.SYMBOL_SKIPPED': '无需下单',
  'COMMON.SUB_MIN_NOTIONAL': '未达到最小下单金额',
  'COMMON.SUB_MIN_QTY': '数量取整后不足最小下单量',
  'COMMON.MARKET_FALLBACK_CANCEL_FAILED': '市价兜底前撤单失败',
  'COMMON.MARKET_FALLBACK_ORDER_FAILED': '市价兜底下单失败',
  'COMMON.MARKET_FALLBACK_ORDER_SUBMITTED': '已提交市价兜底单',
  'COMMON.MARKET_FALLBACK_PRICE_PROTECTION': '价格保护阻止市价兜底',
  'COMMON.ORDER_CHASE': '已追价',
  'COMMON.ORDER_CHASE_CANCEL_UNCONFIRMED': '追价前撤单未确认',
  'COMMON.ORDER_SUBMITTED': '已提交订单',
  'COMMON.EXECUTION_STARTED': '开始执行',
  'COMMON.INPUT_SNAPSHOTTED': '已冻结输入',
  'COMMON.TARGET_COMPUTED': '已算出目标',
  'COMMON.EXECUTION_COMPLETED': '执行完成',
  'COMMON.EXECUTION_FAILED': '执行失败',
  'COMMON.EXECUTION_TERMINATED': '执行已终止',
  'COMMON.EXECUTION_TERMINATION_REQUESTED': '已请求终止',
  'COMMON.EXECUTION_TERMINATION_ACKED': '已确认终止',
  'CALENDAR.CLOSED': '休市，已跳过',
  'CALENDAR.NO_NIGHT_SESSION': '无对应夜盘，已跳过',
  'CALENDAR.SESSION_CLOSED': '非交易时段，已跳过',
  BUSY: '已有执行在途，本次排程跳过',
  'RISK.FORBIDDEN': '受账户交易限制',
}

/** 返回已知原因码的人读文案；未知代码使用调用方提供的场景化兜底。 */
export function executionReasonText(reasonCode: string | null | undefined, fallback: string): string {
  return (reasonCode && REASON_CODE_LABEL[reasonCode]) || fallback
}

/** 普通无操作事件在结果卡已有“跳过”标签，不再重复显示原因行。 */
export function symbolSkipSummaryReason(reasonCode: string | null | undefined): string {
  if (!reasonCode || reasonCode === 'COMMON.SYMBOL_SKIPPED') return ''
  return executionReasonText(reasonCode, '未执行')
}
