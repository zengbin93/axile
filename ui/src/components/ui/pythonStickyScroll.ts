import type { EditorState } from '@codemirror/state'
import { highlightingFor, syntaxTree } from '@codemirror/language'
import { EditorView, ViewPlugin, type ViewUpdate } from '@codemirror/view'
import { highlightTree } from '@lezer/highlight'

export type PythonScope = { from: number; to: number }
const MAX_ROWS = 5

/** Body nodes exclude strings and distinguish elif/else/except from their preceding branch. */
export function pythonScopes(state: EditorState, position: number): PythonScope[] {
  const scopes: PythonScope[] = []
  const line = state.doc.lineAt(position)
  const probe = Math.min(line.to, Math.max(position, line.from + line.text.search(/\S|$/) + 1))
  for (let node = syntaxTree(state).resolveInner(probe, 1); node; node = node.parent!) {
    if (node.name !== 'Body' || !node.parent) continue
    let header = node.parent.from
    for (let previous = node.prevSibling; previous; previous = previous.prevSibling) {
      if (previous.name === 'Body') {
        header = previous.nextSibling!.from
        break
      }
    }
    const from = state.doc.lineAt(header).from
    const to = Math.max(node.from, node.to - 1)
    if (state.doc.lineAt(to).number > state.doc.lineAt(from).number) scopes.unshift({ from, to })
  }
  return scopes
}

function highlightedLine(view: EditorView, from: number) {
  const line = view.state.doc.lineAt(from)
  const code = document.createElement('span')
  code.className = 'cm-python-sticky-code'
  let position = line.from
  highlightTree(syntaxTree(view.state), { style: tags => highlightingFor(view.state, tags) }, (start, end, classes) => {
    if (start > position) code.append(view.state.sliceDoc(position, start))
    const token = document.createElement('span')
    token.className = classes
    token.textContent = view.state.sliceDoc(start, end)
    code.append(token)
    position = end
  }, line.from, line.to)
  code.append(view.state.sliceDoc(position, line.to))
  return code
}

class StickyScroll {
  readonly dom = document.createElement('div')
  height = 0
  private alive = true
  private rendered = ''
  private readonly schedule = () => this.view.requestMeasure({ key: this, read: () => this.measure(), write: data => this.draw(data) })

  constructor(readonly view: EditorView) {
    this.dom.className = 'cm-python-sticky'
    this.dom.setAttribute('role', 'navigation')
    this.dom.setAttribute('aria-label', '代码作用域')
    this.dom.hidden = true
    this.dom.addEventListener('wheel', event => {
      if (event.ctrlKey) return
      const unit = event.deltaMode === 1 ? view.defaultLineHeight : event.deltaMode === 2 ? view.scrollDOM.clientHeight : 1
      view.scrollDOM.scrollBy({
        top: event.shiftKey ? 0 : event.deltaY * unit,
        left: (event.shiftKey ? event.deltaY : event.deltaX) * unit,
        behavior: 'instant',
      })
      event.preventDefault()
    }, { passive: false })
    view.dom.append(this.dom)
    view.scrollDOM.addEventListener('scroll', this.schedule, { passive: true })
    this.schedule()
  }

  update(update: ViewUpdate) {
    if (update.docChanged || syntaxTree(update.startState) !== syntaxTree(update.state)) this.rendered = ''
    if (update.docChanged || update.viewportChanged || update.geometryChanged || syntaxTree(update.startState) !== syntaxTree(update.state)) this.schedule()
  }

  private measure() {
    const { view } = this
    const scroll = view.scrollDOM.getBoundingClientRect()
    const editor = view.dom.getBoundingClientRect()
    const content = view.contentDOM.getBoundingClientRect()
    const lineHeight = view.defaultLineHeight
    const top = scroll.top - view.documentTop
    const rows: (PythonScope & { offset: number })[] = []
    const limit = Math.min(MAX_ROWS, Math.floor(view.scrollDOM.clientHeight / (lineHeight * 2)))
    for (let index = 0; index < limit; index++) {
      const slot = top + index * lineHeight
      const block = view.lineBlockAtHeight(Math.max(0, slot))
      const scope = pythonScopes(view.state, block.from).find(candidate => !rows.some(row => row.from === candidate.from))
      if (!scope || view.lineBlockAt(scope.from).top >= slot) break
      // A folded body shares a display block with its declaration and must not stick.
      if (view.lineBlockAt(scope.from).from === view.lineBlockAt(scope.to).from) break
      const bottom = view.lineBlockAt(scope.to).bottom
      if (bottom <= slot) break
      rows.push({ ...scope, offset: Math.min(0, bottom - slot - lineHeight) })
    }
    return {
      rows, lineHeight, top: scroll.top - editor.top, left: scroll.left - editor.left,
      width: view.scrollDOM.clientWidth,
      gutter: view.scrollDOM.querySelector('.cm-gutters')?.getBoundingClientRect().width ?? 0,
      codeLeft: content.left - scroll.left + parseFloat(getComputedStyle(view.contentDOM).paddingLeft || '0'),
    }
  }

  private draw(data: ReturnType<StickyScroll['measure']>) {
    if (!this.alive) return
    this.height = data.rows.length * data.lineHeight
    this.dom.hidden = !data.rows.length
    Object.assign(this.dom.style, {
      top: `${data.top}px`, left: `${data.left}px`, width: `${data.width}px`,
    })
    this.dom.style.setProperty('--sticky-line-height', `${data.lineHeight}px`)
    this.dom.style.setProperty('--sticky-gutter', `${data.gutter}px`)
    this.dom.style.setProperty('--sticky-code-offset', `${data.codeLeft - data.gutter}px`)
    const key = data.rows.map(row => row.from).join(',')
    if (key !== this.rendered) {
      this.rendered = key
      this.dom.replaceChildren(...data.rows.map(scope => this.row(scope)))
    }
    data.rows.forEach((row, index) => {
      const button = this.dom.children[index]?.firstElementChild as HTMLElement | null
      if (button) button.style.transform = `translateY(${row.offset}px)`
    })
  }

  private row(scope: PythonScope) {
    const row = document.createElement('div')
    row.className = 'cm-python-sticky-row'
    const button = row.appendChild(document.createElement('button'))
    button.type = 'button'
    const line = this.view.state.doc.lineAt(scope.from)
    button.setAttribute('aria-label', `第 ${line.number} 行：${line.text.trim()}`)
    const number = button.appendChild(document.createElement('span'))
    number.className = 'cm-python-sticky-number'
    number.textContent = String(line.number)
    number.setAttribute('aria-hidden', 'true')
    const clip = button.appendChild(document.createElement('span'))
    clip.className = 'cm-python-sticky-text'
    clip.append(highlightedLine(this.view, scope.from))
    button.addEventListener('click', () => {
      this.view.dispatch({ selection: { anchor: scope.from }, effects: EditorView.scrollIntoView(scope.from, { y: 'start', yMargin: 0 }) })
      this.view.focus()
    })
    return row
  }

  destroy() {
    this.alive = false
    this.view.scrollDOM.removeEventListener('scroll', this.schedule)
    this.dom.remove()
  }
}

const stickyPlugin = ViewPlugin.fromClass(StickyScroll)

export const pythonStickyScroll = [
  stickyPlugin,
  EditorView.scrollMargins.of(view => ({ top: view.plugin(stickyPlugin)?.height ?? 0 })),
  EditorView.theme({
    '.cm-python-sticky': {
      position: 'absolute', zIndex: '5', overflow: 'hidden', backgroundColor: 'var(--color-code-bg)',
      boxShadow: '0 1px 0 var(--color-line)', fontFamily: 'var(--font-mono)', fontSize: 'inherit',
    },
    '.cm-python-sticky[hidden]': { display: 'none' },
    '.cm-python-sticky-row': { height: 'var(--sticky-line-height)', overflow: 'hidden' },
    '.cm-python-sticky-row button': {
      position: 'relative', display: 'block', width: '100%', height: '100%', padding: '0', border: '0',
      font: 'inherit', lineHeight: 'var(--sticky-line-height)', textAlign: 'left', cursor: 'pointer',
      backgroundColor: 'var(--color-code-bg)', color: 'var(--color-code-fg)',
    },
    '.cm-python-sticky-row button:hover': { backgroundColor: 'var(--color-bg-subtle)' },
    '.cm-python-sticky-row button:focus-visible': { outline: '1px solid var(--color-accent)', outlineOffset: '-1px' },
    '.cm-python-sticky-number': {
      position: 'absolute', top: '0', left: '0', width: 'var(--sticky-gutter)', boxSizing: 'border-box',
      paddingRight: '18px', color: 'var(--color-ink-3)', textAlign: 'right',
    },
    '.cm-python-sticky-text': { position: 'absolute', inset: '0 0 0 var(--sticky-gutter)', overflow: 'hidden' },
    '.cm-python-sticky-code': { display: 'block', whiteSpace: 'pre', transform: 'translateX(var(--sticky-code-offset))', tabSize: '4' },
  }),
]
