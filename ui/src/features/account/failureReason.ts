/** 直接回放已有错误；不分类、归责或推荐重试，也不读取事件调试载荷。 */
export interface FailureReason {
  human: string
  raw: string
}
export function describeFailureText(text: string): FailureReason {
  return { human: text, raw: text }
}
