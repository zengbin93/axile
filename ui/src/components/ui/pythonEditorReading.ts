import { foldable, foldGutter, foldedRanges, foldState } from '@codemirror/language'
import { Decoration, EditorView, ViewPlugin, type ViewUpdate } from '@codemirror/view'

const foldedLine = Decoration.line({ class: 'cm-python-foldedLine' })
export const foldedLineHighlight = EditorView.decorations.compute([foldState], (state) => {
  const lines = new Set<number>()
  foldedRanges(state).between(0, state.doc.length, (from) => { lines.add(state.doc.lineAt(from).from) })
  return Decoration.set([...lines].sort((a, b) => a - b).map((from) => foldedLine.range(from)))
})
const foldGutterHover = ViewPlugin.fromClass(class {
  private source = -1
  private revealed: Element[] = []

  constructor(readonly view: EditorView) {
    view.dom.addEventListener('pointermove', this.onPointerMove)
    view.dom.addEventListener('pointerleave', this.clear)
  }

  private clear = () => {
    for (const element of this.revealed) element.classList.remove('cm-python-revealedFoldLine')
    this.revealed = []
    this.source = -1
  }

  private onPointerMove = (event: PointerEvent) => {
    const gutter = this.view.dom.querySelector('.cm-foldGutter')
    if (!gutter?.contains(event.target as Node)) { this.clear(); return }

    const block = this.view.lineBlockAtHeight(event.clientY - this.view.documentTop)
    if (block.from === this.source) return
    this.clear()
    let scopeFrom = block.from
    let range = foldable(this.view.state, block.from, block.to)
    for (const line of this.view.viewportLineBlocks) {
      if (line.from >= scopeFrom) continue
      const candidate = foldable(this.view.state, line.from, line.to)
      if (candidate && candidate.to > block.from) { scopeFrom = line.from; range = candidate }
    }
    if (!range) return
    this.source = block.from

    for (const element of gutter.querySelectorAll('.cm-gutterElement')) {
      const bounds = element.getBoundingClientRect()
      if (!bounds.height) continue
      const line = this.view.lineBlockAtHeight((bounds.top + bounds.bottom) / 2 - this.view.documentTop)
      if (line.from !== scopeFrom && (line.from <= scopeFrom || line.from >= range.to)) continue
      element.classList.add('cm-python-revealedFoldLine')
      this.revealed.push(element)
    }
  }

  update(update: ViewUpdate) {
    if (update.docChanged || update.viewportChanged || update.heightChanged) this.clear()
  }

  destroy() {
    this.view.dom.removeEventListener('pointermove', this.onPointerMove)
    this.view.dom.removeEventListener('pointerleave', this.clear)
    this.clear()
  }
})
export const centeredFoldGutter = [
  foldGutter({
    markerDOM: (open) => {
      const marker = document.createElement('span')
      marker.title = open ? '折叠代码' : '展开代码'
      if (!open) marker.className = 'cm-python-foldedMarker'
      const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
      icon.setAttribute('viewBox', '0 0 16 16')
      icon.setAttribute('width', '14')
      icon.setAttribute('height', '14')
      icon.setAttribute('aria-hidden', 'true')
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path')
      path.setAttribute('d', open ? 'm4 6 4 4 4-4' : 'm6 4 4 4-4 4')
      path.setAttribute('fill', 'none')
      path.setAttribute('stroke', 'currentColor')
      path.setAttribute('stroke-width', '1.5')
      path.setAttribute('stroke-linecap', 'round')
      path.setAttribute('stroke-linejoin', 'round')
      icon.append(path)
      marker.append(icon)
      return marker
    },
  }),
  EditorView.theme({
    '.cm-foldGutter .cm-gutterElement': { display: 'flex', alignItems: 'center', justifyContent: 'center', minWidth: '18px' },
    '.cm-foldGutter .cm-gutterElement span': { display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '0' },
    '.cm-foldGutter .cm-gutterElement span:not(.cm-python-foldedMarker)': {
      opacity: '0', transition: 'opacity 140ms cubic-bezier(.4, 0, .2, 1)',
    },
    '.cm-foldGutter .cm-gutterElement.cm-python-revealedFoldLine span:not(.cm-python-foldedMarker)': {
      opacity: '1', transitionDuration: '180ms',
    },
    '.cm-foldGutter .cm-python-foldedMarker': { color: 'var(--color-code-fg)' },
    '@media (hover: none)': {
      '.cm-foldGutter .cm-gutterElement span:not(.cm-python-foldedMarker)': { opacity: '1' },
    },
    '@media (prefers-reduced-motion: reduce)': {
      '.cm-foldGutter .cm-gutterElement span:not(.cm-python-foldedMarker)': { transition: 'none' },
    },
  }),
  foldGutterHover,
]
