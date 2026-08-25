import { useEffect, useState } from 'react'
import { useNavigate } from '@/components/ui/nav'
import { InitWizard } from '@/features/init/InitWizard'
import { initStatus, peekInitValues, type InitValues } from '@/lib/api/init'

/**
 * 系统配置页（常驻应用导航内）。
 *
 * 已配置用户从顶栏齿轮进入，以「编辑」模式复用 :func:`InitWizard`。预填值优先
 * 取启动时已拉取的缓存（:func:`peekInitValues`），从而首帧即渲染向导、与 `/setup`
 * 一样无加载闪屏；仅当缓存缺失（启动探测失败）时才回退到即时拉取。执行告警保存后
 * 立即热生效；高级系统设置仍由后端写入 config.toml 并重启。
 */
export function SystemConfigPage({ section = 'alert' }: { section?: 'alert' | 'advanced' }) {
  const navigate = useNavigate()
  const [values, setValues] = useState<InitValues | null>(() => peekInitValues())

  useEffect(() => {
    if (values) return
    let alive = true
    initStatus()
      .then((s) => {
        if (alive) setValues(s.values)
      })
      .catch(() => {
        // 拉取失败（后端异常）时退回主页，由主应用的错误提示处理。
        if (alive) navigate('/')
      })
    return () => {
      alive = false
    }
  }, [values, navigate])

  if (!values) {
    return (
      <div className="grid h-full place-items-center bg-bg text-ink-3">
        <div className="text-[15px] tracking-wide">读取配置中…</div>
      </div>
    )
  }

  return <InitWizard initial={values} mode="edit" editSection={section} />
}
