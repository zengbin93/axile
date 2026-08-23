/**
 * 薄 API 客户端 —— 统一 baseURL、鉴权头与错误归一。
 *
 * 后端绑定 loopback、无应用级鉴权；仅当设置了 `x-api-password` 时附带。
 * dev 下 `/api` 由 Vite 代理到 127.0.0.1:8000（见 vite.config.ts）。
 */

const BASE = '/api/v1'

/** 可选的 API 口令；生产由部署方注入，dev 一般为空。 */
const API_PASSWORD = import.meta.env.VITE_API_PASSWORD as string | undefined

/** API 调用失败时抛出的统一错误，携带 HTTP 状态码。 */
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

function headers(extra?: HeadersInit): HeadersInit {
  const h: Record<string, string> = { 'Content-Type': 'application/json' }
  if (API_PASSWORD) h['x-api-password'] = API_PASSWORD
  return { ...h, ...(extra as Record<string, string>) }
}

async function parse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = (await res.json()) as { detail?: string }
      if (body?.detail) detail = body.detail
    } catch {
      // 非 JSON 响应，沿用 statusText
    }
    throw new ApiError(res.status, detail)
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
