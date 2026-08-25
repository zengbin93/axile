import { Outlet } from 'react-router'
import { AppSidebar } from '@/components/AppSidebar'
import { TopBar } from '@/components/TopBar'
import { Toast } from '@/components/Toast'

/** 应用外壳：稳定顶栏、悬浮常驻导航与独立滚动工作区。 */
export function AppShell() {
  return (
    <div className="flex h-screen flex-col overflow-hidden bg-bg">
      <TopBar />
      <div className="relative min-h-0 flex-1">
        <AppSidebar />
        {/* 内容列左缘为侧边栏让位（20+224+24），其余空间内居中；不设全局最小宽，
            窄视口（高 zoom）下内容自然收缩，只留纵向滚动。 */}
        <main className="app-workspace h-full overflow-y-auto pr-6 pl-[268px] [scrollbar-gutter:stable]">
          <div className="mx-auto h-full w-full max-w-[860px] pt-2 pb-16">
            <Outlet />
          </div>
        </main>
      </div>
      <Toast />
    </div>
  )
}
