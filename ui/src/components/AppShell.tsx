import { Outlet } from 'react-router'
import { AppSidebar } from '@/components/AppSidebar'
import { TopBar } from '@/components/TopBar'
import { Toast } from '@/components/Toast'

/** 应用外壳：稳定顶栏、悬浮常驻导航与独立滚动工作区。 */
export function AppShell() {
  return (
    <div className="flex h-screen min-w-[1400px] flex-col overflow-hidden bg-bg">
      <TopBar />
      <div className="relative min-h-0 flex-1">
        <AppSidebar />
        <main className="app-workspace h-full overflow-y-auto [scrollbar-gutter:stable]">
          <div className="relative left-24 mx-auto h-full w-full max-w-[860px] px-6 pt-2 pb-16">
            <Outlet />
          </div>
        </main>
      </div>
      <Toast />
    </div>
  )
}
