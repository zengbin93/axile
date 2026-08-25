import { ApiError } from '@/lib/api/client'

export interface ErrorEvidence {
  label: string
  value: string
}

export interface ErrorInfo {
  message: string
  evidence: ErrorEvidence[]
}

const SECRET_ASSIGNMENT = /\b(password|passwd|secret|token|api[_-]?key|access[_-]?key)\b\s*[:=]\s*([^\s,;]+)/gi
const URL_SECRET = /([?&](?:password|secret|token|api[_-]?key|access[_-]?key)=)[^&#\s]+/gi

/** 对可见错误做保守脱敏；结构化请求体从 API 边界起就不会进入此函数。 */
export function redactErrorText(value: string): string {
  return value
    .replace(SECRET_ASSIGNMENT, '$1=[已隐藏]')
    .replace(URL_SECRET, '$1[已隐藏]')
}

export function shortErrorReason(error: unknown, maxLength = 160): string {
  const raw = error instanceof Error ? error.message : String(error ?? '')
  const normalized = redactErrorText(raw).replace(/\s+/g, ' ').trim()
  const message = normalized === 'Failed to fetch'
    ? '无法连接 axile 服务'
    : normalized || '未知错误'
  return message.length <= maxLength ? message : `${message.slice(0, maxLength - 1)}…`
}

export function errorInfo(error: unknown): ErrorInfo {
  const evidence: ErrorEvidence[] = []
  if (error instanceof ApiError) {
    evidence.push({ label: 'HTTP', value: String(error.status) })
    if (error.code) evidence.push({ label: '错误码', value: error.code })
    if (error.requestId) evidence.push({ label: '请求标识', value: error.requestId })
  }
  return { message: shortErrorReason(error), evidence }
}
