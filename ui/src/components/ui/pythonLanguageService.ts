import { Compartment, Text } from '@codemirror/state'
import { EditorView, ViewPlugin, keymap, showDialog, type ViewUpdate } from '@codemirror/view'
import { linter, forceLinting, type Diagnostic } from '@codemirror/lint'
import { LSPClient, LSPPlugin, serverCompletion, signatureHelp, jumpToDefinitionKeymap, findReferencesKeymap, type WorkspaceFile } from '@codemirror/lsp-client'
import DOMPurify from 'dompurify'
import { pythonHover } from '@/components/ui/pythonHover'
import { apiGet } from '@/lib/api/client'
import { pythonVisualFeatures, quickFix, renamePythonSymbol } from '@/components/ui/pythonLanguageFeatures'
import type { DocumentSymbol, SymbolInformation } from 'vscode-languageserver-protocol'

export type LanguageStatus = 'connecting' | 'ready' | 'reconnecting'
export type DocumentSymbols = DocumentSymbol[] | SymbolInformation[]
type LspDiagnostic = {
  range: { start: { line: number; character: number }; end: { line: number; character: number } }
  severity?: number
  message: string
}

/** 重连时只替换语言扩展，保留编辑文档、选择和撤销栈。 */
export function connectPython(
  view: EditorView,
  slot: Compartment,
  onStatus: (status: LanguageStatus) => void,
  displaySource: (uri: string, code: string) => Promise<EditorView | null>,
  onSymbols?: (symbols: DocumentSymbols | null, doc: Text) => void,
) {
  let disposed = false
  let socket: WebSocket | null = null
  let client: LSPClient | null = null
  let timer: ReturnType<typeof setTimeout> | undefined
  let watchdog: ReturnType<typeof setTimeout> | undefined
  let failures = 0

  const connect = () => {
    if (disposed) return
    onStatus(failures ? 'reconnecting' : 'connecting')
    const url = new URL('/api/v1/editor/lsp', window.location.href)
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(url)
    socket = ws
    const handlers = new Set<(message: string) => void>()
    watchdog = setTimeout(() => ws.close(), 15000)
    ws.onmessage = (event) => {
      if (disposed) return
      const message = JSON.parse(String(event.data))
      if (message.type !== 'session') {
        handlers.forEach((handler) => handler(String(event.data)))
        return
      }
      const active = new LSPClient({
        rootUri: message.rootUri,
        timeout: 10000,
        sanitizeHTML: (html) => DOMPurify.sanitize(html),
        extensions: [serverCompletion(), signatureHelp(), {
          clientCapabilities: { textDocument: {
            codeAction: { codeActionLiteralSupport: { codeActionKind: { valueSet: ['quickfix'] } }, resolveSupport: { properties: ['edit'] } },
            semanticTokens: { requests: { full: true }, tokenTypes: ['namespace', 'class', 'type', 'function', 'method', 'variable', 'parameter', 'property', 'keyword', 'string', 'number', 'comment', 'decorator'], tokenModifiers: [], formats: ['relative'] },
            inlayHint: {}, foldingRange: { lineFoldingOnly: false }, documentSymbol: { hierarchicalDocumentSymbolSupport: true },
          } },
        }],
      })
      client = active
      const workspace = active.workspace
      const sources = new Map<string, WorkspaceFile>()
      workspace.requestFile = async (uri) => {
        const existing = workspace.getFile(uri) ?? sources.get(uri)
        if (existing) return existing
        const { code } = await apiGet<{ code: string }>(`/editor/source?uri=${encodeURIComponent(uri)}`)
        const file: WorkspaceFile = { uri, languageId: 'python', version: 0, doc: Text.of(code.split('\n')), getView: () => null }
        sources.set(uri, file)
        return file
      }
      workspace.displayFile = async (uri) => {
        try {
          const own = workspace.getFile(uri)?.getView()
          if (own) return own
          const file = await workspace.requestFile(uri)
          return file && !disposed ? displaySource(uri, file.doc.toString()) : null
        } catch (error) {
          if (!disposed) showDialog(view, { label: error instanceof Error ? error.message : '无法打开源码预览' })
          return null
        }
      }
      active.connect({
        send: (value) => {
          if (ws.readyState !== WebSocket.OPEN) throw new Error('语言服务已断开')
          ws.send(value)
        },
        subscribe: (handler) => { handlers.add(handler) },
        unsubscribe: (handler) => { handlers.delete(handler) },
      })
      void active.initializing.then(() => {
        if (disposed || socket !== ws || ws.readyState !== WebSocket.OPEN) return
        clearTimeout(watchdog)
        failures = 0
        view.dispatch({ effects: slot.reconfigure([
          active.plugin(message.uri, 'python'),
          pythonVisualFeatures(),
          pythonHover(),
          ...(onSymbols ? [documentSymbols(onSymbols)] : []),
          keymap.of([...jumpToDefinitionKeymap, ...findReferencesKeymap,
            { key: 'F2', run: renamePythonSymbol }, { key: 'Mod-.', run: quickFix }]),
          linter(async (editor): Promise<Diagnostic[]> => {
            const plugin = LSPPlugin.get(editor)
            if (!plugin || !active.connected) return []
            const doc = editor.state.doc
            try {
              active.sync()
              const report = await active.request<object, { items?: LspDiagnostic[] }>(
                'textDocument/diagnostic', { textDocument: { uri: message.uri } },
              )
              if (editor.state.doc !== doc || !active.connected) return []
              return (report.items ?? []).map((item) => ({
                from: plugin.fromPosition(item.range.start, doc),
                to: plugin.fromPosition(item.range.end, doc),
                severity: item.severity === 1 ? 'error' : item.severity === 2 ? 'warning' : 'info',
                message: item.message,
                source: 'ty',
              }))
            } catch {
              return []
            }
          }, { delay: 350 }),
        ]) })
        forceLinting(view)
        onStatus('ready')
      }).catch(() => ws.close())
    }
    ws.onerror = () => ws.close()
    ws.onclose = () => {
      clearTimeout(watchdog)
      client?.disconnect()
      client = null
      if (disposed) return
      view.dispatch({ effects: slot.reconfigure([]) })
      forceLinting(view)
      onStatus('reconnecting')
      timer = setTimeout(connect, Math.min(1000 * 2 ** failures++, 15000))
    }
  }
  connect()
  return () => {
    disposed = true
    clearTimeout(timer)
    clearTimeout(watchdog)
    client?.disconnect()
    socket?.close()
  }
}

/** 文档版本与插件身份共同约束响应，编辑后立即清除旧的可点击位置。 */
function documentSymbols(onSymbols: (symbols: DocumentSymbols | null, doc: Text) => void) {
  return ViewPlugin.fromClass(class {
    timer: ReturnType<typeof setTimeout> | undefined
    sequence = 0
    alive = true
    constructor(readonly view: EditorView) { this.schedule(0) }
    update(update: ViewUpdate) {
      if (update.docChanged) {
        this.sequence++
        onSymbols(null, update.state.doc)
        this.schedule(450)
      }
    }
    schedule(delay: number) {
      clearTimeout(this.timer)
      this.timer = setTimeout(() => void this.refresh(), delay)
    }
    async refresh() {
      const plugin = LSPPlugin.get(this.view)
      const doc = this.view.state.doc
      const sequence = ++this.sequence
      if (!plugin?.client.connected || !plugin.client.serverCapabilities?.documentSymbolProvider) {
        onSymbols(null, doc)
        return
      }
      try {
        plugin.client.sync()
        const symbols = await plugin.client.request<object, DocumentSymbols | null>('textDocument/documentSymbol', { textDocument: { uri: plugin.uri } })
        if (this.alive && this.sequence === sequence && this.view.state.doc === doc && LSPPlugin.get(this.view) === plugin && plugin.client.connected) onSymbols(symbols ?? [], doc)
      } catch {
        if (this.alive && this.sequence === sequence && this.view.state.doc === doc) onSymbols(null, doc)
      }
    }
    destroy() { this.alive = false; this.sequence++; clearTimeout(this.timer); onSymbols(null, this.view.state.doc) }
  })
}
