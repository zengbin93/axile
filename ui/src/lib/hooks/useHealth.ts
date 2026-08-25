import { healthCheck } from '@/lib/api/system'
import { usePolling } from '@/lib/hooks/usePolling'

/** 后端存活状态，供顶栏活性点使用。每 5 秒探测一次。 */
export function useHealth() {
  const { data, error, updatedAt } = usePolling(healthCheck, { queryKey: 'health', intervalMs: 5000 })
  return {
    online: data === true && error == null,
    updatedAt,
  }
}
