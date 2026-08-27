import { Link } from '@/components/ui/nav'

/** 设置首页：先建组合，再建账户绑定它。 */
export function SetupHub() {
  return (
    <div className="mx-auto max-w-[1080px] px-12 pt-8 pb-6">
      <div className="mb-1.5 text-xs font-semibold tracking-wide text-accent">设置</div>
      <div className="text-[22px] font-[680] tracking-tight">你想设置什么？</div>
      <div className="mt-1.5 max-w-[560px] text-[14px] text-ink-2">
        组合决定「交易什么」，账户决定「在哪、怎么、何时」。先建组合，再建账户绑定它。
      </div>
      <div className="mt-4 grid grid-cols-1 gap-[18px] md:grid-cols-2">
        <Link
          to="/setup/pf/name"
          className="rounded-card border border-line bg-surface p-[26px] transition-all duration-150 hover:-translate-y-0.5 hover:border-border-strong"
        >
          <div className="text-3xl">🎯</div>
          <h3 className="mt-3.5 text-[18px] font-semibold">新建组合</h3>
          <p className="mt-1.5 text-[14px] text-ink-2">挑策略配权重，或自己写逻辑，产出目标持仓。</p>
          <span className="mt-4 inline-block text-[14px] font-semibold text-accent">开始 →</span>
        </Link>
        <Link
          to="/setup/acct/channel"
          className="rounded-card border border-line bg-surface p-[26px] transition-all duration-150 hover:-translate-y-0.5 hover:border-border-strong"
        >
          <div className="text-3xl">🔌</div>
          <h3 className="mt-3.5 text-[18px] font-semibold">新建账户</h3>
          <p className="mt-1.5 text-[14px] text-ink-2">连交易所 / 券商，绑定组合，设定交易方式。</p>
          <span className="mt-4 inline-block text-[14px] font-semibold text-accent">开始 →</span>
        </Link>
      </div>
    </div>
  )
}
