import { useState } from 'react'
import { Check, Copy, TriangleAlert } from 'lucide-react'
import { buildCustomCalcMarkdown, CUSTOM_CALC_NOTES } from './customCalcMarkdown'

/** context 对外暴露的通用能力（与后端 `Context` 一一对应）。 */
const CTX_FIELDS: { name: string; type: string; desc: string }[] = [
  { name: 'account', type: 'UnifiedAccountAssets', desc: '账户资产快照，包含总资产、可用资金和持仓' },
  { name: 'positions', type: 'list[Position]', desc: '当前账户的统一持仓列表' },
  { name: 'get_positions(symbol=None, direction=None)', type: 'list[Position]', desc: '按标的或多空方向筛选持仓' },
  { name: 'get_quote(symbol)', type: 'UnifiedPriceData', desc: '获取最新统一行情，同一次计算内自动缓存' },
  { name: 'get_price(symbol)', type: 'float', desc: '获取标的最新成交价' },
  { name: 'get_pending_orders(symbol=None)', type: 'list[UnifiedOrder]', desc: '查询全部或指定标的的未完成订单' },
  { name: 'query_trades(symbol, order_id)', type: 'list[TradeRecord]', desc: '查询指定订单的成交明细' },
  { name: 'executor', type: '渠道执行器', desc: '高级入口，可直接使用当前账户渠道的专有能力' },
]

/** 可复制的示例代码（原「示例」胶囊搬到文档，作为参考模板）。 */
const EXAMPLES: { key: string; title: string; desc: string; code: string }[] = [
  {
    key: 'fixed',
    title: '固定权重',
    desc: '最简单的等权组合，不依赖任何账户状态。',
    code: `def calculate_portfolio(context):
    # 返回 {品种: 目标权重}
    return {"rb2610": 0.5, "ag2612": 0.5}`,
  },
  {
    key: 'price',
    title: '按最新价格选择标的',
    desc: '使用统一行情接口，GM、TQ、CTP 等渠道共用相同写法。',
    code: `def calculate_portfolio(context):
    rb_price = context.get_price("rb2610")
    ag_price = context.get_price("ag2612")
    return {"rb2610": 1.0} if rb_price < ag_price else {"ag2612": 1.0}`,
  },
  {
    key: 'tq-multiplier',
    title: '读取 TQ 合约乘数',
    desc: '渠道专有信息通过 executor 获取；这段代码只适用于 TQ 账户。',
    code: `def calculate_portfolio(context):
    quote = context.executor.get_market_data(["KQ.m@SHFE.rb"])["KQ.m@SHFE.rb"]
    multiplier = float(quote.extra["volume_multiple"])
    return {"KQ.m@SHFE.rb": min(1.0, 10.0 / multiplier)}`,
  },
]

const CONTRACT_CODE = `def calculate_portfolio(context):
    # 返回 {品种: 目标权重}，例如 0.5 表示半仓多头，-0.5 表示半仓空头
    return {"rb2610": 0.5, "ag2612": 0.5}`

/** 带「复制」按钮的代码块。 */
function CodeBlock({ code }: { code: string }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    void navigator.clipboard?.writeText(code).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }
  return (
    <div className="relative">
      <button
        className="absolute right-2.5 top-2.5 cursor-pointer rounded-md border border-line bg-surface px-2.5 py-1 text-[13px] text-ink-2 hover:text-ink-1"
        onClick={copy}
      >
        {copied ? '已复制' : '复制'}
      </button>
      <pre className="overflow-auto rounded-[12px] bg-code-bg p-[18px] font-mono text-[14px] leading-relaxed text-code-fg">
        {code}
      </pre>
    </div>
  )
}

/**
 * 自定义组合逻辑开发文档（独立整页，供编辑器「开发文档 ↗」新标签打开）。
 *
 * 说明 `calculate_portfolio(context)` 的契约、可用的 context 字段与参考示例。
 * 用户在本页之外（如本地 IDE）开发脚本，试跑通过后粘贴回组合编辑器。
 */
export function CustomCalcDocPage() {
  const [copyStatus, setCopyStatus] = useState<'idle' | 'copied' | 'error'>('idle')
  const copyMarkdown = async () => {
    try {
      await navigator.clipboard.writeText(buildCustomCalcMarkdown(CTX_FIELDS, CONTRACT_CODE, EXAMPLES, CUSTOM_CALC_NOTES))
      setCopyStatus('copied')
    } catch {
      setCopyStatus('error')
    }
    setTimeout(() => setCopyStatus('idle'), 1800)
  }

  return (
    <div className="min-h-screen bg-bg">
      <div className="mx-auto max-w-[1408px] px-8 py-12">
        <div className="flex flex-col items-start gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="text-xs font-semibold tracking-wide text-accent">组合 · 自定义逻辑</div>
            <h1 className="mt-1.5 text-[27px] font-[680] tracking-tight">开发自定义组合逻辑</h1>
          </div>
          <button
            className={`inline-flex h-9 flex-none cursor-pointer items-center gap-2 rounded-[8px] border px-3 text-[14px] font-[520] ${copyStatus === 'error' ? 'border-warn/40 text-warn' : 'border-line text-ink-2 hover:border-ink-3 hover:text-ink-1'}`}
            onClick={() => void copyMarkdown()}
            type="button"
          >
            {copyStatus === 'copied' ? <Check size={15} /> : copyStatus === 'error' ? <TriangleAlert size={15} /> : <Copy size={15} />}
            {copyStatus === 'copied' ? '已复制' : copyStatus === 'error' ? '复制失败' : '复制 Markdown'}
          </button>
        </div>
        <p className="mt-3 text-[15.5px] leading-relaxed text-ink-2">
          自定义逻辑让你用一段 Python 决定组合「交易什么」。在本地写好并调试后，把
          <code className="mx-1 rounded bg-fill px-1.5 py-0.5 font-mono text-[14px]">calculate_portfolio</code>
          函数粘贴到组合编辑器，点「试跑」跑一次确认无误（默认空跑，也可切到某真实账户）。
        </p>

        {/* 契约 */}
        <h2 className="mt-9 text-[19px] font-[640]">函数契约</h2>
        <p className="mt-2 text-[15px] leading-relaxed text-ink-2">
          脚本必须定义一个恰好接收一个参数的函数
          <code className="mx-1 rounded bg-fill px-1.5 py-0.5 font-mono text-[14px]">calculate_portfolio(context)</code>，
          返回一个「品种 → 目标权重」的字典（<code className="rounded bg-fill px-1.5 py-0.5 font-mono text-[14px]">dict[str, float]</code>）。
          返回空字典 <code className="rounded bg-fill px-1.5 py-0.5 font-mono text-[14px]">{'{}'}</code> 表示空仓。
        </p>
        <div className="mt-3">
          <CodeBlock code={CONTRACT_CODE} />
          <p className="mt-3 text-[14px] leading-relaxed text-ink-3">
            标的格式由交易渠道决定；新建组合时请以当前市场自动生成的示例为准。
          </p>
        </div>

        {/* context 字段 */}
        <h2 className="mt-9 text-[19px] font-[640]">可用的 context 能力</h2>
        <p className="mt-2 text-[15px] leading-relaxed text-ink-2">
          <code className="rounded bg-fill px-1.5 py-0.5 font-mono text-[14px]">context</code>
          基于统一模型提供账户、持仓、行情和订单查询。<b>空跑</b>使用固定样例账户和行情；
          切到某<b>真实账户</b>会准备该账户的真实渠道并执行实际查询，口径与真实调仓一致。
        </p>
        <div className="mt-3 overflow-hidden rounded-[12px] border border-line">
          <table className="w-full border-collapse text-[14.5px]">
            <thead>
              <tr className="bg-fill text-left text-ink-2">
                <th className="px-4 py-2.5 font-[550]">字段</th>
                <th className="px-4 py-2.5 font-[550]">类型</th>
                <th className="px-4 py-2.5 font-[550]">含义</th>
              </tr>
            </thead>
            <tbody>
              {CTX_FIELDS.map((f) => (
                <tr key={f.name} className="border-t border-line">
                  <td className="px-4 py-2.5 font-mono text-[13.5px] text-ink-1">{f.name}</td>
                  <td className="px-4 py-2.5 font-mono text-[13.5px] text-ink-3">{f.type}</td>
                  <td className="px-4 py-2.5 text-ink-2">{f.desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* 示例 */}
        <h2 className="mt-9 text-[19px] font-[640]">示例</h2>
        <div className="mt-3 flex flex-col gap-6">
          {EXAMPLES.map((ex) => (
            <div key={ex.key}>
              <div className="text-[16px] font-[550]">{ex.title}</div>
              <div className="mb-2 mt-0.5 text-[14.5px] text-ink-2">{ex.desc}</div>
              <CodeBlock code={ex.code} />
            </div>
          ))}
        </div>

        {/* 注意事项 */}
        <h2 className="mt-9 text-[19px] font-[640]">注意事项</h2>
        <ul className="mt-2 flex list-disc flex-col gap-1.5 pl-5 text-[15px] leading-relaxed text-ink-2">
          {CUSTOM_CALC_NOTES.map((note) => <li key={note}>{note.replaceAll('`', '')}</li>)}
        </ul>
      </div>
    </div>
  )
}
