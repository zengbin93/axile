import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import CodeMirror from '@uiw/react-codemirror'
import { python } from '@codemirror/lang-python'
import { EditorView } from '@codemirror/view'
import { pythonEditorTheme } from '@/components/ui/pythonEditorTheme'

const sourceExtensions = [python(), pythonEditorTheme]

export interface SourcePreview {
  uri: string
  code: string
  resolve: (view: EditorView | null) => void
}

/** 定义与引用的依赖源码只读预览；原草稿及撤销栈始终留在原编辑器。 */
export function PythonSourcePreview({ source, onClose }: { source: SourcePreview; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    dialog.current?.showModal()
    return () => source.resolve(null)
  }, [source])
  return createPortal(
    <dialog ref={dialog} onCancel={(event) => { event.preventDefault(); onClose() }} onClose={onClose} className="m-auto h-[80vh] w-[90vw] max-w-6xl rounded-lg border border-line bg-code-bg p-0 text-ink-1 backdrop:bg-scrim" aria-label="只读源码预览">
      <div className="flex h-full flex-col">
        <header className="flex flex-none items-center gap-3 border-b border-line bg-surface px-4 py-3">
          <span className="min-w-0 flex-1 break-all text-[12px]">{decodeURIComponent(source.uri)} · 只读</span>
          <button type="button" onClick={onClose}>关闭 · Esc</button>
        </header>
        <CodeMirror value={source.code} readOnly editable={false} theme="none" extensions={sourceExtensions} onCreateEditor={source.resolve} height="100%" className="min-h-0 flex-1 overflow-auto" />
      </div>
    </dialog>, document.body,
  )
}
