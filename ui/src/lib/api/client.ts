/**
 * 薄 API 客户端 —— 统一 baseURL、鉴权头与错误归一。
 *
 * 后端绑定 loopback、无应用级鉴权；仅当设置了 `x-api-password` 时附带。
 * dev 下 `/api` 由 Vite 代理到 127.0.0.1:1419（见 vite.config.ts）。
 */

const BASE = '/api/v1'

/** 可选的 API 口令；生产由部署方注入，dev 一般为空。 */
const API_PASSWORD = import.meta.env.VITE_API_PASSWORD as string | undefined

/** API 调用失败时抛出的统一错误，仅保留可安全展示的诊断标识。 */
export class ApiError extends Error {
  status: number
  code: string | null
  requestId: string | null

  constructor(status: number, message: string, options: { code?: string | null; requestId?: string | null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = options.code ?? null
    this.requestId = options.requestId ?? null
  }
}

type ErrorBody = {
  detail?: unknown
  message?: unknown
  code?: unknown
  request_id?: unknown
}

/** FastAPI 校验错误只取字段路径与消息，刻意丢弃可能含密钥的 input/body。 */
function validationMessage(detail: unknown): string | null {
  if (!Array.isArray(detail)) return null
  const issue = detail[0]
  if (!issue || typeof issue !== 'object') return null
  const { loc, msg } = issue as { loc?: unknown; msg?: unknown }
  if (typeof msg !== 'string') return null
  const path = Array.isArray(loc)
    ? loc.filter((part) => part !== 'body').map(String).join('.')
    : ''
  return path ? `${path}：${msg}` : msg
}

export function apiErrorFromBody(status: number, statusText: string, body: unknown): ApiError {
  const payload = body && typeof body === 'object' ? body as ErrorBody : {}
  const message = typeof payload.message === 'string'
    ? payload.message
    : typeof payload.detail === 'string'
      ? payload.detail
      : (validationMessage(payload.detail) ?? statusText) || `HTTP ${status}`
  return new ApiError(status, message, {
    code: typeof payload.code === 'string' ? payload.code : null,
    requestId: typeof payload.request_id === 'string' ? payload.request_id : null,
  })
}

function headers(extra?: HeadersInit): HeadersInit {
  const h: Record<string, string> = { 'Content-Type': 'application/json' }
  if (API_PASSWORD) h['x-api-password'] = API_PASSWORD
  return { ...h, ...(extra as Record<string, string>) }
}

async function parse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let body: unknown = null
    try {
      body = await res.json()
    } catch {
      // 非 JSON 响应沿用 HTTP 状态，不把响应正文直接暴露给 UI。
    }
    throw apiErrorFromBody(res.status, res.statusText, body)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

/** 发起 GET 请求。`signal` 用于配合轮询取消。 */
export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(BASE + path, { headers: headers(), signal })
  return parse<T>(res)
}

/** 发起带 JSON body 的写请求（POST/PATCH/DELETE）。 */
export async function apiSend<T>(
  method: 'POST' | 'PUT' | 'PATCH' | 'DELETE',
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const res = await fetch(BASE + path, {
    method,
    headers: headers(),
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  })
  return parse<T>(res)
}

/** 上传 multipart 文件；浏览器负责生成 Content-Type boundary。 */
export async function apiUpload<T>(path: string, file: File): Promise<T> {
  const body = new FormData()
  body.append('file', file)
  const uploadHeaders: Record<string, string> = {}
  if (API_PASSWORD) uploadHeaders['x-api-password'] = API_PASSWORD
  const res = await fetch(BASE + path, { method: 'POST', headers: uploadHeaders, body })
  return parse<T>(res)
}
