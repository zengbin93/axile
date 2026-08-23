import { useState } from 'react'

/** context 对外暴露的字段（与后端 `Context` 属性一一对应）。 */
const CTX_FIELDS: { name: string; type: string; desc: string }[] = [
  { name: 'today_return', type: 'float', desc: '当日收益率，小数形式（0.025 表示 2.5%）' },
  { name: 'today_max_drawdown', type: 'float', desc: '当日最大回撤，小数形式（0.05 表示 5%）' },
  { name: 'current_leverage', type: 'float', desc: '当前杠杆倍数（总持仓市值 / 账户总资产）' },
  { name: 'long_market_value', type: 'float', desc: '多头持仓市值' },
  { name: 'short_market_value', type: 'float', desc: '空头持仓市值' },
  { name: 'net_market_value', type: 'float', desc: '净市值（多头 − 空头）' },
  { name: 'total_balance', type: 'float', desc: '账户总资产' },
  { name: 'available_balance', type: 'float', desc: '可用余额' },
  { name: 'frozen_funds', type: 'float', desc: '冻结资金（总资产 − 可用余额）' },
  { name: 'used_margin', type: 'float', desc: '已用保证金（等于冻结资金）' },
  { name: 'margin_usage_ratio', type: 'float', desc: '保证金占用比例' },
  { name: 'yesterday_total_balance', type: 'float', desc: '昨日总资产（上一交易日最后一条成功记录）' },
  { name: 'consecutive_loss_days', type: 'int', desc: '连续亏损天数' },
  { name: 'last_update_time', type: 'str | None', desc: '最后一条成功记录的时间（ISO 8601）' },
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
    key: 'dd',
    title: '按回撤降仓',
    desc: '回撤越深，仓位越轻；超过阈值直接清仓。',
    code: `def calculate_portfolio(context):
    # 回撤越深，仓位越轻
    if context.today_max_drawdown > 0.05:
        return {}                          # 回撤超 5% 清仓
    scale = 0.5 if context.today_max_drawdown > 0.02 else 1.0
    return {"rb2610": 0.5 * scale, "ag2612": 0.5 * scale}`,
  },
  {
    key: 'loss',
    title: '连亏清仓',
    desc: '连续亏损达阈值则清仓观望。',
    code: `def calculate_portfolio(context):
    # 连续亏损达阈值则清仓观望
    if context.consecutive_loss_days >= 3:
        return {}
    return {"rb2610": 0.5, "ag2612": 0.5}`,
  },
]

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
        className="absolute right-2.5 top-2.5 cursor-pointer rounded-md border border-line bg-surface px-2.5 py-1 text-[12px] text-ink-2 hover:text-ink-1"
        onClick={copy}
      >
        {copied ? '已复制' : '复制'}
      </button>
      <pre className="overflow-auto rounded-[12px] bg-code-bg p-[18px] font-mono text-[13px] leading-relaxed text-code-fg">
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
  return (
    <div className="min-h-screen bg-bg">
      <div className="mx-auto max-w-[820px] px-8 py-12">
        <div className="text-xs font-semibold tracking-wide text-accent">组合 · 自定义逻辑</div>
        <h1 className="mt-1.5 text-[26px] font-[680] tracking-tight">开发自定义组合逻辑</h1>
        <p className="mt-3 text-[14.5px] leading-relaxed text-ink-2">
          自定义逻辑让你用一段 Python 决定组合「交易什么」。在本地写好并调试后，把
          <code className="mx-1 rounded bg-fill px-1.5 py-0.5 font-mono text-[13px]">calculate_portfolio</code>
          函数粘贴到组合编辑器，点「试跑」跑一次确认无误（默认空跑，也可切到某真实账户）。
        </p>

        {/* 契约 */}
        <h2 className="mt-9 text-[18px] font-[640]">函数契约</h2>
        <p className="mt-2 text-[14px] leading-relaxed text-ink-2">
          脚本必须定义一个恰好接收一个参数的函数
          <code className="mx-1 rounded bg-fill px-1.5 py-0.5 font-mono text-[13px]">calculate_portfolio(context)</code>，
          返回一个「品种 → 目标权重」的字典（<code className="rounded bg-fill px-1.5 py-0.5 font-mono text-[13px]">dict[str, float]</code>）。
          返回空字典 <code className="rounded bg-fill px-1.5 py-0.5 font-mono text-[13px]">{'{}'}</code> 表示空仓。
        </p>
        <div className="mt-3">
          <CodeBlock
            code={`def calculate_portfolio(context):
    # 返回 {品种: 目标权重}，例如 0.5 表示半仓多头，-0.5 表示半仓空头
    return {"rb2610": 0.5, "ag2612": 0.5}`}
          />
          <p className="mt-3 text-[13px] leading-relaxed text-ink-3">
            标的格式由交易渠道决定；新建组合时请以当前市场自动生成的示例为准。
          </p>
        </div>

        {/* context 字段 */}
        <h2 className="mt-9 text-[18px] font-[640]">可用的 context 字段</h2>
        <p className="mt-2 text-[14px] leading-relaxed text-ink-2">
          <code className="rounded bg-fill px-1.5 py-0.5 font-mono text-[13px]">context</code>
          提供账户当日 / 历史的统计指标。<b>空跑</b>会喂入一组固定的假值让脚本跑通；
          切到某<b>真实账户</b>则取该账户的真实数据，口径与真实调仓一致。
        </p>
        <div className="mt-3 overflow-hidden rounded-[12px] border border-line">
          <table className="w-full border-collapse text-[13.5px]">
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
                  <td className="px-4 py-2.5 font-mono text-[12.5px] text-ink-1">{f.name}</td>
                  <td className="px-4 py-2.5 font-mono text-[12.5px] text-ink-3">{f.type}</td>
                  <td className="px-4 py-2.5 text-ink-2">{f.desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* 示例 */}
        <h2 className="mt-9 text-[18px] font-[640]">示例</h2>
        <div className="mt-3 flex flex-col gap-6">
          {EXAMPLES.map((ex) => (
            <div key={ex.key}>
              <div className="text-[15px] font-[550]">{ex.title}</div>
              <div className="mb-2 mt-0.5 text-[13.5px] text-ink-2">{ex.desc}</div>
              <CodeBlock code={ex.code} />
            </div>
          ))}
        </div>

        {/* 注意事项 */}
        <h2 className="mt-9 text-[18px] font-[640]">注意事项</h2>
        <ul className="mt-2 flex list-disc flex-col gap-1.5 pl-5 text-[14px] leading-relaxed text-ink-2">
          <li>权重为小数（0.5 = 半仓）；正数为多头，负数为空头。</li>
          <li>脚本在服务端执行，请勿引入不可信的第三方依赖或访问外部网络。</li>
          <li>发生异常时试跑会把错误标在出错的代码行上，据此定位问题后再重新试跑。</li>
        </ul>
      </div>
    </div>
  )
}
