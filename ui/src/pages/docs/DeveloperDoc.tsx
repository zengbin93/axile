import { useState, type ReactNode } from 'react'
import { Check, Copy, TriangleAlert } from 'lucide-react'

export type DocSection = readonly [id: string, label: string]

export function InlineCode({ children }: { children: string }) {
  return <code className="rounded bg-fill px-1.5 py-0.5 font-mono text-[0.92em]">{children}</code>
}

export function RichText({ text }: { text: string }) {
  return <>{text.split('`').map((part, index) => index % 2 ? <InlineCode key={index}>{part}</InlineCode> : part)}</>
}

export function CodeBlock({ code }: { code: string }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      setCopied(false)
    }
  }
  return (
    <div className="relative overflow-hidden rounded-[8px] bg-code-bg">
      <button aria-label="复制代码" className="absolute right-2.5 top-2.5 inline-flex size-8 cursor-pointer items-center justify-center rounded-[6px] border border-white/15 bg-code-bg text-code-fg/70 hover:text-code-fg" onClick={() => void copy()} title="复制代码" type="button">
        {copied ? <Check size={15} /> : <Copy size={15} />}
      </button>
      <pre className="overflow-auto p-[18px] pr-14 font-mono text-[14px] leading-relaxed text-code-fg">{code}</pre>
    </div>
  )
}

export function SectionTitle({ id, children }: { id: string; children: string }) {
  return <h2 id={id} className="scroll-mt-8 pt-10 text-[20px] font-[650]">{children}</h2>
}

export function RuleList({ items }: { items: string[] }) {
  return <ul className="mt-3 flex list-disc flex-col gap-2 pl-5 text-[15px] leading-7 text-ink-2">{items.map((item) => <li key={item}><RichText text={item} /></li>)}</ul>
}

export function DocTable({ headers, rows, minWidth = 680 }: { headers: string[]; rows: ReactNode[][]; minWidth?: number }) {
  return (
    <div className="mt-4 overflow-x-auto rounded-[8px] border border-line">
      <table className="w-full border-collapse text-[14px]" style={{ minWidth }}>
        <thead><tr className="bg-fill text-left text-ink-2">{headers.map((header) => <th key={header} className="px-4 py-3 font-[550]">{header}</th>)}</tr></thead>
        <tbody>{rows.map((row, index) => <tr key={index} className="border-t border-line align-top">{row.map((cell, cellIndex) => <td key={cellIndex} className="px-4 py-3 text-ink-2">{cell}</td>)}</tr>)}</tbody>
      </table>
    </div>
  )
}

export function DeveloperDoc({ category, title, intro, sections, markdown, children }: {
  category: string
  title: string
  intro: ReactNode
  sections: readonly DocSection[]
  markdown: () => string
  children: ReactNode
}) {
  const [copyStatus, setCopyStatus] = useState<'idle' | 'copied' | 'error'>('idle')
  const copyMarkdown = async () => {
    try {
      await navigator.clipboard.writeText(markdown())
      setCopyStatus('copied')
    } catch {
      setCopyStatus('error')
    }
    setTimeout(() => setCopyStatus('idle'), 1800)
  }
  return (
    <div className="h-full overflow-y-auto bg-bg text-ink-1">
      <header className="border-b border-line">
        <div className="mx-auto flex max-w-[1180px] flex-col gap-5 px-5 py-9 sm:px-8 md:flex-row md:items-end md:justify-between">
          <div className="max-w-[760px]">
            <div className="text-xs font-semibold text-accent">{category} / 开发文档</div>
            <h1 className="mt-2 text-[30px] font-[680]">{title}</h1>
            <p className="mt-3 text-[15.5px] leading-7 text-ink-2">{intro}</p>
          </div>
          <button className={`inline-flex h-9 w-fit flex-none cursor-pointer items-center gap-2 rounded-[8px] border px-3 text-[14px] font-[520] ${copyStatus === 'error' ? 'border-warn/40 text-warn' : 'border-line text-ink-2 hover:border-ink-3 hover:text-ink-1'}`} onClick={() => void copyMarkdown()} type="button">
            {copyStatus === 'copied' ? <Check size={15} /> : copyStatus === 'error' ? <TriangleAlert size={15} /> : <Copy size={15} />}
            {copyStatus === 'copied' ? '已复制' : copyStatus === 'error' ? '复制失败' : '复制 Markdown'}
          </button>
        </div>
      </header>
      <div className="mx-auto grid max-w-[1180px] grid-cols-1 gap-10 px-5 pb-16 sm:px-8 lg:grid-cols-[180px_minmax(0,1fr)]">
        <nav className="hidden pt-10 lg:block" aria-label="文档目录">
          <div className="sticky top-8 border-l border-line pl-4">
            <div className="mb-2 text-xs font-semibold text-ink-3">本页内容</div>
            {sections.map(([id, label]) => <a key={id} className="block py-1.5 text-[14px] text-ink-2 hover:text-ink-1" href={`#${id}`}>{label}</a>)}
          </div>
        </nav>
        <main className="min-w-0 max-w-[860px]">{children}</main>
      </div>
    </div>
  )
}
