import { activateHover, closeHoverTooltips, EditorView, hoverTooltip, keymap, repositionTooltips } from '@codemirror/view'
import { LSPPlugin } from '@codemirror/lsp-client'
import type { Hover, MarkedString } from 'vscode-languageserver-protocol'

/** Keep the user's reading size for this page, without persisting document content. */
let readingSize: { width: number; height: number } | undefined

function renderMarked(plugin: LSPPlugin, value: MarkedString): string {
  if (typeof value === 'string') return plugin.docToHTML(value, 'markdown')
  // A fence longer than any run in the source preserves embedded backticks.
  const fence = '`'.repeat(Math.max(3, ...Array.from(value.value.matchAll(/`+/g), m => m[0].length + 1)))
  return plugin.docToHTML(`${fence}${value.language.replace(/[^\w+-]/g, '')}\n${value.value}\n${fence}`, 'markdown')
}

export function pythonHover() {
  let focusNext = false
  const hover = hoverTooltip(async (view, pos) => {
    const focus = focusNext
    focusNext = false
    const plugin = LSPPlugin.get(view)
    if (!plugin?.client.connected || plugin.client.serverCapabilities?.hoverProvider === false) return null
    const doc = view.state.doc
    plugin.client.sync()
    try {
      const result = await plugin.client.request<object, Hover | null>('textDocument/hover', {
        textDocument: { uri: plugin.uri }, position: plugin.toPosition(pos),
      })
      if (!result || view.state.doc !== doc || LSPPlugin.get(view) !== plugin) return null
      const contents = result.contents
      const html = Array.isArray(contents) ? contents.map(value => renderMarked(plugin, value)).join('<hr>')
        : typeof contents === 'string' || 'language' in contents ? renderMarked(plugin, contents) : plugin.docToHTML(contents)
      return {
        pos: result.range ? plugin.fromPosition(result.range.start) : pos,
        end: result.range ? plugin.fromPosition(result.range.end) : pos,
        above: true,
        create: () => createHover(view, html, () => focus),
      }
    } catch { return null }
  }, { hideOn: tr => tr.docChanged || !!tr.selection })

  return [hover, hoverTheme, keymap.of([{
    key: 'Mod-Alt-i', run(view) {
      const existing = view.dom.querySelector<HTMLElement>('.cm-python-hover-doc:not(.cm-python-hover-signature)')
      if (existing) existing.focus()
      else {
        focusNext = true
        activateHover(view, view.state.selection.main.head, 1, { tooltip: hover, until: tr => tr.docChanged || !!tr.selection })
      }
      return true
    },
  }, { key: 'Escape', run(view) {
    focusNext = false
    if (!view.state.field(hover.active).length) return false
    view.dispatch({ effects: closeHoverTooltips })
    return true
  } }])]
}

function createHover(view: EditorView, html: string, shouldFocus: () => boolean) {
  const dom = document.createElement('div')
  dom.className = 'cm-python-hover'
  const content = dom.appendChild(document.createElement('div'))
  content.className = 'cm-python-hover-doc cm-lsp-documentation quiet-scrollbar'
  content.tabIndex = 0
  content.setAttribute('role', 'region')
  content.setAttribute('aria-label', 'Python 文档')
  content.innerHTML = html
  pinDocumentationContext(dom, content)
  const signature = dom.querySelector<HTMLElement>('.cm-python-hover-signature')
  // Keep a readable body even when CodeMirror clamps the hover near a viewport edge.
  const sizeObserver = new ResizeObserver(([entry]) => {
    if (entry) dom.style.setProperty('--python-hover-height', `${entry.contentRect.height}px`)
  })
  signature?.addEventListener('wheel', event => {
    if (signature.scrollHeight > signature.clientHeight + 1) return
    const delta = event.deltaMode === 1 ? event.deltaY * 20
      : event.deltaMode === 2 ? event.deltaY * content.clientHeight : event.deltaY
    content.scrollTop += delta
    event.preventDefault()
  }, { passive: false })
  const grip = dom.appendChild(document.createElement('div'))
  grip.className = 'cm-python-hover-resize'
  grip.title = '拖动调整文档大小'
  grip.setAttribute('aria-hidden', 'true')
  let drag: { x: number; y: number; width: number; height: number } | undefined
  const close = (event: KeyboardEvent) => {
    if (event.key !== 'Escape') return
    event.preventDefault()
    event.stopPropagation()
    view.dispatch({ effects: closeHoverTooltips })
    view.focus()
  }
  dom.addEventListener('keydown', close)
  // Pointer capture can put the pointer outside the previous tooltip bounds while resizing.
  dom.addEventListener('mousemove', event => { if (drag) event.stopPropagation() })
  grip.addEventListener('pointerdown', event => {
    if (event.button !== 0) return
    event.preventDefault()
    grip.setPointerCapture(event.pointerId)
    const rect = dom.getBoundingClientRect()
    drag = { x: event.clientX, y: event.clientY, width: rect.width, height: rect.height }
  })
  grip.addEventListener('pointermove', event => {
    if (!drag) return
    // CodeMirror keeps the text anchor fixed, including when the hover is above it.
    const above = dom.closest('.cm-tooltip')?.classList.contains('cm-tooltip-above')
    readingSize = {
      width: Math.min(window.innerWidth - 24, Math.max(240, drag.width + event.clientX - drag.x)),
      height: Math.min(window.innerHeight - 24, Math.max(100, drag.height + (above ? -1 : 1) * (event.clientY - drag.y))),
    }
    dom.style.width = `${readingSize.width}px`
    dom.style.height = `${readingSize.height}px`
    repositionTooltips(view)
  })
  grip.addEventListener('lostpointercapture', () => { drag = undefined })
  return {
    dom,
    mount() {
      sizeObserver.observe(dom)
      if (readingSize) {
        dom.style.width = `${readingSize.width}px`
        dom.style.height = `${readingSize.height}px`
      }
      if (shouldFocus()) content.focus({ preventScroll: true })
    },
    destroy() { sizeObserver.disconnect() },
  }
}

/** Move the leading LSP signature once; section boundaries let CSS push old headings away. */
function pinDocumentationContext(dom: HTMLElement, content: HTMLElement) {
  const first = content.firstElementChild
  if (first?.matches('pre:has(> code.language-python)') && first.nextElementSibling) {
    const signature = document.createElement('div')
    signature.className = 'cm-python-hover-doc cm-python-hover-signature quiet-scrollbar'
    signature.tabIndex = 0
    signature.setAttribute('role', 'region')
    signature.setAttribute('aria-label', '函数签名')
    signature.appendChild(first)
    dom.insertBefore(signature, content)
    // The pinned header already separates the signature from the documentation.
    if (content.firstElementChild?.tagName === 'HR') content.firstElementChild.remove()
  }

  let section: HTMLElement | undefined
  for (const node of Array.from(content.childNodes)) {
    if (node instanceof HTMLElement && /^H[1-6]$/.test(node.tagName)) {
      section = document.createElement('section')
      section.className = 'cm-python-hover-section'
      content.insertBefore(section, node)
    }
    section?.appendChild(node)
  }
}

const hoverTheme = EditorView.theme({
  '.cm-tooltip-hover:has(.cm-python-hover)': {
    display: 'flex', flexDirection: 'column', overflow: 'hidden',
    border: '1px solid var(--color-line)', borderRadius: '6px',
    backgroundColor: 'var(--color-surface)', boxShadow: 'var(--shadow-card)',
  },
  '.cm-python-hover': {
    position: 'relative', display: 'flex', flexDirection: 'column', boxSizing: 'border-box', minHeight: '0', flex: '0 1 auto',
    width: 'max-content', maxWidth: 'min(680px, calc(100vw - 24px))', maxHeight: 'min(420px, 55vh)',
    overflow: 'hidden', borderRadius: '6px',
  },
  '.cm-python-hover[style*="width"]': { maxWidth: 'calc(100vw - 24px)', maxHeight: 'calc(100vh - 24px)' },
  '.cm-python-hover-doc': {
    minWidth: '0', minHeight: '0', flex: '1 1 auto', overflow: 'auto', overscrollBehavior: 'contain',
    padding: '8px 10px', fontFamily: 'var(--font-sans)', fontSize: '13px',
    color: 'var(--color-ink-2)', lineHeight: '1.65', whiteSpace: 'normal', overflowWrap: 'anywhere',
  },
  '.cm-python-hover-signature': {
    flex: '0 0 auto', boxSizing: 'border-box',
    maxHeight: 'min(110px, 25vh, max(0px, calc(var(--python-hover-height, 420px) - 24px)))', padding: '0 10px',
    borderBottom: '1px solid var(--color-line)', backgroundColor: 'var(--color-surface)',
  },
  '.cm-python-hover-signature + .cm-python-hover-doc': { minHeight: '24px' },
  '.cm-python-hover-section': { display: 'flow-root', paddingBottom: '4px' },
  '.cm-python-hover-doc .cm-python-hover-section > :first-child': {
    position: 'sticky', top: '-8px', zIndex: '1', margin: '0 -10px 4px', padding: '6px 10px',
    backgroundColor: 'var(--color-surface)',
  },
  '.cm-python-hover-doc:focus-visible': { outline: '1px solid var(--color-accent)', outlineOffset: '-2px' },
  '.cm-python-hover-doc p': { margin: '8px 0' },
  '.cm-python-hover-doc h1, .cm-python-hover-doc h2, .cm-python-hover-doc h3, .cm-python-hover-doc h4, .cm-python-hover-doc h5, .cm-python-hover-doc h6': {
    margin: '16px 0 6px', fontSize: '13px', fontWeight: '650', lineHeight: '1.5', color: 'var(--color-ink-1)',
  },
  '.cm-python-hover-doc strong, .cm-python-hover-doc dt': { fontWeight: '600', color: 'var(--color-ink-1)' },
  '.cm-python-hover-doc code': { fontFamily: 'var(--font-mono)', fontSize: '12px' },
  '.cm-python-hover-doc :not(pre) > code': {
    padding: '1px 4px', borderRadius: '3px', backgroundColor: 'var(--color-bg-subtle)', color: 'var(--color-code-fg)',
    boxDecorationBreak: 'clone',
  },
  '.cm-python-hover-doc pre': {
    whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', margin: '8px 0', padding: '6px 8px',
    border: 'none', borderRadius: '4px',
    backgroundColor: 'var(--color-code-bg)', color: 'var(--color-code-fg)', fontFamily: 'var(--font-mono)', lineHeight: '1.6',
  },
  '.cm-python-hover-signature pre': { margin: '0', padding: '7px 0', border: 'none', backgroundColor: 'transparent' },
  '.cm-python-hover-doc ul, .cm-python-hover-doc ol': { margin: '8px 0', paddingLeft: '22px' },
  '.cm-python-hover-doc ul': { listStyleType: 'disc' },
  '.cm-python-hover-doc ol': { listStyleType: 'decimal' },
  '.cm-python-hover-doc li': { margin: '4px 0' },
  '.cm-python-hover-doc dd': { margin: '4px 0 8px 16px' },
  '.cm-python-hover-doc blockquote': { margin: '10px 0', paddingLeft: '10px', borderLeft: '2px solid var(--color-line)' },
  '.cm-python-hover-doc hr': { margin: '12px 0', border: 'none', borderTop: '1px solid var(--color-line)' },
  '.cm-python-hover-doc > :first-child': { marginTop: '0' },
  '.cm-python-hover-doc > :last-child': { marginBottom: '0' },
  '.cm-python-hover-doc img': { maxWidth: '100%' },
  '.cm-python-hover-doc table': { display: 'block', maxWidth: '100%', overflowX: 'auto', margin: '10px 0', borderCollapse: 'collapse' },
  '.cm-python-hover-doc th, .cm-python-hover-doc td': { padding: '5px 8px', border: '1px solid var(--color-line)', textAlign: 'left' },
  '.cm-python-hover-doc th': { fontWeight: '600', color: 'var(--color-ink-1)', backgroundColor: 'var(--color-bg-subtle)' },
  '.cm-python-hover-doc a': { color: 'var(--color-accent)', textDecoration: 'underline', textUnderlineOffset: '2px' },
  '.cm-python-hover-resize': {
    position: 'absolute', right: '0', bottom: '0', width: '14px', height: '14px',
    cursor: 'nwse-resize', touchAction: 'none',
    background: 'linear-gradient(135deg, transparent 55%, var(--color-ink-3) 56%, var(--color-ink-3) 62%, transparent 63%, transparent 75%, var(--color-ink-3) 76%, var(--color-ink-3) 82%, transparent 83%)',
  },
  '.cm-tooltip-above .cm-python-hover-resize, .cm-python-hover.cm-tooltip-above .cm-python-hover-resize': {
    top: '0', bottom: 'auto', cursor: 'nesw-resize', transform: 'scaleY(-1)',
  },
})
