import { useEffect, useRef } from 'react'

export interface PythonSaveAction {
  dirty: boolean
  saving: boolean
  error?: Error | null
  blocked?: boolean
  blockedReason?: string
  disabled?: boolean
  onSave: () => void
  onRestore?: () => void
  title?: string
}

/** 页面与编辑器焦点都使用同一个保存动作；按钮和快捷键共用可用条件。 */
export function usePythonSaveShortcut(action?: PythonSaveAction) {
  const actionRef = useRef(action)
  actionRef.current = action
  const enabled = action !== undefined
  useEffect(() => {
    if (!enabled) return
    const onKey = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.altKey || event.shiftKey || event.key.toLowerCase() !== 's') return
      event.preventDefault()
      const current = actionRef.current
      if (current && canSavePython(current)) current.onSave()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [enabled])
}

export function canSavePython(action: PythonSaveAction) {
  return action.dirty && !action.saving && !action.blocked && !action.disabled
}

