/** 向导步骤定义（路径 + 标签），供步骤栏与导航共用。 */

export interface Step {
  path: string
  label: string
}

export const ACCT_STEPS: Step[] = [
  { path: '/setup/acct/channel', label: '选渠道' },
  { path: '/setup/acct/connect', label: '连接' },
  { path: '/setup/acct/portfolio', label: '绑定组合' },
  { path: '/setup/acct/trade', label: '交易方式' },
  { path: '/setup/acct/timer', label: '定时' },
  { path: '/setup/acct/confirm', label: '确认' },
]

/** 由当前路径推断所属流程与步骤序号。组合新建不走向导（列表页弹层 → 编辑器）。 */
export function flowOf(pathname: string): { flow: 'acct' | null; steps: Step[]; index: number } {
  if (pathname.startsWith('/setup/acct/')) {
    const index = ACCT_STEPS.findIndex((s) => s.path === pathname)
    return { flow: 'acct', steps: ACCT_STEPS, index }
  }
  return { flow: null, steps: [], index: -1 }
}
