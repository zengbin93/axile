import { useEffect } from 'react'
import { useDomainStore } from '@/stores/domain'
import { useLiveExecStore, type RunFrame } from '@/stores/liveExec'

/**
 * 执行实时态 SSE 接线 —— 在应用根挂载一次。
 *
 * 数据方向纯为 server→client，故用 SSE：吃现成 HTTP、原生自动重连。后端无应用级
 * 鉴权（环回明文），`EventSource` 无法设自定义头也不影响；重连后服务端重发 snapshot
 * 帧使 store 自对账。仪表盘轮询作为断线兜底，见 `useLiveExecStore.reconcile`。
 */

const STREAM_PATH = '/api/v1/account/executions/stream'

function parseData<T>(e: Event): T {
  return JSON.parse((e as MessageEvent<string>).data) as T
}

export function useLiveExecSync(): void {
  const applySnapshot = useLiveExecStore((s) => s.applySnapshot)
  const applyEvent = useLiveExecStore((s) => s.applyEvent)
  const reconcile = useLiveExecStore((s) => s.reconcile)

  // 开 SSE 流：连上先收 snapshot（权威全量），随后逐帧 event。原生自动重连。
  useEffect(() => {
    const es = new EventSource(STREAM_PATH)
    es.addEventListener('snapshot', (e) => applySnapshot(parseData<RunFrame[]>(e)))
    es.addEventListener('event', (e) => applyEvent(parseData<RunFrame>(e)))
    return () => es.close()
  }, [applySnapshot, applyEvent])

  // 断线兜底：每次账户轮询刷新后，用最新快照对账运行集。
  const accounts = useDomainStore((s) => s.accounts)
  useEffect(() => {
    if (accounts) reconcile(accounts)
  }, [accounts, reconcile])
}
