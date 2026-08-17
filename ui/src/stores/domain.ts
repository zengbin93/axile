import { useEffect } from 'react'
import { create } from 'zustand'
import { getDashboard } from '@/lib/api/accounts'
import { getPortfolios } from '@/lib/api/portfolios'
import type { AccountDashboardItem, PortfolioLite } from '@/types/api'

/**
 * 领域状态 store —— 有界、聚合、被多视图反复看的名词（账户、组合）。
 *
 * 第一性原理：仪表盘 / 账户详情 / 回看 / 组合详情都是同一份状态的不同投影，
 * 不该各自冷拉。这里持有一份共享、活的领域模型：单一来源、单一 poller，
 * 页面从 store 读它要的实体——导航即时、跨视图一致、写操作一处更新处处生效。
 *
 * 无界 / 视图专属的数据（某次执行的 events、回看的 500 条记录、组合详情的
 * 策略配置）仍按需拉，不进本 store。
 */
interface DomainState {
  /** 全部账户（来自 /account/dashboard）；null=尚未首次加载。 */
  accounts: AccountDashboardItem[] | null
  /** 组合列表（来自 /portfolio/）；null=尚未首次加载。 */
  portfolios: PortfolioLite[] | null
  /** 账户数据最近一次成功刷新的时间戳（ms），供顶栏「数据 N 秒前」。 */
  accountsUpdatedAt: number | null
  /** 账户数据最近一次刷新的错误；有值即视为「失联」，但保留旧数据降级展示。 */
  accountsError: Error | null
  refreshAccounts: () => Promise<void>
  refreshPortfolios: () => Promise<void>
}

// 在途请求：新的刷新到来时中止旧的，最后一次成功者为准。
let accountsCtrl: AbortController | null = null
let portfoliosCtrl: AbortController | null = null

export const useDomainStore = create<DomainState>((set) => ({
  accounts: null,
  portfolios: null,
  accountsUpdatedAt: null,
  accountsError: null,

  refreshAccounts: async () => {
    accountsCtrl?.abort()
    const ctrl = new AbortController()
    accountsCtrl = ctrl
    try {
      const res = await getDashboard(ctrl.signal)
      if (ctrl.signal.aborted) return
      set({ accounts: res.data, accountsUpdatedAt: Date.now(), accountsError: null })
    } catch (e) {
      if (ctrl.signal.aborted) return
      // 保留上次的 accounts（SWR 降级），只标记错误。
      set({ accountsError: e instanceof Error ? e : new Error(String(e)) })
    }
  },

  refreshPortfolios: async () => {
    portfoliosCtrl?.abort()
    const ctrl = new AbortController()
    portfoliosCtrl = ctrl
    try {
      const res = await getPortfolios(ctrl.signal)
      if (ctrl.signal.aborted) return
      set({ portfolios: res.data })
    } catch {
      // 保留旧值，静默。
    }
  },
}))

/**
 * 在应用根挂载一次，驱动共享领域状态的刷新。
 *
 * 账户（活数据）按间隔轮询；组合列表变动稀疏（仅建/改/删时），首屏拉一次、
 * 之后由写操作显式 refresh。
 */
export function useDomainSync(accountIntervalMs = 5000) {
  const refreshAccounts = useDomainStore((s) => s.refreshAccounts)
  const refreshPortfolios = useDomainStore((s) => s.refreshPortfolios)
  useEffect(() => {
    void refreshAccounts()
    void refreshPortfolios()
    const t = setInterval(() => void refreshAccounts(), accountIntervalMs)
    return () => clearInterval(t)
  }, [refreshAccounts, refreshPortfolios, accountIntervalMs])
}
