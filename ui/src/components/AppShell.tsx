import { useCallback, useState } from 'react'
import { Outlet } from 'react-router'
import { AppSidebar } from '@/components/AppSidebar'
import { TopBar } from '@/components/TopBar'
import { Toast } from '@/components/Toast'

/** 应用外壳：状态带、贴边导航栏与独立滚动工作区——一体化驾驶舱框架。 */
export function AppShell() {
  const [navigationOpen, setNavigationOpen] = useState(false)
  const closeNavigation = useCallback(() => setNavigationOpen(false), [])

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-bg">
      <TopBar onOpenNavigation={() => setNavigationOpen(true)} />
      <div className="flex min-h-0 flex-1">
        <AppSidebar mobileOpen={navigationOpen} onClose={closeNavigation} />
        {/* 内容列在导航栏右侧的余量里居中；不设全局最小宽，窄视口（高 zoom）下
            内容自然收缩，只留纵向滚动。 */}
        <main className="app-workspace h-full min-w-0 flex-1 overflow-y-auto px-4 [scrollbar-gutter:stable] md:px-10">
          <div className="mx-auto h-full w-full max-w-[2176px] pt-5 pb-16">
            <Outlet />
          </div>
        </main>
      </div>
      <Toast />
    </div>
  )
}
