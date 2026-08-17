import { Outlet } from 'react-router'
import { TopBar } from '@/components/TopBar'
import { Toast } from '@/components/Toast'

/** 应用外壳：顶栏 + 路由出口 + 全局 toast。所有页面共用。 */
export function AppShell() {
  return (
    <div className="flex min-h-full flex-col">
      <TopBar />
      <main className="mx-auto w-full max-w-[860px] flex-1 px-6 pt-8 pb-16">
        <Outlet />
      </main>
      <Toast />
    </div>
  )
}
