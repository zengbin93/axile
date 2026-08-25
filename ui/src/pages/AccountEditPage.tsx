/**
 * 账户浅配置页 /accounts/:id/edit/*。
 *
 * 基本信息、杠杆、品种控制、组合执行各走可直达子路由；连接设置、定时、算法、流控
 * 仍由各自的完整编辑器承载。保存保持最小 PATCH + 底栏变更摘要。
 */

import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router'
import { useNavigate } from '@/components/ui/nav'
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
import { getAccount, updateAccount } from '@/lib/api/accounts'
import { testFeishu, type TestResult } from '@/lib/api/init'
import { usePolling } from '@/lib/hooks/usePolling'
import { useDomainStore } from '@/stores/domain'
import { useChannelCatalogStore, useChannelDescriptor } from '@/stores/channels'
import { useToastStore } from '@/stores/ui'
import {
  TEXT,
  EditError,
  EditLoading,
  EditSaveBar,
  Row,
  Section,
  Toggle,
} from '@/features/account/editUi'
import type { Account, PortfolioLite } from '@/types/api'

/** 总览草稿：不含定时 / 算法（各在子页独立保存）。 */
interface Draft {
  name: string
  remark: string
  feishu: string
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
  return {
    name: acc.name,
    remark: acc.remark ?? '',
    feishu: acc.feishu_key ?? '',
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

function buildPatch(draft: Draft, acc: Account, showShortLeverage: boolean): Partial<Account> {
  const patch: Partial<Account> = {}
  const name = draft.name.trim()
  if (name && name !== acc.name) patch.name = name
  if (draft.remark !== (acc.remark ?? '')) patch.remark = draft.remark || null
  const feishuKey = extractFeishuKey(draft.feishu)
  if (feishuKey !== (acc.feishu_key ?? '')) patch.feishu_key = feishuKey || null

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
  const navigate = useNavigate()
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
  const item = accounts?.find((a) => a.account_id === accountId) ?? null
  // 首帧用仪表盘缓存名挂共享元素，避免等 getAccount 时落点缺失、FLIP 断档。
  const displayName = acc?.name ?? item?.name

  const [ready, setReady] = useState(false)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [feishuTest, setFeishuTest] = useState<TestResult | 'busy' | null>(null)
  const [saveError, setSaveError] = useState<Error | null>(null)
  useEffect(() => {
    if (!acc || ready) return
    setDraft(draftOf(acc))
    setReady(true)
  }, [acc, ready])

  /** 统一页头标题行（页名 · 账户名 + 渠道 chip）；账户名 FLIP 门控在原子内部。 */
  const titleName = (
    <AccountPageTitle
      accountId={accountId}
      page={SECTION_TITLE[section]}
      name={displayName}
      channel={acc?.trade_channel}
      market={acc?.market}
    />
  )

  if (account.error && !acc)
    return <EditError error={account.error} onRetry={account.refresh} />

  if (account.loading || !ready || !acc || !draft || (channelDescriptor == null && channelCatalogLoading))
    return (
      <section className="pb-24">
        <div className="flex flex-wrap items-baseline gap-3">{titleName}</div>
        <EditLoading bare />
      </section>
    )

  const showShortLeverage = channelDescriptor?.ui.show_short_leverage ?? true
  const d = draft
  const set = (patch: Partial<Draft>) => {
    setSaveError(null)
    setDraft((prev) => (prev ? { ...prev, ...patch } : prev))
  }
  // 飞书 key 容忍粘贴整条 webhook 链接：测试与保存都用规整后的裸 key
  // （后端 /init/test-feishu 无状态，测的就是请求体里这串，故可存盘前先测）。
  const feishuKey = extractFeishuKey(d.feishu)
  const runFeishuTest = async () => {
    setFeishuTest('busy')
    try {
      setFeishuTest(await testFeishu(feishuKey))
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
    levErr || timeoutErr || weightPrecisionErr || portfolios == null || portfoliosError || channelCatalogError,
  )

  const save = async () => {
    if (levErr) return toast(`杠杆有误：${levErr}`)
    if (timeoutErr) return toast(`执行超时有误：${timeoutErr}`)
    if (weightPrecisionErr) return toast(`权重精度有误：${weightPrecisionErr}`)
    if (!dirty) return toast('没有改动')
    setSaveError(null)
    try {
      await updateAccount(accountId, patch)
      toast('账户已更新')
      void refreshAccounts()
      account.refresh()
      navigate(`/accounts/${accountId}`)
    } catch (e) {
      setSaveError(e instanceof Error ? e : new Error(String(e)))
    }
  }

  return (
    <section className="pb-24">
      <div className="flex flex-wrap items-baseline gap-3">{titleName}</div>

      <div className="mt-3 border-l-2 border-warn/60 bg-warn-tint/50 py-2 pl-3 pr-2 text-[13px] text-ink-2">
        修改不会立即下单，从下次调仓开始生效。
      </div>

      {section === 'basic' && (
        <Section label="基本信息">
          <Row label="名称">
            <input className={TEXT} value={d.name} onChange={(e) => set({ name: e.target.value })} />
          </Row>
        <Row label="备注">
          <input className={TEXT} value={d.remark} placeholder="可选" onChange={(e) => set({ remark: e.target.value })} />
        </Row>
        <Row label="飞书通知" hint={feishuKey ? '已配置' : '未配置'} top span>
          <div className="flex items-center gap-2">
            <input
              className={`${TEXT} min-w-0 flex-1`}
              value={d.feishu}
              placeholder="留空则不推送 · 可粘贴整条 webhook 链接"
              spellCheck={false}
              onChange={(e) => {
                set({ feishu: e.target.value })
                if (feishuTest) setFeishuTest(null)
              }}
              onBlur={() => {
                const k = extractFeishuKey(d.feishu)
                if (k !== d.feishu) set({ feishu: k })
              }}
            />
            <button
              type="button"
              className="flex-none cursor-pointer rounded-[9px] border border-line bg-surface px-4 py-2 text-[14px] text-ink-2 transition-[border-color] hover:border-ink-3/40 disabled:opacity-45"
              disabled={!feishuKey || feishuTest === 'busy'}
              onClick={() => void runFeishuTest()}
            >
              {feishuTest === 'busy' ? '测试中…' : '测试推送'}
            </button>
          </div>
          <div className="mt-1.5 text-[12px]" aria-live="polite">
            {feishuTest && feishuTest !== 'busy' ? (
              <span className={feishuTest.ok ? 'text-accent' : 'text-warn'}>
                {feishuTest.ok ? '✓ ' : '✗ '}
                {feishuTest.message}
              </span>
            ) : (
              <span className="text-ink-3">
                飞书自定义机器人 webhook 的 key（.../hook/ 后那串）;「测试推送」会真发一张卡片到群里确认联通。
              </span>
            )}
          </div>
        </Row>
        </Section>
      )}

      {section === 'leverage' && (
        <Section label="杠杆设置">
          <div className="flex flex-wrap gap-x-8 gap-y-3 md:col-span-2">
          <div className="flex flex-col gap-1">
            <label htmlFor="edit-long-leverage" className="text-[13px] text-ink-2">
              {channelDescriptor?.ui.long_leverage_label ?? '做多杠杆'}
              {longLevErr && <span className="ml-1.5 text-[11px] text-warn">{longLevErr}</span>}
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
              <label htmlFor="edit-short-leverage" className="text-[13px] text-ink-2">
                {channelDescriptor?.ui.short_leverage_label ?? '做空杠杆'}
                <span className="ml-1.5 text-[11px] text-ink-3">0 = 不做空</span>
                {shortLevErr && <span className="ml-1.5 text-[11px] text-warn">{shortLevErr}</span>}
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
          <div className="flex flex-col gap-1">
            <label htmlFor="edit-weight-precision" className="text-[13px] text-ink-2">
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
          </div>
        </Section>
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
        </Section>
      )}

      {section === 'portfolio' && (
        <Section label="组合执行">
          <Row label="跟随组合" span>
          <Select<number | null>
            ariaLabel="跟随组合"
            searchable
            disabled={portfolios == null || Boolean(portfoliosError)}
            className="w-full justify-between px-3 py-2 text-[14px]"
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
            <span className={`text-[11px] ${timeoutErr ? 'text-warn' : 'text-ink-3'}`}>
              {timeoutErr ?? '超时后停止开新单'}
            </span>
          </div>
          </Row>
        </Section>
      )}

      <EditSaveBar
        changes={changes}
        blocked={blocked}
        cancelTo={`/accounts/${accountId}`}
        onSave={() => void save()}
        error={saveError}
      />
    </section>
  )
}
