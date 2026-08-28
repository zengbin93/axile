import { useState } from 'react'
import { Check, Copy, TriangleAlert } from 'lucide-react'
import { buildCustomCalcMarkdown, CALC_EXAMPLES, CONTEXT_FIELDS, CONTEXT_MODES, CONTRACT_CODE, CONTRACT_RULES, EXECUTION_TRIGGERS, EXECUTOR_RULES } from './customCalcMarkdown'

const SECTIONS = [['execution', '何时执行'], ['contexts', '运行上下文'], ['contract', '函数契约'], ['api', 'Context API'], ['executor', '完整 executor'], ['examples', '示例']] as const

function InlineCode({ children }: { children: string }) {
  return <code className="rounded bg-fill px-1.5 py-0.5 font-mono text-[0.92em]">{children}</code>
}

function RichText({ text }: { text: string }) {
  return <>{text.split('`').map((part, index) => index % 2 ? <InlineCode key={`${part}-${index}`}>{part}</InlineCode> : part)}</>
}

function CodeBlock({ code }: { code: string }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    await navigator.clipboard.writeText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
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

function SectionTitle({ id, children }: { id: string; children: string }) {
  return <h2 id={id} className="scroll-mt-8 pt-10 text-[20px] font-[650]">{children}</h2>
}

function RuleList({ items }: { items: string[] }) {
  return <ul className="mt-3 flex list-disc flex-col gap-2 pl-5 text-[15px] leading-7 text-ink-2">{items.map((item) => <li key={item}><RichText text={item} /></li>)}</ul>
}

export function CustomCalcDocPage() {
  const [copyStatus, setCopyStatus] = useState<'idle' | 'copied' | 'error'>('idle')
  const copyMarkdown = async () => {
    try {
      await navigator.clipboard.writeText(buildCustomCalcMarkdown())
      setCopyStatus('copied')
    } catch {
      setCopyStatus('error')
    }
    setTimeout(() => setCopyStatus('idle'), 1800)
  }

  return (
    <div className="min-h-screen bg-bg text-ink-1">
      <header className="border-b border-line">
        <div className="mx-auto flex max-w-[1180px] flex-col gap-5 px-5 py-9 sm:px-8 md:flex-row md:items-end md:justify-between">
          <div className="max-w-[760px]">
            <div className="text-xs font-semibold text-accent">组合 / 开发文档</div>
            <h1 className="mt-2 text-[30px] font-[680]">自定义组合函数</h1>
            <p className="mt-3 text-[15.5px] leading-7 text-ink-2">
              用 <InlineCode>calculate_portfolio(context)</InlineCode> 计算组合的原始目标权重。Context 提供跨渠道的统一查询；高级代码也可以直接使用当前账户的完整 executor。
            </p>
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
            {SECTIONS.map(([id, label]) => <a key={id} className="block py-1.5 text-[14px] text-ink-2 hover:text-ink-1" href={`#${id}`}>{label}</a>)}
          </div>
        </nav>

        <main className="min-w-0 max-w-[860px]">
          <SectionTitle id="execution">何时执行</SectionTitle>
          <p className="mt-2 text-[15px] leading-7 text-ink-2">函数只在明确需要重新计算目标时运行：</p>
          <RuleList items={EXECUTION_TRIGGERS} />
          <p className="mt-4 border-l-2 border-accent pl-4 text-[14.5px] leading-7 text-ink-2">普通页面读取只显示最近一次成功保存的目标快照，不会执行用户函数。</p>

          <SectionTitle id="contexts">样例上下文与真实账户</SectionTitle>
          <div className="mt-4 overflow-x-auto rounded-[8px] border border-line">
            <table className="w-full min-w-[680px] border-collapse text-[14px]">
              <thead><tr className="bg-fill text-left text-ink-2"><th className="px-4 py-3 font-[550]">能力</th><th className="px-4 py-3 font-[550]">样例上下文</th><th className="px-4 py-3 font-[550]">真实账户</th></tr></thead>
              <tbody>{CONTEXT_MODES.map((mode) => <tr key={mode.item} className="border-t border-line"><td className="px-4 py-3 font-[550]">{mode.item}</td><td className="px-4 py-3 text-ink-2">{mode.sample}</td><td className="px-4 py-3 text-ink-2">{mode.real}</td></tr>)}</tbody>
            </table>
          </div>
          <div className="mt-4 rounded-[8px] border border-warn/35 bg-warn/5 px-4 py-3.5 text-[14.5px] leading-7 text-ink-2">
            <div className="flex items-center gap-2 font-[600] text-warn"><TriangleAlert size={16} />真实账户执行边界</div>
            <p className="mt-1">“试跑”只表示 Axile 不会自动执行函数返回的目标；如果函数主动调用 executor 的交易方法，仍会产生真实交易。</p>
          </div>

          <SectionTitle id="contract">函数契约</SectionTitle>
          <div className="mt-4"><CodeBlock code={CONTRACT_CODE} /></div>
          <RuleList items={CONTRACT_RULES} />

          <SectionTitle id="api">Context 通用能力</SectionTitle>
          <p className="mt-2 text-[15px] leading-7 text-ink-2">优先使用这些跨渠道能力。账户和行情缓存只在当前一次函数调用中有效。</p>
          <div className="mt-4 overflow-x-auto rounded-[8px] border border-line">
            <table className="w-full min-w-[760px] border-collapse text-[14px]">
              <thead><tr className="bg-fill text-left text-ink-2"><th className="px-4 py-3 font-[550]">字段或方法</th><th className="px-4 py-3 font-[550]">类型</th><th className="px-4 py-3 font-[550]">含义</th></tr></thead>
              <tbody>{CONTEXT_FIELDS.map((field) => <tr key={field.name} className="border-t border-line align-top"><td className="px-4 py-3 font-mono text-[13px]">{field.name}</td><td className="px-4 py-3 font-mono text-[13px] text-ink-3">{field.type}</td><td className="px-4 py-3 text-ink-2">{field.desc}</td></tr>)}</tbody>
            </table>
          </div>

          <SectionTitle id="executor">完整 executor</SectionTitle>
          <p className="mt-2 text-[15px] leading-7 text-ink-2">这是面向可信高级代码的入口，不是额外包装的只读接口。</p>
          <RuleList items={EXECUTOR_RULES} />

          <SectionTitle id="examples">示例</SectionTitle>
          <div className="mt-4 flex flex-col gap-8">
            {CALC_EXAMPLES.map((example) => <section key={example.key}>
              <div className="flex items-center gap-2"><h3 className="text-[16px] font-[600]">{example.title}</h3>{example.advanced && <span className="rounded bg-fill px-2 py-0.5 text-xs text-ink-3">高级</span>}</div>
              <p className="mb-3 mt-1 text-[14.5px] leading-6 text-ink-2">{example.desc}</p>
              <CodeBlock code={example.code} />
            </section>)}
          </div>
        </main>
      </div>
    </div>
  )
}
