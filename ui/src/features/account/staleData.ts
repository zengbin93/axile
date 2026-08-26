import { isConnectionError } from '@/lib/errorInfo'

export interface QueryFreshness {
  error: Error | null
  stale: boolean
  updatedAt: number | null
}

/** 网络级失联时，已有缓存的查询退为新鲜度提示，不再重复完整错误。 */
export function connectionStaleAt(connectionUnavailable: boolean, queries: QueryFreshness[]): number | null {
  if (!connectionUnavailable) return null
  const timestamps = queries.flatMap((query) => (
    query.stale && query.updatedAt != null && isConnectionError(query.error) ? [query.updatedAt] : []
  ))
  return timestamps.length > 0 ? Math.min(...timestamps) : null
}

/** 保留首次加载和独立接口错误，只隐藏已经由全局失联状态解释的缓存刷新错误。 */
export function localQueryError(connectionUnavailable: boolean, query: QueryFreshness): Error | null {
  return connectionStaleAt(connectionUnavailable, [query]) == null ? query.error : null
}
