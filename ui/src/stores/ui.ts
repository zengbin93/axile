import { create } from 'zustand'

interface ToastState {
  /** 当前 toast 文案；null 表示不展示。 */
  message: string | null
  /** 弹出一条轻提示，`ms` 后自动消失。 */
  toast: (message: string, ms?: number) => void
  /** 立即清除。 */
  clear: () => void
}

interface NavigationState {
  /** 全局页面没有账户 ID 时，侧栏仍保留用户最近选择的账户。 */
  activeAccountId: number | null
  setActiveAccountId: (accountId: number | null) => void
  /** 侧栏是否因可用高度不足进入紧凑布局。 */
  sidebarCompact: boolean
  setSidebarCompact: (compact: boolean) => void
}

let timer: ReturnType<typeof setTimeout> | undefined

/** 全局轻提示（toast）。跨页面共用，故放 store 而非局部状态。 */
export const useToastStore = create<ToastState>((set) => ({
  message: null,
  toast: (message, ms = 2800) => {
    if (timer) clearTimeout(timer)
    set({ message })
    timer = setTimeout(() => set({ message: null }), ms)
  },
  clear: () => {
    if (timer) clearTimeout(timer)
    set({ message: null })
  },
}))

/** 常驻导航的账户上下文；路由中的账户 ID 始终拥有更高优先级。 */
export const useNavigationStore = create<NavigationState>((set) => ({
  activeAccountId: null,
  setActiveAccountId: (activeAccountId) => set({ activeAccountId }),
  sidebarCompact: false,
  setSidebarCompact: (sidebarCompact) => set({ sidebarCompact }),
}))
