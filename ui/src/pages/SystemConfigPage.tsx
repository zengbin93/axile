import { useEffect, useState } from 'react'
import { useNavigate } from '@/components/ui/nav'
import { SystemAlertPage } from '@/pages/SystemAlertPage'
import { InitWizard } from '@/features/init/InitWizard'
import { initStatus, initValuesFromStatus, peekInitValues, type InitValues } from '@/lib/api/init'

/** 告警使用独立配置页；高级系统设置沿用需要重启的配置向导。 */
export function SystemConfigPage({ section = 'alert' }: { section?: 'alert' | 'advanced' }) {
  return section === 'alert' ? <SystemAlertPage /> : <AdvancedSystemConfigPage />
}

function AdvancedSystemConfigPage() {
  const navigate = useNavigate()
  const [values, setValues] = useState<InitValues | null>(() => peekInitValues())

  useEffect(() => {
    if (values) return
    let alive = true
    initStatus()
      .then((s) => {
        if (alive) setValues(initValuesFromStatus(s.values))
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
        <div className="text-[16px] tracking-wide">读取配置中…</div>
      </div>
    )
  }

  return <InitWizard initial={values} mode="edit" editSection="advanced" />
}
