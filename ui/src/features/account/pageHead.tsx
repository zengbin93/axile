/**
 * 账户域页头原子：统一大标题（``页名 · 账户名`` + 渠道 chip）与账户名共享元素门控。
 *
 * 身份协议（先命名同一逻辑物）：
 * - 账户名是账户域跨页唯一不变的逻辑物（同字号 18/640、同槽位族、内容真不变），
 *   统一挂 ``account-name-*``：域内互切只剩**纯平移** FLIP，缩放恒 1、绝不拉皮；
 *   进出账户域（舰队卡 → 标题头）沿用既有配对。
 * - 页名前缀是内容真变，不挂名，随工作区 180ms 交叉淡（同槽换字，诚实）。
 * - 「同账户」的连续感由本标题行承担。
 */
import { useViewTransitionState } from 'react-router'
import { Chip } from '@/components/ui/Card'
import { channelLabel } from '@/features/dashboard/display'
import type { TradeChannel } from '@/types/api'

/**
 * 账户名共享元素门控：仅在「往返账户域」的 View Transition 期间为真。
 *
 * ``useViewTransitionState`` 只认精确路径、不支持通配，故逐路径展开（hooks 不可进循环）。
 * 执行详情含动态段（executionId）无法在此登记，不参与名字 FLIP（``AccountPageTitle``
 * 用 ``flip={false}`` 关掉）。**新增账户域页面时必须在此登记**，否则切到该页时
 * 旧侧快照缺名、FLIP 断档。
 */
// oxlint-disable-next-line react/only-export-components -- 门控 hook 与标题原子同属页头一处，刻意合并
export function useAccountNameVt(accountId: number): boolean {
  const base = `/accounts/${accountId}`
  const tDetail = useViewTransitionState(base)
  const tHoldings = useViewTransitionState(`${base}/holdings`)
  const tExecutions = useViewTransitionState(`${base}/executions`)
  const tHistory = useViewTransitionState(`${base}/history`)
  const tEdit = useViewTransitionState(`${base}/edit`)
  const tEditConnection = useViewTransitionState(`${base}/edit/connection`)
  const tEditLeverage = useViewTransitionState(`${base}/edit/leverage`)
  const tEditSymbols = useViewTransitionState(`${base}/edit/symbols`)
  const tEditPortfolio = useViewTransitionState(`${base}/edit/portfolio`)
  const tEditTimer = useViewTransitionState(`${base}/edit/timer`)
  const tEditAlgorithm = useViewTransitionState(`${base}/edit/algorithm`)
  const tEditControl = useViewTransitionState(`${base}/edit/control`)
  return (
    tDetail || tHoldings || tExecutions || tHistory ||
    tEdit || tEditConnection || tEditLeverage || tEditSymbols || tEditPortfolio ||
    tEditTimer || tEditAlgorithm || tEditControl
  )
}

/**
 * 账户域统一大标题：``页名 · 账户名`` + 渠道 chip（返回片段，外层自行排行）。
 *
 * Parameters
 * ----------
 * page : string
 *     当前页名（与侧边栏一致）；不进共享身份，随工作区交叉淡。
 * name : string | null | undefined
 *     账户名；缺省时回退 ``账户 #id`` 且不挂共享名（身份未就位不做假连续）。
 * flip : boolean
 *     为假时账户名不做共享元素 FLIP（执行详情等无法门控的页）。
 */
export function AccountPageTitle({
  accountId,
  page,
  name,
  channel,
  market,
  flip = true,
}: {
  accountId: number
  page: string
  name?: string | null
  channel?: TradeChannel
  market?: string
  flip?: boolean
}) {
  const transitioning = useAccountNameVt(accountId)
  const nameVt = flip && transitioning && name != null
  return (
    <>
      <h1 className="text-[18px] font-[640]">
        {page} ·{' '}
        <span
          style={nameVt ? { viewTransitionName: `account-name-${accountId}` } : undefined}
        >
          {name ?? `账户 #${accountId}`}
        </span>
      </h1>
      {channel && <Chip>{channelLabel(channel, market ?? '')}</Chip>}
    </>
  )
}
