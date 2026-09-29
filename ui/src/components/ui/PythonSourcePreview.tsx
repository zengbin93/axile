import { useEffect, useMemo, useState, type CSSProperties, type MouseEvent } from 'react'
import CodeMirror from '@uiw/react-codemirror'
import { python } from '@codemirror/lang-python'
import { Compartment } from '@codemirror/state'
import { EditorView, keymap, scrollPastEnd } from '@codemirror/view'
import { jumpToDefinitionKeymap, findReferencesKeymap, type LSPClient } from '@codemirror/lsp-client'
import { pythonEditorTheme } from '@/components/ui/pythonEditorTheme'
import { pythonEditorZoomKeys, usePythonEditorFontSize } from '@/components/ui/pythonEditorFontSize'
import { pythonStickyScroll } from '@/components/ui/pythonStickyScroll'
import { centeredFoldGutter, foldedLineHighlight } from '@/components/ui/pythonEditorReading'
import { readingExtensions } from '@/components/ui/pythonEditorExtensions'
import { pythonDefinitionClick } from '@/components/ui/pythonDefinitionClick'
import { pythonHover } from '@/components/ui/pythonHover'
import { pythonVisualFeatures } from '@/components/ui/pythonLanguageFeatures'
import { documentSymbols, type DocumentSymbols } from '@/components/ui/pythonLanguageService'
import type { PythonEditorKind } from '@/components/ui/pythonEditorContract'

const sourceBasicSetup = { foldGutter: false, highlightActiveLine: false, highlightActiveLineGutter: false, autocompletion: false }

export interface SourceTab {
  uri: string
  code: string
}

/** 外部源码常驻在文件 tab 中，切换时保留滚动位置与选区。 */
export function PythonSourcePreview({ source, client, kind, onCreateEditor, onCursor, onSymbols, onContextMenu }: {
  source: SourceTab
  client: LSPClient | null
  kind: PythonEditorKind
  onCreateEditor: (view: EditorView) => void
  onCursor: (uri: string, line: number, character: number) => void
  onSymbols: (uri: string, symbols: DocumentSymbols | null) => void
  onContextMenu: (event: MouseEvent<HTMLDivElement>, view: EditorView) => void
}) {
  const fontSize = usePythonEditorFontSize()
  const [view, setView] = useState<EditorView | null>(null)
  const languageSlot = useMemo(() => new Compartment(), [])
  const extensions = useMemo(() => [
    pythonEditorTheme, pythonEditorZoomKeys, pythonStickyScroll, scrollPastEnd(), python(),
    centeredFoldGutter, foldedLineHighlight, readingExtensions(), languageSlot.of([]),
    EditorView.updateListener.of((update) => {
      if (!update.selectionSet) return
      const position = update.state.selection.main.head
      const line = update.state.doc.lineAt(position)
      onCursor(source.uri, line.number - 1, position - line.from)
    }),
  ], [languageSlot, onCursor, source.uri])

  useEffect(() => {
    if (!view) return
    view.dispatch({ effects: languageSlot.reconfigure(client ? [
      client.plugin(source.uri, 'python'), pythonVisualFeatures(), pythonHover(kind),
      pythonDefinitionClick, documentSymbols((symbols) => onSymbols(source.uri, symbols)),
      keymap.of([...jumpToDefinitionKeymap, ...findReferencesKeymap]),
    ] : []) })
  }, [view, languageSlot, client, source.uri, kind, onSymbols])

  return (
    <div className="h-full" onContextMenu={(event) => { if (view) onContextMenu(event, view) }}>
      <CodeMirror value={source.code} readOnly theme="none" basicSetup={sourceBasicSetup} extensions={extensions} onCreateEditor={(editor) => { setView(editor); onCreateEditor(editor) }} height="100%" className="h-full [&_.cm-editor]:h-full [&_.cm-editor]:!bg-code-bg [&_.cm-gutters]:!bg-code-bg [&_.cm-scroller]:h-full" style={{ '--python-editor-font-size': `${fontSize}px` } as CSSProperties} />
    </div>
  )
}
