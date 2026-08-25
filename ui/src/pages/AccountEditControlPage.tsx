/** 账户流控结构化编辑页。界面只展示中文业务语义，内部键仅用于数据索引。 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router'
import { useNavigate } from '@/components/ui/nav'
import { Chip } from '@/components/ui/Card'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { Select } from '@/components/ui/Select'
import {
  EditBreadcrumb,
  EditError,
  EditLoading,
  EditSaveBar,
  EditWorktopBar,
  Section,
  editShellVtName,
} from '@/features/account/editUi'
import { channelLabel } from '@/features/dashboard/display'
import { getAccount, getAccountControlPolicy, updateAccount } from '@/lib/api/accounts'
import { usePolling } from '@/lib/hooks/usePolling'
import { useDomainStore } from '@/stores/domain'
import { useToastStore } from '@/stores/ui'
import type {
  Account,
  AccountControlOperationMeta,
  AccountControlOperationOverride,
  AccountControlOperationPolicy,
  AccountControlOverride,
  AccountControlPolicy,
  AccountControlPolicyEditorModel,
  AccountControlRule,
  AccountControlRuleOverride,
  AccountControlScope,
  AccountControlScopeOverride,
  AccountControlTrigger,
} from '@/types/api'

type RuleKey = 'per_minute' | 'per_day' | 'min_interval_ms'
type ScopeKey = 'account' | 'symbol'

const RULES: { key: RuleKey; label: string; unit: string }[] = [
  { key: 'per_minute', label: '每分钟额度', unit: '次' },
  { key: 'per_day', label: '每日额度', unit: '次' },
  { key: 'min_interval_ms', label: '最小间隔', unit: '毫秒' },
]

const COMMON_KEYS = ['place_order', 'cancel_order', 'query_order']

function cloneOverride(value: AccountControlOverride | null): AccountControlOverride {
  return value
    ? structuredClone(value)
    : { operations: {}, groups: {} }
}

function normalizedOverride(value: AccountControlOverride): AccountControlOverride | null {
  const operations = Object.fromEntries(
    Object.entries(value.operations ?? {}).filter(([, operation]) =>
      Object.values(operation ?? {}).some((scope) => scope && Object.values(scope).some(Boolean)),
    ),
  )
  const groups = Object.fromEntries(
    Object.entries(value.groups ?? {}).filter(([, scope]) => scope && Object.values(scope).some(Boolean)),
  )
  if (!Object.keys(operations).length && !Object.keys(groups).length && !value.timezone) return null
  return { ...(value.timezone ? { timezone: value.timezone } : {}), operations, groups }
}

function countOverrides(value: AccountControlOverride | null): number {
  if (!value) return 0
  const operationCount = Object.values(value.operations ?? {}).reduce(
    (sum, operation) =>
      sum + Object.values(operation ?? {}).reduce((scopeSum, scope) => scopeSum + Object.values(scope ?? {}).filter(Boolean).length, 0),
    0,
  )
  const groupCount = Object.values(value.groups ?? {}).reduce(
    (sum, scope) => sum + Object.values(scope ?? {}).filter(Boolean).length,
    0,
  )
  return operationCount + groupCount
}

function resolveRule(base: AccountControlRule | null | undefined, override: AccountControlRuleOverride | null | undefined): AccountControlRule | null {
  if (!override) return base ?? null
  if (!base && override.limit == null) return null
  return {
    limit: override.limit ?? base?.limit ?? 1,
    on_trigger: override.on_trigger ?? base?.on_trigger ?? 'wait',
  }
}

function resolveScope(base: AccountControlScope | null | undefined, override: AccountControlScopeOverride | null | undefined): AccountControlScope {
  return {
    per_minute: resolveRule(base?.per_minute, override?.per_minute),
    per_day: resolveRule(base?.per_day, override?.per_day),
    min_interval_ms: resolveRule(base?.min_interval_ms, override?.min_interval_ms),
  }
}

function resolvePolicy(base: AccountControlPolicy, override: AccountControlOverride): AccountControlPolicy {
  const operations = { ...base.operations }
  for (const [key, operationOverride] of Object.entries(override.operations ?? {})) {
    const current = operations[key] ?? { account: {} }
    operations[key] = {
      account: resolveScope(current.account, operationOverride.account),
      symbol: current.symbol || operationOverride.symbol ? resolveScope(current.symbol, operationOverride.symbol) : null,
    }
  }
  const groups = { ...base.groups }
  for (const [key, groupOverride] of Object.entries(override.groups ?? {})) {
    groups[key] = resolveScope(groups[key], groupOverride)
  }
  return { timezone: override.timezone ?? base.timezone, operations, groups }
}

function ruleText(rule: AccountControlRule | null | undefined, key: RuleKey): string {
  if (!rule) return key === 'per_day' ? '不限每日' : '不限制'
  if (key === 'per_minute') return `${rule.limit} 次/分钟`
  if (key === 'per_day') return `${rule.limit} 次/日`
  return `间隔 ${rule.limit} 毫秒`
}

function scopeSummary(scope: AccountControlScope | null | undefined): string {
  return RULES.map(({ key }) => ruleText(scope?.[key], key)).join(' · ')
}

function ruleError(key: RuleKey, rule: AccountControlRuleOverride | null | undefined): string | null {
  if (!rule) return null
  if (!Number.isInteger(rule.limit) || (rule.limit ?? -1) < 0) return '请输入不小于 0 的整数'
  if (key === 'min_interval_ms' && rule.limit === 0) return '最小间隔必须大于 0'
  return null
}

function ControlRuleField({
  ruleKey,
  preset,
  custom,
  onChange,
}: {
  ruleKey: RuleKey
  preset: AccountControlRule | null | undefined
  custom: AccountControlRuleOverride | null | undefined
  onChange: (next: AccountControlRuleOverride | null) => void
}) {
  const meta = RULES.find((item) => item.key === ruleKey)!
  const active = Boolean(custom)
  const effective = resolveRule(preset, custom)
  const error = ruleError(ruleKey, custom)
  const zeroWarning = ruleKey !== 'min_interval_ms' && custom?.limit === 0
  const begin = () => onChange({ limit: effective?.limit ?? 1, on_trigger: effective?.on_trigger ?? 'wait' })

  return (
    <div className="border-t border-line/70 py-3 first:border-t-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="w-24 flex-none text-[13px] text-ink-2">{meta.label}</span>
        <span className="num min-w-0 flex-1 text-[13px] text-ink-1">
          {effective ? `${effective.limit} ${meta.unit}` : '不限制'}
          {active && <span className="ml-2 text-[11px] text-ink-3">预设 {preset ? `${preset.limit} ${meta.unit}` : '不限制'}</span>}
        </span>
        <span className={`text-[11px] ${active ? 'text-accent' : 'text-ink-3'}`}>
          {active ? '自定义' : '使用预设值'}
        </span>
        <button
          type="button"
          className="cursor-pointer border-0 bg-transparent text-[12px] font-semibold text-accent"
          onClick={() => (active ? onChange(null) : begin())}
        >
          {active ? '恢复预设值' : preset ? '修改' : '设置限制'}
        </button>
      </div>
      <div
        inert={!active}
        className={`grid transition-[grid-template-rows] duration-200 motion-reduce:transition-none ${active ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}
      >
        <div className="min-h-0 overflow-hidden">
          <div className="ml-0 mt-2 flex flex-col gap-2 rounded-[9px] bg-canvas/70 px-3 py-3 sm:ml-24 sm:flex-row sm:items-center">
            <label className="flex items-center gap-2 text-[12px] text-ink-2">
              <input
                className="num w-24 rounded-[8px] border border-ink-3/25 bg-surface px-2.5 py-1.5 text-right text-[13px] outline-none focus:border-ink-2"
                type="number"
                min={ruleKey === 'min_interval_ms' ? 1 : 0}
                step={1}
                value={custom?.limit ?? ''}
                onChange={(event) => onChange({ ...custom, limit: Number(event.target.value), on_trigger: custom?.on_trigger ?? 'wait' })}
              />
              {meta.unit}
            </label>
            <span className="text-[12px] text-ink-3">达到额度后</span>
            <Select<AccountControlTrigger>
              ariaLabel={`${meta.label}达到额度后的动作`}
              value={custom?.on_trigger ?? 'wait'}
              onChange={(on_trigger) => onChange({ ...custom, limit: custom?.limit ?? effective?.limit ?? 1, on_trigger })}
              options={[
                { value: 'wait', label: '等待后继续', hint: '等待至下一可用时刻' },
                { value: 'block', label: '立即阻断', hint: '本次请求不再等待' },
              ]}
            />
          </div>
          {(error || zeroWarning) && (
            <p className="ml-0 mt-1 text-[11px] text-warn sm:ml-24">
              {error ?? '0 次会阻断所有此类请求。'}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

function ControlScopeEditor({
  label,
  preset,
  custom,
  onChange,
}: {
  label: string
  preset: AccountControlScope | null | undefined
  custom: AccountControlScopeOverride | null | undefined
  onChange: (next: AccountControlScopeOverride | null) => void
}) {
  const setRule = (key: RuleKey, rule: AccountControlRuleOverride | null) => {
    const next = { ...(custom ?? {}), [key]: rule }
    if (!rule) delete next[key]
    onChange(Object.values(next).some(Boolean) ? next : null)
  }
  return (
    <div className="mt-4">
      <h3 className="text-[13px] font-semibold text-ink-1">{label}</h3>
      <div className="mt-1">
        {RULES.map(({ key }) => (
          <ControlRuleField key={key} ruleKey={key} preset={preset?.[key]} custom={custom?.[key]} onChange={(rule) => setRule(key, rule)} />
        ))}
      </div>
    </div>
  )
}

function ControlOperationRow({
  meta,
  preset,
  effective,
  custom,
  open,
  onToggle,
  onChange,
}: {
  meta: AccountControlOperationMeta
  preset: AccountControlOperationPolicy
  effective: AccountControlOperationPolicy
  custom: AccountControlOperationOverride | undefined
  open: boolean
  onToggle: () => void
  onChange: (next: AccountControlOperationOverride | null) => void
}) {
  const customCount = Object.values(custom ?? {}).reduce((sum, scope) => sum + Object.values(scope ?? {}).filter(Boolean).length, 0)
  const setScope = (key: ScopeKey, scope: AccountControlScopeOverride | null) => {
    const next = { ...(custom ?? {}), [key]: scope }
    if (!scope) delete next[key]
    onChange(Object.values(next).some(Boolean) ? next : null)
  }
  return (
    <div className="rounded-[12px] border border-line bg-surface">
      <button type="button" className="w-full cursor-pointer border-0 bg-transparent px-4 py-3.5 text-left" onClick={onToggle} aria-expanded={open}>
        <div className="flex items-center gap-3">
          <span className="min-w-0 flex-1 text-[14px] font-semibold text-ink-1">{meta.display_name}</span>
          <span className={`text-[11px] ${customCount ? 'text-accent' : 'text-ink-3'}`}>
            {customCount ? `${customCount} 处自定义` : '全部使用预设值'}
          </span>
          <span className="text-[12px] text-ink-3" aria-hidden>{open ? '⌄' : '›'}</span>
        </div>
        <div className="mt-1.5 space-y-1 text-[12px] text-ink-2">
          <div><span className="mr-2 text-ink-3">账户合计</span>{scopeSummary(effective.account)}</div>
          <div><span className="mr-2 text-ink-3">每个品种</span>{scopeSummary(effective.symbol)}</div>
        </div>
      </button>
      <div inert={!open} className={`grid transition-[grid-template-rows] duration-200 motion-reduce:transition-none ${open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}>
        <div className="min-h-0 overflow-hidden">
          <div className="border-t border-line px-4 pb-4">
            <ControlScopeEditor label="账户合计" preset={preset.account} custom={custom?.account} onChange={(scope) => setScope('account', scope)} />
            <ControlScopeEditor label="每个品种" preset={preset.symbol} custom={custom?.symbol} onChange={(scope) => setScope('symbol', scope)} />
          </div>
        </div>
      </div>
    </div>
  )
}

export function AccountEditControlPage() {
  const { id } = useParams()
  const accountId = Number(id)
  const navigate = useNavigate()
  const toast = useToastStore((state) => state.toast)
  const refreshAccounts = useDomainStore((state) => state.refreshAccounts)
  const account = usePolling(useCallback((signal: AbortSignal) => getAccount(accountId, signal), [accountId]), {
    queryKey: `account:${accountId}`,
    intervalMs: 0,
  })
  const [model, setModel] = useState<AccountControlPolicyEditorModel | null>(null)
  const [presetKey, setPresetKey] = useState('')
  const [override, setOverride] = useState<AccountControlOverride>({ operations: {}, groups: {} })
  const [openKey, setOpenKey] = useState<string | null>(null)
  const [otherOpen, setOtherOpen] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [previewNote, setPreviewNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [policyError, setPolicyError] = useState<Error | null>(null)
  const [previewError, setPreviewError] = useState<Error | null>(null)
  const [saveError, setSaveError] = useState<Error | null>(null)

  const loadPolicy = useCallback(() => {
    if (!account.data) return
    setPolicyError(null)
    getAccountControlPolicy(accountId)
      .then((value) => {
        setModel(value)
        setPresetKey(value.preset_key)
        setOverride(cloneOverride(value.override))
      })
      .catch((error) => setPolicyError(error instanceof Error ? error : new Error(String(error))))
  }, [account.data, accountId])

  useEffect(() => {
    if (!model) loadPolicy()
  }, [loadPolicy, model])

  const acc = account.data
  const normalized = normalizedOverride(override)
  const effective = useMemo(() => model ? resolvePolicy(model.preset_policy, override) : null, [model, override])
  const overrideCount = countOverrides(normalized)
  const originalOverride = model?.override ?? null
  const dirtyPreset = Boolean(acc && presetKey !== acc.account_control_preset)
  const dirtyOverride = JSON.stringify(normalized) !== JSON.stringify(originalOverride)
  const dirty = dirtyPreset || dirtyOverride
  const errors = Object.values(override.operations ?? {}).flatMap((operation) =>
    Object.values(operation ?? {}).flatMap((scope) => RULES.map(({ key }) => ruleError(key, scope?.[key])).filter(Boolean)),
  ).concat(Object.values(override.groups ?? {}).flatMap((scope) => RULES.map(({ key }) => ruleError(key, scope?.[key])).filter(Boolean)))

  if (account.error && !acc) return <EditError id={accountId} error={account.error} onRetry={account.refresh} />
  if (policyError && !model)
    return (
      <EditError
        id={accountId}
        name={acc?.name}
        channel={acc?.trade_channel}
        error={policyError}
        onRetry={loadPolicy}
      />
    )
  if (!acc || !model || !effective)
    return <EditLoading id={accountId} name={acc?.name} channel={acc?.trade_channel} leaf="流控" />

  const switchPreset = async (nextKey: string) => {
    if (nextKey === presetKey) return
    const previous = presetKey
    setPresetKey(nextKey)
    setPreviewing(true)
    setPreviewError(null)
    try {
      const preview = await getAccountControlPolicy(accountId, nextKey)
      setModel(preview)
      setPreviewNote(`已按 ${preview.preset_display_name} 预设方案重新计算，${overrideCount} 处账户设置保持不变。`)
    } catch (error) {
      setPresetKey(previous)
      setPreviewError(error instanceof Error ? error : new Error(String(error)))
    } finally {
      setPreviewing(false)
    }
  }

  const setOperation = (key: string, next: AccountControlOperationOverride | null) => {
    setOverride((current) => {
      const operations = { ...current.operations }
      if (next) operations[key] = next
      else delete operations[key]
      return { ...current, operations }
    })
  }

  const operationRows = model.operations.filter((meta) => effective.operations[meta.key])
  const common = operationRows.filter((meta) => COMMON_KEYS.includes(meta.key) || Boolean(override.operations[meta.key]))
  const other = operationRows.filter((meta) => !common.includes(meta))
  const renderOperation = (meta: AccountControlOperationMeta) => (
    <ControlOperationRow
      key={meta.key}
      meta={meta}
      preset={model.preset_policy.operations[meta.key] ?? { account: {} }}
      effective={effective.operations[meta.key]}
      custom={override.operations[meta.key]}
      open={openKey === meta.key}
      onToggle={() => setOpenKey((value) => value === meta.key ? null : meta.key)}
      onChange={(next) => setOperation(meta.key, next)}
    />
  )

  const changes = dirty ? [
    ...(dirtyPreset ? [`预设方案改为${model.preset_display_name}`] : []),
    ...(dirtyOverride ? [`流控自定义值 ${overrideCount} 处`] : []),
  ] : []

  const save = async () => {
    if (errors.length) return toast(`流控设置有误：${errors[0]}`)
    setSaving(true)
    setSaveError(null)
    try {
      await updateAccount(accountId, {
        account_control_preset: presetKey,
        account_control_override: normalized as Account['account_control_override'],
      })
      toast('流控已更新')
      void refreshAccounts()
      navigate(`/accounts/${accountId}/edit`)
    } catch (error) {
      setSaveError(error instanceof Error ? error : new Error(String(error)))
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="pb-24">
      <EditBreadcrumb id={accountId} name={acc.name} channel={acc.trade_channel} leaf="流控" />
      <EditWorktopBar
        label="流控"
        hint="请求节奏"
        summary={`${model.preset_display_name} · ${overrideCount ? `${overrideCount} 处自定义` : '全部使用预设值'}`}
        trailing={<Chip>{channelLabel(acc.trade_channel, acc.market)}</Chip>}
        shellVtName={editShellVtName(accountId, 'control')}
        lead="控制交易请求的频率与间隔。保存后从下一次执行开始生效。"
      />

      <Section label="预设方案">
        <div className="rounded-[12px] border border-line bg-surface px-4 py-3.5 md:col-span-2">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <div className="w-24 flex-none text-[13px] text-ink-2">当前方案</div>
            <Select<string>
              ariaLabel="流控预设方案"
              disabled={previewing}
              value={presetKey}
              onChange={(value) => void switchPreset(value)}
              className="w-full justify-between px-3 py-2 text-[14px] sm:w-64"
              options={model.compatible_presets.map((item) => ({ value: item.key, label: item.display_name, hint: item.description }))}
            />
            <span className="text-[12px] text-ink-3">{model.compatible_presets.find((item) => item.key === presetKey)?.description}</span>
          </div>
          <div className="mt-3 flex gap-3 text-[13px]"><span className="w-24 flex-none text-ink-2">统计时区</span><span className="text-ink-1">{model.timezone_display_name}</span></div>
          {previewNote && <p className="mt-2 text-[12px] text-ink-2">{previewNote}</p>}
        </div>
      </Section>
      <ErrorNotice title="预设方案预览失败" error={previewError} variant="mutation" />

      <Section label="常用操作"><div className="flex flex-col gap-2 md:col-span-2">{common.map(renderOperation)}</div></Section>

      {other.length > 0 && (
        <div className="mt-4">
          <button type="button" className="flex w-full cursor-pointer items-center gap-3 border-0 bg-transparent py-2 text-left" onClick={() => setOtherOpen((value) => !value)} aria-expanded={otherOpen}>
            <span className="text-[12px] font-semibold text-ink-2">其他操作</span>
            <span className="text-[11px] text-ink-3">{other.length} 项</span><span className="h-px flex-1 bg-line" /><span className="text-[12px] text-ink-3">{otherOpen ? '⌄' : '›'}</span>
          </button>
          <div inert={!otherOpen} className={`grid transition-[grid-template-rows] duration-200 motion-reduce:transition-none ${otherOpen ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}><div className="min-h-0 overflow-hidden"><div className="flex flex-col gap-2 pt-1">{other.map(renderOperation)}</div></div></div>
        </div>
      )}

      {model.groups.length > 0 && (
        <Section label="共享限制">
          <div className="flex flex-col gap-2 md:col-span-2">
            {model.groups.map((group) => {
              const key = `group:${group.key}`
              const open = openKey === key
              const custom = override.groups[group.key]
              const preset = model.preset_policy.groups[group.key]
              const current = resolveScope(preset, custom)
              return (
                <div key={group.key} className="rounded-[12px] border border-line bg-surface">
                  <button type="button" className="w-full cursor-pointer border-0 bg-transparent px-4 py-3.5 text-left" onClick={() => setOpenKey(open ? null : key)} aria-expanded={open}>
                    <div className="flex items-center gap-3"><span className="min-w-0 flex-1 text-[14px] font-semibold text-ink-1">{group.display_name}</span><span className={`text-[11px] ${custom ? 'text-accent' : 'text-ink-3'}`}>{custom ? '已自定义' : '使用预设值'}</span><span className="text-ink-3">{open ? '⌄' : '›'}</span></div>
                    <p className="mt-1 text-[12px] text-ink-3">{group.description}</p><p className="mt-1 text-[12px] text-ink-2">{scopeSummary(current)}</p>
                  </button>
                  <div inert={!open} className={`grid transition-[grid-template-rows] duration-200 motion-reduce:transition-none ${open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}><div className="min-h-0 overflow-hidden"><div className="border-t border-line px-4 pb-4"><ControlScopeEditor label="共同限制" preset={preset} custom={custom} onChange={(next) => setOverride((currentOverride) => { const groups = { ...currentOverride.groups }; if (next) groups[group.key] = next; else delete groups[group.key]; return { ...currentOverride, groups } })} /></div></div></div>
                </div>
              )
            })}
          </div>
        </Section>
      )}

      <EditSaveBar changes={changes} blocked={Boolean(errors.length || previewing)} cancelTo={`/accounts/${accountId}/edit`} onSave={() => void save()} saving={saving} error={saveError} />
    </section>
  )
}
