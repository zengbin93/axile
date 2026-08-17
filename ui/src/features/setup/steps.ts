/** 向导步骤定义（路径 + 标签），供步骤栏与导航共用。 */

export interface Step {
  path: string
  label: string
}

export const PF_STEPS: Step[] = [
  { path: '/setup/pf/name', label: '命名' },
  { path: '/setup/pf/define', label: '定义策略' },
  { path: '/setup/pf/done', label: '完成' },
]

export const ACCT_STEPS: Step[] = [
  { path: '/setup/acct/channel', label: '选渠道' },
  { path: '/setup/acct/connect', label: '连接' },
  { path: '/setup/acct/portfolio', label: '绑定组合' },
  { path: '/setup/acct/trade', label: '交易方式' },
  { path: '/setup/acct/timer', label: '定时' },
  { path: '/setup/acct/confirm', label: '确认' },
]

/** 由当前路径推断所属流程与步骤序号。 */
export function flowOf(pathname: string): { flow: 'pf' | 'acct' | null; steps: Step[]; index: number } {
  if (pathname.startsWith('/setup/pf/')) {
    const index = PF_STEPS.findIndex((s) => s.path === pathname)
    return { flow: 'pf', steps: PF_STEPS, index }
  }
  if (pathname.startsWith('/setup/acct/')) {
    const index = ACCT_STEPS.findIndex((s) => s.path === pathname)
    return { flow: 'acct', steps: ACCT_STEPS, index }
  }
  return { flow: null, steps: [], index: -1 }
}
