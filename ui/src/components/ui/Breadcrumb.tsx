import { Fragment } from 'react'
import { Link } from '@/components/ui/nav'

/** 面包屑的一段：带 ``to`` 即可点上行；末段（当前页）省略 ``to``。 */
export type Crumb = { label: string; to?: string; annotation?: string }

/**
 * 层级面包屑 —— 一行安静的路径，兼作「我在哪」定位与逐层上行导航.

 * 第一性原理：详情页左上角要同时回答两个问题——「我在哪」与「怎么离开」。旧的单个
 * 「返回X」把箭头（读作 back=撤销上一步）与写死的目的地（其实是 up=层级父级）揉进一个
 * 控件，来路一旦不同（从通知/深链/列表进来）就预期错位，这正是「难用」的根。面包屑把整条
 * up 路径摊开：每段可点、可跳任意层级，末段作当前定位。根「总览」内建，各页只传后半段。

 * Parameters
 * ----------
 * trail : Crumb[]
 *     从根之下到当前页的路径段；末段视为当前页，渲染为不可点的定位文本。
 */
export function Breadcrumb({ trail }: { trail: Crumb[] }) {
  const items: Crumb[] = [{ label: '总览', to: '/' }, ...trail]
  const lastIndex = items.length - 1
  return (
    <nav aria-label="面包屑" className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[13px]">
      {items.map((c, i) => {
        const isCurrent = i === lastIndex
        const content = (
          <>
            <span>{c.label}</span>
            {!isCurrent && c.annotation && (
              <span className="ml-1 text-[11px] text-ink-3/70 group-hover:text-ink-2">· {c.annotation}</span>
            )}
          </>
        )
        return (
          <Fragment key={`${i}-${c.label}`}>
            {i > 0 && (
              <span aria-hidden className="text-ink-3/45">
                /
              </span>
            )}
            {isCurrent || !c.to ? (
              // 当前页略提亮作定位、不可点；无 to 的中间段（理论上少见）也退化为纯文本。
              <span
                className={`group inline-flex items-baseline whitespace-nowrap ${isCurrent ? 'text-ink-2' : 'text-ink-3'}`}
                aria-current={isCurrent ? 'page' : undefined}
              >
                {content}
              </span>
            ) : (
              <Link
                to={c.to}
                className="group inline-flex items-baseline whitespace-nowrap text-ink-3 hover:text-ink-1"
              >
                {content}
              </Link>
            )}
          </Fragment>
        )
      })}
    </nav>
  )
}
