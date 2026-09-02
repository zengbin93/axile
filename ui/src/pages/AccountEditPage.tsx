/**
 * 账户浅配置页 /accounts/:id/edit/*。
 *
 * 基本信息、杠杆、品种控制、组合执行各走可直达子路由；连接设置、定时、算法、流控
 * 仍由各自的完整编辑器承载。保存保持最小 PATCH + 底栏变更摘要；保存与取消都不离开本页。
 */

import { useCallback, useEffect, useState, type CSSProperties } from 'react'
import { Check, ChevronDown, Eye, EyeOff } from 'lucide-react'
import { useParams, useViewTransitionState } from 'react-router'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { Skeleton } from '@/components/ui/Skeleton'
import { Select } from '@/components/ui/Select'
import { SymbolTagInput } from '@/components/ui/SymbolTagInput'
import { ExecutionTimeoutInput } from '@/features/account/ExecutionTimeoutInput'
import { executionTimeoutError } from '@/features/account/executionTimeout'
import { LeverageInput } from '@/features/account/LeverageInput'
import { leverageError } from '@/features/account/leverage'
import { AccountPageTitle } from '@/features/account/pageHead'
import { WeightPrecisionInput } from '@/features/account/WeightPrecisionInput'
import { weightPrecisionError } from '@/features/account/weightPrecision'
import {
  accountConfigVtName,
  describeLeverage,
  describeSymbolControl,
  readAccountConfigSummary,
  writeAccountConfigSummary,
} from '@/features/account/configSummary'
import { getAccount, testAccountFeishu, updateAccount, type AccountFeishuTestResult } from '@/lib/api/accounts'
import { usePolling } from '@/lib/hooks/usePolling'
import { useDomainStore } from '@/stores/domain'
import { useChannelCatalogStore, useChannelDescriptor } from '@/stores/channels'
import { useToastStore } from '@/stores/ui'
import {
  TEXT,
  AREA,
  EditError,
  EditLoading,
  EditSaveBar,
  EditSynopsis,
  Row,
  Section,
  Toggle,
} from '@/features/account/editUi'
import type { Account, FeishuCardConfig, PortfolioLite } from '@/types/api'

type FeishuCardMode = 'default' | 'template' | 'custom'

const FEISHU_TEMPLATE_VARIABLES = [
  'account_mark', 'dt', 'algorithm', 'total_assets', 'available_cash', 'market_value',
  'positions', 'trades', 'account', 'execution', 'strategy', 'assets', 'targets',
  'orders', 'symbols', 'summary',
]

/** 通知卡片三态：默认是主角，模板 / 自定义面向高级用户，收进「高级设置」折叠条。 */
const FEISHU_CARD_MODES: Record<FeishuCardMode, { label: string; description: string }> = {
  default: { label: '默认', description: '使用内置账户执行结果卡片' },
  template: { label: '模板 ID', description: '使用你在飞书卡片搭建工具中发布的模板' },
  custom: { label: '自定义卡片', description: '卡片内容将原样发送，不替换变量' },
}

const FEISHU_CARD_MODE_ORDER: FeishuCardMode[] = ['default', 'template', 'custom']

/** 总览草稿：不含定时 / 算法（各在子页独立保存）。 */
interface Draft {
  name: string
  remark: string
  feishu: string
  feishuCardMode: FeishuCardMode
  feishuTemplateId: string
  feishuCardText: string
  longLev: string
  shortLev: string
  portfolioId: number | null
  forbidden: string[]
  risk: string[]
  weightPrecision: string
  executionTimeout: string
  writeEmpty: boolean
}

/**
 * 从用户输入中提取飞书机器人 key.

 * 兼容直接粘贴整条 webhook 链接（形如 ``.../bot/v2/hook/<key>``）：截取 ``hook/`` 之后、
 * 下一个分隔符之前的片段；输入本就是裸 key 时原样返回。幂等，可重复套用。
 */
function extractFeishuKey(raw: string): string {
  const s = raw.trim()
  const m = s.match(/hook\/([^/?#\s]+)/i)
  return m ? m[1] : s
}

function sameList(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((x, i) => x === b[i])
}

function draftOf(acc: Account): Draft {
  const cardConfig = acc.feishu_card_config
  return {
    name: acc.name,
    remark: acc.remark ?? '',
    feishu: acc.feishu_key ?? '',
    feishuCardMode: cardConfig?.mode ?? 'default',
    feishuTemplateId: cardConfig?.mode === 'template' ? cardConfig.template_id : '',
    feishuCardText: cardConfig?.mode === 'custom' ? JSON.stringify(cardConfig.card, null, 2) : '',
    longLev: String(acc.long_leverage ?? ''),
    shortLev: String(acc.short_leverage ?? ''),
    portfolioId: acc.portfolio_id,
    forbidden: acc.forbidden_symbols ?? [],
    risk: acc.risk_symbols ?? [],
    weightPrecision: String(acc.weight_precision ?? ''),
    executionTimeout: String(acc.execution_timeout ?? ''),
    writeEmpty: Boolean(acc.write_empty_record),
  }
}

function customCardDepth(value: unknown): number {
  if (Array.isArray(value)) return 1 + Math.max(0, ...value.map(customCardDepth))
  if (value && typeof value === 'object') return 1 + Math.max(0, ...Object.values(value).map(customCardDepth))
  return 0
}

function parseCustomCard(raw: string): { config: FeishuCardConfig | null; error: string | null } {
  if (!raw.trim()) return { config: null, error: '卡片内容不能为空' }
  let value: unknown
  try {
    value = JSON.parse(raw)
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    const position = /position (\d+)/i.exec(message)?.[1]
    if (!position) return { config: null, error: message }
    const offset = Number(position)
    const before = raw.slice(0, offset)
    const line = before.split('\n').length
    const column = offset - before.lastIndexOf('\n')
    return { config: null, error: `第 ${line} 行第 ${column} 列：JSON 格式有误` }
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) return { config: null, error: '卡片内容必须是 JSON 对象' }
  const card = value as Record<string, unknown>
  if ('msg_type' in card || 'card' in card) return { config: null, error: '请只粘贴卡片主体，不要包含 webhook 消息信封' }
  if (new TextEncoder().encode(JSON.stringify(card)).length > 20 * 1024) return { config: null, error: '卡片内容不得超过 20 KiB' }
  if (customCardDepth(card) > 20) return { config: null, error: '卡片内容嵌套不得超过 20 层' }
  return { config: { mode: 'custom', card }, error: null }
}

function draftFeishuCardConfig(draft: Draft): FeishuCardConfig | null {
  if (draft.feishuCardMode === 'default') return null
  if (draft.feishuCardMode === 'template') {
    const templateId = draft.feishuTemplateId.trim()
    return templateId ? { mode: 'template', template_id: templateId } : null
  }
  return parseCustomCard(draft.feishuCardText).config
}

function buildPatch(draft: Draft, acc: Account, showShortLeverage: boolean): Partial<Account> {
  const patch: Partial<Account> = {}
  const name = draft.name.trim()
  if (name && name !== acc.name) patch.name = name
  if (draft.remark !== (acc.remark ?? '')) patch.remark = draft.remark || null
  const feishuKey = extractFeishuKey(draft.feishu)
  if (feishuKey !== (acc.feishu_key ?? '')) patch.feishu_key = feishuKey || null
  const feishuCardConfig = draftFeishuCardConfig(draft)
  if (JSON.stringify(feishuCardConfig) !== JSON.stringify(acc.feishu_card_config)) {
    patch.feishu_card_config = feishuCardConfig
  }

  const nl = Number(draft.longLev) || 0
  if (nl !== (acc.long_leverage ?? 0)) patch.long_leverage = nl
  const ns = showShortLeverage ? Number(draft.shortLev) || 0 : 0
  if (ns !== (acc.short_leverage ?? 0)) patch.short_leverage = ns

  if (draft.portfolioId !== acc.portfolio_id) patch.portfolio_id = draft.portfolioId

  const fb = draft.forbidden
  if (!sameList(fb, acc.forbidden_symbols ?? [])) patch.forbidden_symbols = fb.length ? fb : null
  const rk = draft.risk
  if (!sameList(rk, acc.risk_symbols ?? [])) patch.risk_symbols = rk.length ? rk : null

  if (draft.weightPrecision.trim() !== '') {
    const wp = Number(draft.weightPrecision)
    if (Number.isFinite(wp) && wp !== acc.weight_precision) patch.weight_precision = wp
  }
  if (executionTimeoutError(draft.executionTimeout, { allowEmpty: true }) === null && draft.executionTimeout.trim() !== '') {
    // 复用同一条规则，避免两处口径漂移；非法值不进 patch，免得提交后被 422 打回。
    const et = Number(draft.executionTimeout)
    if (et !== acc.execution_timeout) patch.execution_timeout = et
  }
  const we = draft.writeEmpty ? 1 : 0
  if (we !== (acc.write_empty_record ?? 0)) patch.write_empty_record = we

  return patch
}

const FIELD_LABEL: Record<string, string> = {
  name: '名称',
  remark: '备注',
  feishu_key: '飞书',
  feishu_card_config: '通知卡片',
  long_leverage: '做多杠杆',
  short_leverage: '做空杠杆',
  weight_precision: '权重精度',
  execution_timeout: '执行超时',
  portfolio_id: '跟随组合',
  forbidden_symbols: '禁投',
  risk_symbols: '风险品种',
  write_empty_record: '空仓记录',
}

function summarize(patch: Partial<Account>, acc: Account, portfolios: PortfolioLite[] | null): string[] {
  const pname = (v: number | null | undefined) =>
    v == null ? '未绑定' : (portfolios?.find((p) => p.id === v)?.name ?? `#${v}`)
  const out: string[] = []
  for (const k of Object.keys(patch)) {
    if (k === 'long_leverage') out.push(`做多杠杆 ${acc.long_leverage ?? 0}→${patch.long_leverage}`)
    else if (k === 'short_leverage') out.push(`做空杠杆 ${acc.short_leverage ?? 0}→${patch.short_leverage}`)
    else if (k === 'weight_precision') out.push(`权重精度 ${acc.weight_precision}→${patch.weight_precision}`)
    else if (k === 'execution_timeout') out.push(`执行超时 ${acc.execution_timeout}s→${patch.execution_timeout}s`)
    else if (k === 'portfolio_id') out.push(`组合 ${pname(acc.portfolio_id)}→${pname(patch.portfolio_id)}`)
    else if (k === 'write_empty_record')
      out.push(`空仓记录 ${acc.write_empty_record ? '开' : '关'}→${patch.write_empty_record ? '开' : '关'}`)
    else out.push(`${FIELD_LABEL[k] ?? k} 已改`)
  }
  return out
}

type EditSection = 'basic' | 'leverage' | 'symbols' | 'portfolio'

const SECTION_TITLE: Record<EditSection, string> = {
  basic: '基本信息',
  leverage: '杠杆设置',
  symbols: '品种控制',
  portfolio: '组合执行',
}

export function AccountEditPage({ section = 'basic' }: { section?: EditSection }) {
  const { id } = useParams()
  const accountId = Number(id)
  const toast = useToastStore((s) => s.toast)
  const accounts = useDomainStore((s) => s.accounts)
  const portfolios = useDomainStore((s) => s.portfolios)
  const portfoliosError = useDomainStore((s) => s.portfoliosError)
  const refreshPortfolios = useDomainStore((s) => s.refreshPortfolios)
  const channelCatalogLoading = useChannelCatalogStore((s) => s.loading)
  const channelCatalogError = useChannelCatalogStore((s) => s.error)
  const refreshAccounts = useDomainStore((s) => s.refreshAccounts)

  const account = usePolling(useCallback((s: AbortSignal) => getAccount(accountId, s), [accountId]), {
    queryKey: `account:${accountId}`,
    intervalMs: 0,
  })
  const acc = account.data
  const channelDescriptor = useChannelDescriptor(acc?.trade_channel)
  const showShortLeverage = channelDescriptor?.ui.show_short_leverage ?? true
  const item = accounts?.find((a) => a.account_id === accountId) ?? null
  // 首帧用仪表盘缓存名/渠道挂标题，避免等 getAccount 时落点缺失、FLIP 断档，
  // 也避免 Chip 在过渡尾巴上闪现。
  const displayName = acc?.name ?? item?.name

  // Hero 配置带值 ↔ 本页「当前配置」摘要值的 FLIP：useViewTransitionState 对过渡的
  // current/next 双向匹配，两侧用同一精确路径判定即去程返程一致挂名。本页首帧必冷
  // （usePolling 无跨页缓存），落点靠模块级摘要缓存同步读出；真源到位即写新值。
  const tSelfSection = useViewTransitionState(`/accounts/${accountId}/edit/${section}`)
  const cachedConfig = acc ? null : readAccountConfigSummary(accountId)
  useEffect(() => {
    if (acc) writeAccountConfigSummary(accountId, acc, { showShortLeverage })
  }, [acc, accountId, showShortLeverage])
  /** 当前分区（杠杆/品种）的共享名 style；其余分区不挂。 */
  const sectionVtStyle = (kind: 'leverage' | 'symbols'): CSSProperties | undefined =>
    tSelfSection && section === kind
      ? { viewTransitionName: accountConfigVtName(accountId, kind) }
      : undefined

  const [ready, setReady] = useState(false)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [feishuTest, setFeishuTest] = useState<AccountFeishuTestResult | 'busy' | null>(null)
  const [feishuKeyRevealed, setFeishuKeyRevealed] = useState(false)
  const [showFeishuVariables, setShowFeishuVariables] = useState(false)
  const [feishuAdvancedOpen, setFeishuAdvancedOpen] = useState(false)
  const [saveError, setSaveError] = useState<Error | null>(null)

  /** 草稿重置为服务端当前值；数据未就绪时返回 false（供首帧初始化门控）。 */
  const resetDraft = useCallback(() => {
    if (!acc) return false
    setDraft(draftOf(acc))
    setSaveError(null)
    return true
  }, [acc])

  useEffect(() => {
    if (!ready && resetDraft()) setReady(true)
  }, [ready, resetDraft])

  /** 统一页头标题行（页名 · 账户名 + 渠道 chip）；账户名 FLIP 门控在原子内部。 */
  const titleName = (
    <AccountPageTitle
      accountId={accountId}
      page={SECTION_TITLE[section]}
      name={displayName}
      channel={acc?.trade_channel ?? item?.trade_channel}
      market={acc?.market ?? item?.market}
    />
  )

  if (account.error && !acc)
    return <EditError error={account.error} onRetry={account.refresh} />

  // 「当前配置」摘要常挂：加载（缓存/真源）→ 就绪（草稿）只换文本、不换节点。
  // view transition 的具名捕获认 DOM 节点——摘要若随加载/就绪分支整体重挂，
  // 进行中的组动画会被浏览器杀掉（表现就是「正向 FLIP 不飞」）。
  const draftNum = (s: string) => (s.trim() === '' ? null : Number(s) || 0)
  const savedLeverageText = acc
    ? describeLeverage(acc.long_leverage, acc.short_leverage, showShortLeverage)
    : null
  const savedSymbolsText = acc ? describeSymbolControl(acc.forbidden_symbols, acc.risk_symbols) : null
  const draftLeverageText = draft
    ? describeLeverage(
        draftNum(draft.longLev),
        showShortLeverage ? draftNum(draft.shortLev) : null,
        showShortLeverage,
      )
    : null
  const draftSymbolsText = draft ? describeSymbolControl(draft.forbidden, draft.risk) : null
  const leverageSynopsis = draftLeverageText ?? savedLeverageText ?? cachedConfig?.leverage ?? null
  const symbolsSynopsis = draftSymbolsText ?? savedSymbolsText ?? cachedConfig?.symbols ?? null
  // 同文才挂名：草稿被改后文本分岔，挂名即成内容 morph（假连续），退化为整页交叉淡。
  const leverageSame = draftLeverageText == null || draftLeverageText === savedLeverageText
  const symbolsSame = draftSymbolsText == null || draftSymbolsText === savedSymbolsText

  /** 标题 + 警告条 + 当前配置摘要：加载与就绪两态共用的页面 chrome（同位同节点）。 */
  const pageChrome = (
    <>
      <div className="flex flex-wrap items-baseline gap-3">{titleName}</div>
      <div className="mt-3 border-l-2 border-warn/60 bg-warn-tint/50 py-2 pl-3 pr-2 text-[14px] text-ink-2">
        修改不会立即下单，从下次调仓开始生效。
      </div>
      {section === 'leverage' && leverageSynopsis != null && (
        <EditSynopsis>
          <span
            className="inline-block"
            style={leverageSame ? sectionVtStyle('leverage') : undefined}
          >
            {leverageSynopsis}
          </span>
        </EditSynopsis>
      )}
      {section === 'symbols' && symbolsSynopsis != null && (
        <EditSynopsis>
          <span
            className="inline-block"
            style={symbolsSame ? sectionVtStyle('symbols') : undefined}
          >
            {symbolsSynopsis}
          </span>
        </EditSynopsis>
      )}
    </>
  )

  if (account.loading || !ready || !acc || !draft || (channelDescriptor == null && channelCatalogLoading)) {
    return (
      <section className="pb-24">
        {pageChrome}
        <EditLoading bare />
      </section>
    )
  }

  const d = draft
  const set = (patch: Partial<Draft>) => {
    setSaveError(null)
    setDraft((prev) => (prev ? { ...prev, ...patch } : prev))
  }
  // 飞书 key 容忍粘贴整条 webhook 链接：账户专用测试接口与保存都使用规整后的裸 key，
  // 测试请求同时携带当前卡片草稿，故无需先保存即可验证最终发送形态。
  const feishuKey = extractFeishuKey(d.feishu)
  const customCardResult = d.feishuCardMode === 'custom' ? parseCustomCard(d.feishuCardText) : null
  const feishuCardError =
    d.feishuCardMode === 'template'
      ? d.feishuTemplateId.trim()
        ? null
        : '模板 ID 不能为空'
      : customCardResult?.error ?? null
  const currentFeishuCardConfig = draftFeishuCardConfig(d)
  const runFeishuTest = async () => {
    setFeishuTest('busy')
    try {
      setFeishuTest(await testAccountFeishu(accountId, feishuKey, currentFeishuCardConfig))
    } catch (e) {
      setFeishuTest({ ok: false, message: e instanceof Error ? e.message : String(e) })
    }
  }

  // 杠杆边界校验由渠道目录给出；空=不改，0=该方向不启用。与服务端同口径，
  // 避免像旧版那样「填 999 也能保存、错误配置直进仓位计算」。
  const leverageOptions = { ...channelDescriptor?.leverage, allowEmpty: true }
  const longLevErr = leverageError(d.longLev, leverageOptions)
  const shortLevErr = showShortLeverage ? leverageError(d.shortLev, leverageOptions) : null
  // 执行总超时必须是正整数（服务端 >= 1）：这道兜底不允许按账户关掉。
  const timeoutErr = executionTimeoutError(d.executionTimeout, { allowEmpty: true })
  const weightPrecisionErr = weightPrecisionError(d.weightPrecision, { allowEmpty: true })
  const levErr = longLevErr ?? shortLevErr

  const patch = buildPatch(d, acc, showShortLeverage)
  const changes = summarize(patch, acc, portfolios)
  const dirty = changes.length > 0
  const blocked = Boolean(
    levErr || timeoutErr || weightPrecisionErr || feishuCardError || portfolios == null || portfoliosError || channelCatalogError,
  )

  const save = async () => {
    if (levErr) return toast(`杠杆有误：${levErr}`)
    if (timeoutErr) return toast(`执行超时有误：${timeoutErr}`)
    if (weightPrecisionErr) return toast(`权重精度有误：${weightPrecisionErr}`)
    if (!dirty) return toast('没有改动')
    setSaveError(null)
    try {
      const updated = await updateAccount(accountId, patch)
      // 保存响应直接写摘要缓存：返回详情时 hero 配置带首帧即新值，FLIP 落地同文。
      writeAccountConfigSummary(accountId, updated, { showShortLeverage })
      toast('账户已更新')
      void refreshAccounts()
      account.refresh()
    } catch (e) {
      setSaveError(e instanceof Error ? e : new Error(String(e)))
    }
  }

  return (
    <section>
      {pageChrome}

      {section === 'basic' && (
        <>
        <Section label="基本信息">
          <Row label="名称">
            <input className={TEXT} value={d.name} onChange={(e) => set({ name: e.target.value })} />
          </Row>
          <Row label="备注">
            <input className={TEXT} value={d.remark} placeholder="可选" onChange={(e) => set({ remark: e.target.value })} />
          </Row>
        </Section>
        <Section label="飞书通知">
          <Row label="机器人 Key" hint={feishuKey ? '已配置' : '未配置'} top span>
            <div className="flex items-center gap-2">
              <div className="relative min-w-0 flex-1">
                <input
                  type={feishuKeyRevealed ? 'text' : 'password'}
                  className={`${TEXT} pr-10`}
                  value={d.feishu}
                  placeholder="留空则不推送 · 可粘贴整条 webhook 链接"
                  spellCheck={false}
                  autoComplete="off"
                  onChange={(e) => {
                    set({ feishu: e.target.value })
                    if (feishuTest) setFeishuTest(null)
                  }}
                  onBlur={() => {
                    const key = extractFeishuKey(d.feishu)
                    if (key !== d.feishu) set({ feishu: key })
                  }}
                />
                <button
                  type="button"
                  title={feishuKeyRevealed ? '隐藏机器人 Key' : '显示机器人 Key'}
                  aria-label={feishuKeyRevealed ? '隐藏机器人 Key' : '显示机器人 Key'}
                  className="absolute right-1 top-1/2 flex h-8 w-8 -translate-y-1/2 cursor-pointer items-center justify-center rounded-md text-ink-3 transition-colors hover:bg-fill hover:text-ink-1"
                  onClick={() => setFeishuKeyRevealed((value) => !value)}
                >
                  {feishuKeyRevealed ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
              <button
                type="button"
                className="flex-none cursor-pointer rounded-[9px] border border-line bg-surface px-4 py-2 text-[15px] text-ink-2 transition-[border-color] hover:border-ink-3/40 disabled:opacity-45"
                disabled={!feishuKey || Boolean(feishuCardError) || feishuTest === 'busy'}
                onClick={() => void runFeishuTest()}
              >
                {feishuTest === 'busy' ? '测试中…' : '测试推送'}
              </button>
            </div>
            <div className="mt-1.5 text-[13px]" aria-live="polite">
              {feishuTest && feishuTest !== 'busy' ? (
                <span className={`inline-flex items-center gap-1.5 ${feishuTest.ok ? 'text-accent' : 'text-warn'}`}>
                  {feishuTest.ok && <Check size={14} />}
                  {feishuTest.message}
                </span>
              ) : (
                <span className="text-ink-3">推送一张使用当前页面草稿的样例卡片，成交为样例、非真实执行。</span>
              )}
            </div>
          </Row>

          <Row label="通知卡片" top span>
            <div>
              <div className="text-[15px] font-medium text-ink-1">{FEISHU_CARD_MODES[d.feishuCardMode].label}</div>
              <div className="mt-0.5 text-[13px] text-ink-3">{FEISHU_CARD_MODES[d.feishuCardMode].description}</div>
            </div>

            {/* 模板 / 自定义面向高级用户：收进折叠条，默认面只留摘要。收放范式同 AlgorithmEditor 的 AdvancedSettings。 */}
            <div className="mt-3 border-t border-line">
              <button
                type="button"
                className="flex w-full items-center justify-between py-3 text-[14px] font-semibold text-ink-3 transition-colors hover:text-ink-1 motion-reduce:transition-none"
                aria-expanded={feishuAdvancedOpen}
                onClick={() => setFeishuAdvancedOpen((open) => !open)}
              >
                <span>高级设置</span>
                <ChevronDown
                  size={15}
                  className={`transition-transform duration-200 motion-reduce:transition-none ${feishuAdvancedOpen ? 'rotate-180' : ''}`}
                  aria-hidden
                />
              </button>
              <div
                inert={!feishuAdvancedOpen}
                className={`grid transition-[grid-template-rows] duration-200 motion-reduce:transition-none ${feishuAdvancedOpen ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}
              >
                <div className="min-h-0 overflow-hidden">
                  <div className="pb-2" role="radiogroup" aria-label="通知卡片">
                    {FEISHU_CARD_MODE_ORDER.map((mode) => {
                      const meta = FEISHU_CARD_MODES[mode]
                      const selected = d.feishuCardMode === mode
                      return (
                        <div
                          key={mode}
                          className={`border-l-[3px] pl-3 transition-colors duration-200 motion-reduce:transition-none ${selected ? 'border-accent' : 'border-transparent'}`}
                        >
                          <button
                            type="button"
                            role="radio"
                            aria-checked={selected}
                            className="-mx-2 flex w-[calc(100%+1rem)] cursor-pointer items-start rounded-lg px-2 py-2.5 text-left transition-colors duration-200 hover:bg-fill focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent motion-reduce:transition-none"
                            onClick={() => {
                              if (selected) return
                              set({ feishuCardMode: mode })
                              setFeishuTest(null)
                              if (mode === 'default') setShowFeishuVariables(false)
                            }}
                          >
                            <span>
                              <span className={`block text-[15px] font-medium transition-colors duration-200 motion-reduce:transition-none ${selected ? 'text-ink-1' : 'text-ink-2'}`}>
                                {meta.label}
                              </span>
                              <span className="mt-0.5 block text-[13px] leading-relaxed text-ink-3">{meta.description}</span>
                            </span>
                          </button>
                          {mode !== 'default' && (
                            <div
                              inert={!selected}
                              className={`grid transition-[grid-template-rows] duration-200 motion-reduce:transition-none ${selected ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}
                            >
                              <div className="min-h-0 overflow-hidden">
                                {mode === 'template' ? (
                                  <div className="pt-1 pb-4">
                                    <label className="text-[13px] text-ink-2" htmlFor="feishu-template-id">模板 ID</label>
                                    <input
                                      id="feishu-template-id"
                                      className={`${TEXT} mt-1`}
                                      value={d.feishuTemplateId}
                                      spellCheck={false}
                                      onChange={(event) => {
                                        set({ feishuTemplateId: event.target.value })
                                        setFeishuTest(null)
                                      }}
                                    />
                                    <div className="mt-1.5 flex items-center justify-between gap-3 text-[13px]">
                                      <span className={feishuCardError ? 'text-warn' : 'text-ink-3'}>{feishuCardError ?? '模板可以使用 Axon 提供的通知变量'}</span>
                                      <button type="button" className="cursor-pointer text-ink-2 hover:text-ink-1" onClick={() => setShowFeishuVariables((value) => !value)}>
                                        {showFeishuVariables ? '收起变量' : '查看变量'}
                                      </button>
                                    </div>
                                    <div inert={!showFeishuVariables} className={`grid transition-[grid-template-rows] duration-200 motion-reduce:transition-none ${showFeishuVariables ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}>
                                      <div className="min-h-0 overflow-hidden">
                                        <div className="mt-2 flex flex-wrap gap-1.5 border-l-2 border-line pl-3">
                                          {FEISHU_TEMPLATE_VARIABLES.map((name) => <code key={name} className="text-[12px] text-ink-2">{name}</code>)}
                                        </div>
                                      </div>
                                    </div>
                                  </div>
                                ) : (
                                  <div className="pt-1 pb-4">
                                    <label className="text-[13px] text-ink-2" htmlFor="feishu-custom-card">卡片内容</label>
                                    <textarea
                                      id="feishu-custom-card"
                                      className={`${AREA} mt-1 min-h-52 resize-y`}
                                      value={d.feishuCardText}
                                      placeholder={'{\n  "header": { ... },\n  "elements": [ ... ]\n}'}
                                      spellCheck={false}
                                      onChange={(event) => {
                                        set({ feishuCardText: event.target.value })
                                        setFeishuTest(null)
                                      }}
                                    />
                                    <div className="mt-1.5 flex items-center justify-between gap-3 text-[13px]">
                                      <span className={feishuCardError ? 'text-warn' : 'text-ink-3'}>{feishuCardError ?? '格式有效，发送时保持原始卡片结构'}</span>
                                      <button
                                        type="button"
                                        className="cursor-pointer text-ink-2 hover:text-ink-1 disabled:cursor-not-allowed disabled:opacity-45"
                                        disabled={Boolean(feishuCardError)}
                                        onClick={() => {
                                          if (customCardResult?.config?.mode === 'custom') set({ feishuCardText: JSON.stringify(customCardResult.config.card, null, 2) })
                                        }}
                                      >
                                        格式化
                                      </button>
                                    </div>
                                  </div>
                                )}
                              </div>
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              </div>
            </div>
          </Row>
        </Section>
        </>
      )}

      {section === 'leverage' && (
        <>
          <Section label="杠杆设置">
          <div className="flex flex-wrap gap-x-8 gap-y-3 md:col-span-2">
          <div className="flex flex-col gap-1">
            <label htmlFor="edit-long-leverage" className="text-[14px] text-ink-2">
              {channelDescriptor?.ui.long_leverage_label ?? '做多杠杆'}
              {longLevErr && <span className="ml-1.5 text-[12px] text-warn">{longLevErr}</span>}
            </label>
            <LeverageInput
              limits={channelDescriptor?.leverage}
              id="edit-long-leverage"
              invalid={Boolean(longLevErr)}
              value={d.longLev}
              onChange={(longLev) => set({ longLev })}
            />
          </div>
          {showShortLeverage && (
            <div className="flex flex-col gap-1">
              <label htmlFor="edit-short-leverage" className="text-[14px] text-ink-2">
                {channelDescriptor?.ui.short_leverage_label ?? '做空杠杆'}
                <span className="ml-1.5 text-[12px] text-ink-3">0 = 不做空</span>
                {shortLevErr && <span className="ml-1.5 text-[12px] text-warn">{shortLevErr}</span>}
              </label>
              <LeverageInput
                limits={channelDescriptor?.leverage}
                id="edit-short-leverage"
                invalid={Boolean(shortLevErr)}
                value={d.shortLev}
                onChange={(shortLev) => set({ shortLev })}
              />
            </div>
          )}
          </div>
          </Section>
          <Section label="权重精度">
            <div className="w-fit">
              <label htmlFor="edit-weight-precision" className="sr-only">
                权重精度
              </label>
              <WeightPrecisionInput
                id="edit-weight-precision"
                value={d.weightPrecision}
                invalid={Boolean(weightPrecisionErr)}
                error={weightPrecisionErr}
                onChange={(weightPrecision) => set({ weightPrecision })}
              />
            </div>
          </Section>
        </>
      )}

      {section === 'symbols' && (
        <Section label="品种控制">
          <Row label="禁投" hint="永不建仓" top span>
          <SymbolTagInput
            id="edit-forbidden-symbols"
            value={d.forbidden}
            otherValue={d.risk}
            variant="forbidden"
            placeholder="输入禁投品种…"
            otherLabel="风险品种"
            onChange={(forbidden) => set({ forbidden })}
            onMoveFromOther={(symbols) => {
              const moving = new Set(symbols)
              set({
                forbidden: [...d.forbidden, ...symbols.filter((symbol) => !d.forbidden.includes(symbol))],
                risk: d.risk.filter((symbol) => !moving.has(symbol)),
              })
            }}
          />
        </Row>
        <Row label="风险品种" hint="仅减不加" top span>
          <SymbolTagInput
            id="edit-risk-symbols"
            value={d.risk}
            otherValue={d.forbidden}
            variant="risk"
            placeholder="输入风险品种…"
            otherLabel="禁投"
            onChange={(risk) => set({ risk })}
            onMoveFromOther={(symbols) => {
              const moving = new Set(symbols)
              set({
                forbidden: d.forbidden.filter((symbol) => !moving.has(symbol)),
                risk: [...d.risk, ...symbols.filter((symbol) => !d.risk.includes(symbol))],
              })
            }}
          />
          </Row>
          <p className="md:col-span-2 text-[12px] text-ink-3">Enter、Tab、逗号或空格确认；支持批量粘贴</p>
        </Section>
      )}

      {section === 'portfolio' && (
        <Section label="组合执行">
          <Row label="跟随组合" span>
          <Select<number | null>
            ariaLabel="跟随组合"
            searchable
            disabled={portfolios == null || Boolean(portfoliosError)}
            className="w-full justify-between px-3 py-2 text-[15px]"
            value={d.portfolioId ?? null}
            onChange={(v) => set({ portfolioId: v })}
            options={[
              { value: null, label: '不绑定组合', description: '账户不跟随任何目标持仓' },
              ...(portfolios ?? []).map((p) => ({
                value: p.id ?? null,
                label: p.name,
                description: [p.market, p.description].filter(Boolean).join(' · '),
                hint: p.id == null ? undefined : `#${p.id}`,
              })),
            ]}
          />
          {portfolios == null && !portfoliosError && <Skeleton className="mt-2 h-3 w-40" />}
          <ErrorNotice title="组合关系加载失败" error={portfoliosError} variant="compact" onRetry={refreshPortfolios} />
        </Row>
        <Row label="空仓写记录" hint="审计留痕">
          <Toggle on={d.writeEmpty} onClick={() => set({ writeEmpty: !d.writeEmpty })} />
        </Row>
        <Row label="执行超时" hint="单次上限" top>
          <div className="flex flex-col gap-1">
            <ExecutionTimeoutInput
              invalid={Boolean(timeoutErr)}
              value={d.executionTimeout}
              onChange={(executionTimeout) => set({ executionTimeout })}
            />
            <span className={`text-[12px] ${timeoutErr ? 'text-warn' : 'text-ink-3'}`}>
              {timeoutErr ?? '超时后停止开新单'}
            </span>
          </div>
          </Row>
        </Section>
      )}

      <EditSaveBar
        changes={changes}
        blocked={blocked}
        onCancel={resetDraft}
        onSave={() => void save()}
        error={saveError}
      />
    </section>
  )
}
