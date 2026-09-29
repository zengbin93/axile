import { Decoration, EditorView, ViewPlugin, type DecorationSet, type ViewUpdate } from '@codemirror/view'
import { LSPPlugin, jumpToDefinition } from '@codemirror/lsp-client'
import type { Location, LocationLink } from 'vscode-languageserver-protocol'
import { isMac } from '@/components/ui/pythonEditorExtensions'

const link = Decoration.mark({ class: 'cm-python-definitionLink' })
const linkTheme = EditorView.theme({
  '.cm-python-definitionLink': { textDecoration: 'underline', textUnderlineOffset: '3px', cursor: 'pointer' },
})

function modifier(event: MouseEvent | KeyboardEvent) {
  return isMac() ? event.metaKey && !event.ctrlKey : event.ctrlKey && !event.metaKey
}

/** 仅在语言服务确认有定义时，把修饰键下的符号显示为可点击链接。 */
export const pythonDefinitionClick = [linkTheme, ViewPlugin.fromClass(class {
  decorations: DecorationSet = Decoration.none
  private hovering = false
  private point: { x: number; y: number } | null = null
  private timer: ReturnType<typeof setTimeout> | undefined
  private sequence = 0
  private range: { from: number; to: number } | null = null

  constructor(readonly view: EditorView) {
    view.dom.addEventListener('mousemove', this.onMove)
    view.dom.addEventListener('mouseleave', this.clear)
    view.dom.addEventListener('click', this.onClick)
    window.addEventListener('keydown', this.onKey)
    window.addEventListener('keyup', this.onKey)
    window.addEventListener('blur', this.clear)
  }

  private clear = () => {
    this.sequence++
    clearTimeout(this.timer)
    const hadLink = this.range !== null
    this.range = null
    this.decorations = Decoration.none
    if (hadLink) queueMicrotask(() => this.view.dispatch({}))
  }

  private onMove = (event: MouseEvent) => {
    this.hovering = true
    this.point = { x: event.clientX, y: event.clientY }
    if (!modifier(event) || event.altKey || event.shiftKey || event.buttons) { this.clear(); return }
    this.schedule()
  }

  private onKey = (event: KeyboardEvent) => {
    if (!this.hovering || !this.point) return
    if (!modifier(event) || event.altKey || event.shiftKey) { this.clear(); return }
    this.schedule()
  }

  private schedule() {
    clearTimeout(this.timer)
    const point = this.point
    const pos = point && this.view.posAtCoords(point)
    const word = pos == null ? null : this.view.state.wordAt(pos)
    const plugin = LSPPlugin.get(this.view)
    if (!word || !plugin?.client.connected || !plugin.client.serverCapabilities?.definitionProvider) { this.clear(); return }
    if (this.range?.from === word.from && this.range.to === word.to) return
    this.range = null
    this.decorations = Decoration.none
    const sequence = ++this.sequence
    const doc = this.view.state.doc
    this.timer = setTimeout(async () => {
      try {
        plugin.client.sync()
        const result = await plugin.client.request<object, Location | LocationLink | (Location | LocationLink)[] | null>(
          'textDocument/definition', { textDocument: { uri: plugin.uri }, position: plugin.toPosition(word.from + 1) },
        )
        if (sequence !== this.sequence || this.view.state.doc !== doc || LSPPlugin.get(this.view) !== plugin || !result || Array.isArray(result) && !result.length) return
        this.range = word
        this.decorations = Decoration.set([link.range(word.from, word.to)])
        this.view.dispatch({})
      } catch { /* 断线或无定义时保持普通文本。 */ }
    }, 120)
  }

  private onClick = (event: MouseEvent) => {
    if (event.button !== 0 || !modifier(event) || event.altKey || event.shiftKey || !this.range) return
    const pos = this.view.posAtCoords({ x: event.clientX, y: event.clientY })
    if (pos == null || pos < this.range.from || pos > this.range.to) return
    event.preventDefault()
    this.view.dispatch({ selection: { anchor: pos } })
    jumpToDefinition(this.view)
    this.clear()
  }

  update(update: ViewUpdate) {
    if (update.docChanged || !LSPPlugin.get(this.view)?.client.connected) this.clear()
  }

  destroy() {
    this.clear()
    this.view.dom.removeEventListener('mousemove', this.onMove)
    this.view.dom.removeEventListener('mouseleave', this.clear)
    this.view.dom.removeEventListener('click', this.onClick)
    window.removeEventListener('keydown', this.onKey)
    window.removeEventListener('keyup', this.onKey)
    window.removeEventListener('blur', this.clear)
  }
}, { decorations: value => value.decorations })]
