/**
 * 账户编辑总览 /accounts/:id/edit。
 *
 * 中长期信息架构：总览只扛浅字段 + 子系统入口；完整定时 / 执行算法各走子路由，
 * 避免长页嵌套重编辑器。保存仍为最小 PATCH + 底栏变更摘要。
 */

import { useCallback, useEffect, useState } from 'react'
import { useParams, useViewTransitionState } from 'react-router'
import { useNavigate } from '@/components/ui/nav'
import { Chip } from '@/components/ui/Card'
import { Select } from '@/components/ui/Select'
import { ExecutionTimeoutInput } from '@/features/account/ExecutionTimeoutInput'
import { executionTimeoutError } from '@/features/account/executionTimeout'
import { LeverageInput } from '@/features/account/LeverageInput'
import { leverageError } from '@/features/account/leverage'
import { getAccount, updateAccount } from '@/lib/api/accounts'
import { testFeishu, type TestResult } from '@/lib/api/init'
import { usePolling } from '@/lib/hooks/usePolling'
import { useDomainStore } from '@/stores/domain'
import { useChannelDescriptor } from '@/stores/channels'
import { useToastStore } from '@/stores/ui'
import { channelLabel } from '@/features/dashboard/display'
import { describeCron, marketForChannel } from '@/features/setup/cron'
import { describeAlgorithmRef, type AlgorithmRef } from '@/features/setup/algorithms'
import {
  AREA,
  TEXT,
  EditBreadcrumb,
  EditError,
  EditLoading,
  EditSaveBar,
  EntryRow,
  NumCell,
  Row,
  Section,
  Toggle,
  editShellVtName,
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
  forbidden: string
  risk: string
  weightPrecision: string
  executionTimeout: string
  writeEmpty: boolean
  tradeRules: string
  newConfig: string
}

function parseList(s: string): string[] {
  return s
    .split(/[\n,，\s]+/)
    .map((x) => x.trim())
    .filter(Boolean)
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

function parseJson(s: string): { value?: unknown; error?: string } {
  try {
    return { value: JSON.parse(s) }
  } catch (e) {
    return { error: e instanceof Error ? e.message : '无效 JSON' }
  }
}

function norm(v: unknown): string {
  return JSON.stringify(v ?? null)
}

function jsonText(v: Record<string, unknown> | null | undefined): string {
  if (v == null || (typeof v === 'object' && Object.keys(v).length === 0)) return ''
  return JSON.stringify(v, null, 2)
}

function controlOverrideCount(value: Record<string, unknown> | null): number {
  if (!value) return 0
  const countScope = (scope: unknown) =>
    scope && typeof scope === 'object' ? Object.values(scope).filter(Boolean).length : 0
  const operations = value.operations && typeof value.operations === 'object'
    ? Object.values(value.operations).reduce<number>((sum, operation) => {
        if (!operation || typeof operation !== 'object') return sum
        return sum + Object.values(operation).reduce<number>((scopeSum, scope) => scopeSum + countScope(scope), 0)
      }, 0)
    : 0
  const groups = value.groups && typeof value.groups === 'object'
    ? Object.values(value.groups).reduce<number>((sum, scope) => sum + countScope(scope), 0)
    : 0
  return operations + groups
}

function refOf(algo: Record<string, unknown> | null | undefined): AlgorithmRef | null {
  if (!algo || typeof algo.method !== 'string') return null
  return { method: algo.method, params: (algo.params ?? {}) as Record<string, unknown> }
}

function draftOf(acc: Account): Draft {
  return {
    name: acc.name,
    remark: acc.remark ?? '',
    feishu: acc.feishu_key ?? '',
    longLev: String(acc.long_leverage ?? ''),
    shortLev: String(acc.short_leverage ?? ''),
    portfolioId: acc.portfolio_id,
    forbidden: (acc.forbidden_symbols ?? []).join('\n'),
    risk: (acc.risk_symbols ?? []).join('\n'),
    weightPrecision: String(acc.weight_precision ?? ''),
    executionTimeout: String(acc.execution_timeout ?? ''),
    writeEmpty: Boolean(acc.write_empty_record),
    tradeRules: jsonText(acc.trade_rules),
    newConfig: '',
  }
}

function jsonDiff(text: string, original: unknown): { changed: boolean; value?: unknown } {
  const t = text.trim()
  if (!t) return original == null ? { changed: false } : { changed: true, value: null }
  const p = parseJson(t)
  if (p.error !== undefined) return { changed: false }
  return { changed: norm(p.value) !== norm(original), value: p.value }
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

  const fb = parseList(draft.forbidden)
  if (!sameList(fb, acc.forbidden_symbols ?? [])) patch.forbidden_symbols = fb.length ? fb : null
  const rk = parseList(draft.risk)
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

  const tr = jsonDiff(draft.tradeRules, acc.trade_rules)
  if (tr.changed) patch.trade_rules = tr.value as Record<string, unknown> | null

  if (draft.newConfig.trim()) {
    const cfg = parseJson(draft.newConfig)
    if (cfg.error === undefined) patch.account_config = cfg.value as Record<string, unknown>
  }
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
  trade_rules: '交易规则',
  account_config: '连接密钥',
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

export function AccountEditPage() {
  const { id } = useParams()
  const accountId = Number(id)
  const navigate = useNavigate()
  const toast = useToastStore((s) => s.toast)
  const accounts = useDomainStore((s) => s.accounts)
  const portfolios = useDomainStore((s) => s.portfolios)
  const refreshAccounts = useDomainStore((s) => s.refreshAccounts)

  // 与详情 hero 账户名配对 FLIP：进编辑 / 回详情时挂同一 ``account-name-*``。
  const tEdit = useViewTransitionState(`/accounts/${accountId}/edit`)
  const tDetail = useViewTransitionState(`/accounts/${accountId}`)
  const nameVt = tEdit || tDetail

  const account = usePolling(useCallback((s: AbortSignal) => getAccount(accountId, s), [accountId]), 0)
  const acc = account.data
  const channelDescriptor = useChannelDescriptor(acc?.trade_channel)
  const item = accounts?.find((a) => a.account_id === accountId) ?? null
  // 首帧用仪表盘缓存名挂共享元素，避免等 getAccount 时落点缺失、FLIP 断档。
  const displayName = acc?.name ?? item?.name

  const [ready, setReady] = useState(false)
  const [advanced, setAdvanced] = useState(false)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [feishuTest, setFeishuTest] = useState<TestResult | 'busy' | null>(null)
  useEffect(() => {
    if (!acc || ready) return
    setDraft(draftOf(acc))
    setReady(true)
  }, [acc, ready])

  /** 标题行账户名（可挂 FLIP）；「编辑 ·」前缀不进共享身份。 */
  const titleName = (
    <span className="text-[18px] font-[640]">
      编辑 ·{' '}
      <span
        style={
          nameVt && displayName != null
            ? { viewTransitionName: `account-name-${accountId}` }
            : undefined
        }
      >
        {displayName ?? `账户 #${accountId}`}
      </span>
    </span>
  )

  if (account.error && !acc)
    return <EditError id={accountId} name={displayName} message={account.error.message} />

  if (account.loading || !ready || !acc || !draft)
    return (
      <section className="pb-24">
        <EditBreadcrumb id={accountId} name={displayName} />
        <div className="mt-3 flex flex-wrap items-baseline gap-3">{titleName}</div>
        <EditLoading id={accountId} name={displayName} bare />
      </section>
    )

  const showShortLeverage = channelDescriptor?.ui.show_short_leverage ?? acc.market !== 'ashare'
  const d = draft
  const set = (patch: Partial<Draft>) => setDraft((prev) => (prev ? { ...prev, ...patch } : prev))
  const market = marketForChannel(acc.trade_channel)

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

  const cronExpr = acc.cron_expr ?? ''
  const timerSummary = !cronExpr.trim()
    ? '已关 · 仅手动'
    : (describeCron(market, cronExpr) ?? '自定义节奏')

  const tradeSum = describeAlgorithmRef(refOf(acc.algorithm as Record<string, unknown> | null), market)
  const emptySum = describeAlgorithmRef(
    refOf(acc.empty_positions_algorithm as Record<string, unknown> | null),
    market,
  )
  const algoSummary = emptySum === '未设置' ? tradeSum : `${tradeSum} · 清仓 ${emptySum}`

  const jsonEntries: string[] = [d.tradeRules, d.newConfig]
  const jsonErr = jsonEntries.map((t) => (t.trim() ? parseJson(t).error : undefined)).find(Boolean) ?? null

  // 杠杆边界校验由渠道目录给出；空=不改，0=该方向不启用。与服务端同口径，
  // 避免像旧版那样「填 999 也能保存、错误配置直进仓位计算」。
  const leverageOptions = { ...channelDescriptor?.leverage, allowEmpty: true }
  const longLevErr = leverageError(d.longLev, leverageOptions)
  const shortLevErr = showShortLeverage ? leverageError(d.shortLev, leverageOptions) : null
  // 执行总超时必须是正整数（服务端 >= 1）：这道兜底不允许按账户关掉。
  const timeoutErr = executionTimeoutError(d.executionTimeout, { allowEmpty: true })
  const levErr = longLevErr ?? shortLevErr

  const patch = buildPatch(d, acc, showShortLeverage)
  const changes = summarize(patch, acc, portfolios)
  const dirty = changes.length > 0
  const blocked = Boolean(jsonErr || levErr || timeoutErr)

  const save = async () => {
    if (jsonErr) return toast(`高级 JSON 有误：${jsonErr}`)
    if (levErr) return toast(`杠杆有误：${levErr}`)
    if (timeoutErr) return toast(`执行超时有误：${timeoutErr}`)
    if (!dirty) return toast('没有改动')
    try {
      await updateAccount(accountId, patch)
      toast('账户已更新')
      void refreshAccounts()
      account.refresh()
      navigate(`/accounts/${accountId}`)
    } catch (e) {
      toast(`更新失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  const jsonRow = (key: 'tradeRules', label: string) => {
    const text = d[key]
    const err = text.trim() ? parseJson(text).error : undefined
    return (
      <Row label={label} top span>
        <textarea
          className={AREA}
          rows={3}
          value={text}
          spellCheck={false}
          placeholder="留空 = 不设置 / 不改"
          onChange={(e) => set({ [key]: e.target.value })}
        />
        {err && <div className="mt-1 text-[12px] text-bad">JSON 有误：{err}</div>}
      </Row>
    )
  }

  return (
    <section className="pb-24">
      <EditBreadcrumb id={accountId} name={acc.name} />
      <div className="mt-3 flex flex-wrap items-baseline gap-3">
        {titleName}
        <Chip>{channelLabel(acc.trade_channel, acc.market)}</Chip>
      </div>

      <div className="mt-3 border-l-2 border-warn/60 bg-warn-tint/50 py-2 pl-3 pr-2 text-[13px] text-ink-2">
        <b className="text-ink-1">影响半径</b> · 此账户{acc.is_started ? '自动执行中' : '已暂停'}
        {item && ` · 持仓 ${item.holdings_count} 只`} · 改动不会立刻下单，下次调仓生效。渠道与市场不可更改。
      </div>

      <Section label="基本">
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

      <Section label="杠杆">
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
          <NumCell label="权重精度" value={d.weightPrecision} onChange={(v) => set({ weightPrecision: v })} />
        </div>
      </Section>

      <Section label="节奏与算法">
        <EntryRow
          label="定时"
          hint="自动调仓"
          summary={timerSummary}
          to={`/accounts/${accountId}/edit/timer`}
          shellVtName={editShellVtName(accountId, 'timer')}
        />
        <EntryRow
          label="流控"
          hint="请求节奏"
          summary={`${acc.account_control_preset === 'ctp' ? 'CTP' : '默认'} · ${controlOverrideCount(acc.account_control_override) ? `${controlOverrideCount(acc.account_control_override)} 处自定义` : '全部使用预设值'}`}
          to={`/accounts/${accountId}/edit/control`}
          shellVtName={editShellVtName(accountId, 'control')}
        />
        <EntryRow
          label="执行算法"
          hint="下单 / 清仓"
          summary={algoSummary}
          to={`/accounts/${accountId}/edit/algorithm`}
          shellVtName={editShellVtName(accountId, 'algorithm')}
        />
      </Section>

      <Section label="品种控制">
        <Row label="禁投" hint="永不建仓" top>
          <textarea
            className={`${AREA} min-h-[52px]`}
            rows={2}
            value={d.forbidden}
            spellCheck={false}
            placeholder="逗号或换行分隔"
            onChange={(e) => set({ forbidden: e.target.value })}
          />
        </Row>
        <Row label="风险品种" hint="仅减不加" top>
          <textarea
            className={`${AREA} min-h-[52px]`}
            rows={2}
            value={d.risk}
            spellCheck={false}
            placeholder="可选"
            onChange={(e) => set({ risk: e.target.value })}
          />
        </Row>
      </Section>

      <Section label="组合与执行">
        <Row label="跟随组合" span>
          <Select<number | null>
            ariaLabel="跟随组合"
            searchable
            className="w-full justify-between px-3 py-2 text-[14px]"
            value={d.portfolioId ?? null}
            onChange={(v) => set({ portfolioId: v })}
            options={[
              { value: null, label: '不绑定组合' },
              ...(portfolios ?? []).map((p) => ({ value: p.id ?? null, label: p.name })),
            ]}
          />
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

      <button
        type="button"
        className="mx-0.5 mt-7 flex w-full cursor-pointer items-center gap-3 border-0 bg-transparent p-0 text-left"
        onClick={() => setAdvanced((v) => !v)}
      >
        <span className="text-[11px] font-semibold tracking-wide text-ink-3">
          {advanced ? '▾' : '▸'} 高级 · JSON 规则与换密钥
        </span>
        <span className="h-px flex-1 bg-line" />
      </button>
      {advanced && (
        <div className="mt-2 grid grid-cols-1 gap-x-8 gap-y-3 md:grid-cols-2">
          {jsonRow('tradeRules', 'trade_rules')}
          <Row label="换连接密钥" hint="只写 · 不回显" top span>
            <textarea
              className={AREA}
              rows={3}
              value={d.newConfig}
              spellCheck={false}
              placeholder="填入新 account_config（JSON）整体替换；留空 = 不改"
              onChange={(e) => set({ newConfig: e.target.value })}
            />
            {d.newConfig.trim() && parseJson(d.newConfig).error && (
              <div className="mt-1 text-[12px] text-bad">JSON 有误：{parseJson(d.newConfig).error}</div>
            )}
          </Row>
        </div>
      )}

      <EditSaveBar
        changes={changes}
        blocked={blocked}
        cancelTo={`/accounts/${accountId}`}
        onSave={() => void save()}
      />
    </section>
  )
}
