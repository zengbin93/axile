import { useSyncExternalStore } from 'react'
import { EditorView } from '@codemirror/view'

const storageKey = 'axon:python-editor-font-size'
const defaultSize = 14
const minSize = 10
const maxSize = 24
const listeners = new Set<() => void>()

function savedSize(): number {
  try {
    const value = Number(window.localStorage.getItem(storageKey))
    return Number.isInteger(value) && value >= minSize && value <= maxSize ? value : defaultSize
  } catch {
    return defaultSize
  }
}

let fontSize = typeof window === 'undefined' ? defaultSize : savedSize()

function setFontSize(value: number) {
  const next = Math.min(maxSize, Math.max(minSize, value))
  if (next === fontSize) return
  fontSize = next
  try { window.localStorage.setItem(storageKey, String(next)) } catch { /* 仍在当前页面生效。 */ }
  listeners.forEach((listener) => listener())
}

export function usePythonEditorFontSize(): number {
  return useSyncExternalStore(
    (listener) => { listeners.add(listener); return () => listeners.delete(listener) },
    () => fontSize,
    () => defaultSize,
  )
}

/** 仅编辑器接到缩放快捷键时覆盖浏览器缩放。 */
export const pythonEditorZoomKeys = EditorView.domEventHandlers({
  keydown(event) {
    if (!(event.ctrlKey || event.metaKey) || event.altKey) return false
    if (event.key === '+' || event.key === '=') setFontSize(fontSize + 1)
    else if (event.key === '-') setFontSize(fontSize - 1)
    else if (event.key === '0') setFontSize(defaultSize)
    else return false
    event.preventDefault()
    return true
  },
})
