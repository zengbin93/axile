import { create } from 'zustand'

interface ToastState {
  /** 当前 toast 文案；null 表示不展示。 */
  message: string | null
  /** 弹出一条轻提示，`ms` 后自动消失。 */
  toast: (message: string, ms?: number) => void
  /** 立即清除。 */
  clear: () => void
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
