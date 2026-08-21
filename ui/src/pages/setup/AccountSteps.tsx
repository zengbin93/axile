import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Bitcoin, ChartCandlestick, CircleHelp, Landmark, Monitor, type LucideIcon } from 'lucide-react'
import { Link, useNavigate } from '@/components/ui/nav'
import { ExecutionTimeoutInput } from '@/features/account/ExecutionTimeoutInput'
import { executionTimeoutError } from '@/features/account/executionTimeout'
import { LeverageInput } from '@/features/account/LeverageInput'
import { leverageError } from '@/features/account/leverage'
import { WizardPage, WizardNav } from '@/features/setup/WizardNav'
import { Segmented } from '@/components/ui/Segmented'
import { Select } from '@/components/ui/Select'
import { getLatestWeights } from '@/lib/api/portfolios'
import { createAccount } from '@/lib/api/accounts'
import { useDomainStore } from '@/stores/domain'
import { useChannelCatalogStore, useChannelDescriptor } from '@/stores/channels'
import { useWizardStore } from '@/stores/wizard'
import { useToastStore } from '@/stores/ui'
import {
  marketForChannel,
  resolveCronList,
  cronToExpr,
} from '@/features/setup/cron'
import { TimerEditor, type TimerEditorState } from '@/features/setup/TimerEditor'
import { emptyAlgorithm, defaultAlgorithm, algoLabel, intentFromParams, validateAlgorithmParams } from '@/features/setup/algorithms'
import { AlgorithmEditor } from '@/features/setup/AlgorithmEditor'
import {
  gmConnectionError,
  normalizeGMConnection,
  switchGMConnectionMode,
  type GMConnectionMode,
} from '@/features/setup/gmConnection'
import type { ChannelAccountField, ChannelCapability } from '@/types/api'

/** 主交易算法的人话摘要：SINGLE-MAKER 用意图档，其余用算法名。 */
const INTENT_TEXT: Record<string, string> = { save: '省成本', fill: '保成交', balance: '平衡' }
function algorithmSummary(algo: { method: string; params: Record<string, unknown> }): string {
  if (algo.method === 'SINGLE-MAKER') {
    const intent = intentFromParams(algo.params)
    if (intent) return INTENT_TEXT[intent]
  }
  return algoLabel(algo.method)
}

const MARKET_LABEL: Record<string, string> = { crypto: '加密货币', ashare: 'A股', ctp: '期货' }

const CHANNEL_ICONS: Record<string, LucideIcon> = {
  bitcoin: Bitcoin,
  'chart-candlestick': ChartCandlestick,
  landmark: Landmark,
  monitor: Monitor,
}

function ChannelIcon({ name }: { name: string }) {
  const Icon = CHANNEL_ICONS[name] ?? CircleHelp
  return <Icon aria-hidden="true" className="h-6 w-6" strokeWidth={1.8} />
}

/** 公开渠道在旧版后端下的连接字段兜底；新后端统一下发 account_form。 */
const PUBLIC_CONNECT_FIELDS: Record<string, ChannelAccountField[]> = {
  ctp: [
    { name: 'broker_id', label: '期货公司代码 broker', input: 'text', required: true, placeholder: '如 9999' },
    { name: 'investor_id', label: '投资者号 investor', input: 'text', required: true },
    { name: 'password', label: '密码', input: 'password', required: true },
    { name: 'td_front', label: '交易前置', input: 'text', required: true, placeholder: 'tcp://...' },
    { name: 'md_front', label: '行情前置', input: 'text', required: true, placeholder: 'tcp://...' },
    { name: 'app_id', label: '应用 ID appid（看穿式认证，可选）', input: 'text', required: false, placeholder: '如 client_xxx' },
    { name: 'auth_code', label: '授权码 authcode（看穿式认证，可选）', input: 'text', required: false },
  ],
  gm: [
    { name: 'account_id', label: '账号 ID', input: 'text', required: true },
    { name: 'token', label: 'Token', input: 'password', required: true },
  ],
}

function accountFields(channel: string, descriptor?: ChannelCapability): ChannelAccountField[] {
  const fields = descriptor?.account_form.fields ?? PUBLIC_CONNECT_FIELDS[channel] ?? []
  if (channel !== 'gm') return fields
  return fields.filter((field) => field.name !== 'terminal_path' && field.name !== 'serv_addr')
}

function accountConfigDefaults(fields: ChannelAccountField[]): Record<string, unknown> {
  return Object.fromEntries(fields.filter((field) => field.default !== undefined).map((field) => [field.name, field.default]))
}

function channelDraft(channel: ChannelCapability) {
  return {
    channel: channel.channel,
    config: accountConfigDefaults(accountFields(channel.channel, channel)),
    algorithm: channel.defaults.trade_algorithm,
    longLeverage: String(channel.defaults.long_leverage),
    shortLeverage: String(channel.defaults.short_leverage),
    executionTimeout: String(channel.defaults.execution_timeout),
  }
}

const inputCls = 'w-full rounded-[11px] border border-ink-3/30 bg-surface px-3.5 py-3 text-[15px] outline-none focus:border-ink-2'
const labelCls = 'mb-1.5 mt-4 block text-[13px] text-ink-2 first:mt-0'

/** GM 两种连接方式：本机终端（Axile 负责启动）或终端 RPC 地址（连已运行的终端），二选一。 */
const GM_CONNECTION_OPTIONS: {
  value: GMConnectionMode
  label: string
  description: string
  targetKey: string
  fieldLabel: string
  placeholder: string
  hint: ReactNode
}[] = [
  {
    value: 'terminal',
    label: '本机终端',
    description: 'Axile 与掘金终端同机，填写安装目录并由 Axile 检查或启动。',
    targetKey: 'terminal_path',
    fieldLabel: '掘金终端目录',
    placeholder: '如 C:\\Program Files\\GoldMiner3',
    hint: '填写包含 goldminer3.exe 的安装目录。',
  },
  {
    value: 'service',
    label: '终端 RPC 地址',
    description: 'Axile 连接已经运行的终端，支持同机或异机部署。',
    targetKey: 'serv_addr',
    fieldLabel: '终端 RPC 地址',
    placeholder: '如 192.168.1.20:7001',
    hint: (
      <>
        先启动掘金终端。地址取自安装目录下 <code className="font-mono text-ink-2">resources\app\gmserv.json</code> 的{' '}
        <code className="font-mono text-ink-2">default.hostAddr</code> 和 <code className="font-mono text-ink-2">default.rpcPort</code>
        ；异机连接需填写 Axile 可访问的 IP，不能使用 127.0.0.1。
      </>
    ),
  },
]

/* -------- 1 选渠道 -------- */
export function AcctChannel() {
  const { acct, setAcct } = useWizardStore()
  const channels = useChannelCatalogStore((state) => state.channels)
  const loading = useChannelCatalogStore((state) => state.loading)
  const error = useChannelCatalogStore((state) => state.error)
  const refresh = useChannelCatalogStore((state) => state.refresh)

  const selectChannel = (channel: ChannelCapability) => {
    setAcct(channelDraft(channel))
  }

  // 目录就绪后，为空草稿或失效选择落到第一个可用渠道。
  useEffect(() => {
    if (!channels) return
    if (channels.some((channel) => channel.channel === acct.channel && channel.available)) return
    const firstAvailable = channels.find((channel) => channel.available)
    if (firstAvailable) setAcct(channelDraft(firstAvailable))
  }, [channels, acct.channel, setAcct])

  const selected = channels?.find((channel) => channel.channel === acct.channel)
  const nextDisabled = !selected?.available

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 overflow-y-auto">
        <WizardPage kicker="账户设置 · 1 / 6" title="连接哪个交易所 / 券商？" lead="不同渠道连接方式完全不同——选定后进入对应的连接页。">
          <div className="grid grid-cols-1 gap-3">
            {loading && channels === null && <p className="text-[14px] text-ink-2">加载渠道…</p>}
            {error && channels === null && (
              <button type="button" className="text-left text-[14px] text-warn hover:underline" onClick={() => void refresh()}>
                渠道目录加载失败，点击重试
              </button>
            )}
            {channels?.map((ch) => {
              const available = ch.available
              const isSelected = acct.channel === ch.channel
              return (
                <button
                  key={ch.channel}
                  disabled={!available}
                  className={`flex w-full items-start gap-4 rounded-[14px] border p-[18px] text-left transition ${
                    !available
                      ? 'cursor-not-allowed border-line bg-surface opacity-60'
                      : isSelected
                        ? 'border-accent bg-accent-soft shadow-[inset_0_0_0_1px_var(--color-accent)]'
                        : 'border-line bg-surface hover:border-ink-3/30'
                  }`}
                  onClick={() => available && selectChannel(ch)}
                >
                  <span className="grid h-11 w-11 flex-none place-items-center rounded-xl bg-fill">
                    <ChannelIcon name={ch.icon} />
                  </span>
                  <span>
                    <span className={`block text-[16px] font-[620] ${available ? '' : 'text-ink-3'}`}>{ch.label}</span>
                    <span className={`mt-0.5 block text-[13px] ${available ? 'text-ink-2' : 'text-warn'}`}>
                      {available ? ch.description : '暂不可用'}
                    </span>
                  </span>
                </button>
              )
            })}
          </div>
        </WizardPage>
      </div>
      <WizardNav nextTo="/setup/acct/connect" nextDisabled={nextDisabled} />
    </div>
  )
}

/* -------- 2 连接 -------- */
export function AcctConnect() {
  const { acct, setAcct } = useWizardStore()
  const descriptor = useChannelDescriptor(acct.channel)
  const fields = accountFields(acct.channel, descriptor)
  const gmModeButtonRefs = useRef<Partial<Record<GMConnectionMode, HTMLButtonElement | null>>>({})
  const setField = (key: string, val: unknown) => setAcct({ config: { ...acct.config, [key]: val } })
  const stringConfig = acct.config as Record<string, string>
  const gmError = acct.channel === 'gm' ? gmConnectionError(stringConfig, acct.gmConnectionMode) : null
  const missingRequired = fields.some((field) => {
    if (!field.required) return false
    const value = acct.config[field.name]
    return value === undefined || value === null || (typeof value === 'string' && value.trim() === '')
  })

  const setGMConnectionMode = (mode: GMConnectionMode) => {
    setAcct({
      gmConnectionMode: mode,
      config: switchGMConnectionMode(stringConfig, mode),
    })
  }

  const moveGMConnectionMode = (mode: GMConnectionMode) => {
    setGMConnectionMode(mode)
    gmModeButtonRefs.current[mode]?.focus()
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 overflow-y-auto">
        <WizardPage
          kicker="账户设置 · 2 / 6"
          title={`连接 ${descriptor?.label ?? acct.channel}`}
          lead={descriptor?.ui.account_connect_lead || '填好凭据即可；连通性在创建账户时由后端用真实凭据校验。'}
        >
          <div className="max-w-[560px]">
            <label className={labelCls}>账户名称</label>
            <input className={inputCls} value={acct.name} onChange={(e) => setAcct({ name: e.target.value })} placeholder="给这个账户起个名字" />

            {descriptor?.account_form.notices.map((notice, index) => (
              <div
                key={`${notice.tone}-${index}`}
                className={`mt-4 rounded-xl border px-4 py-3.5 text-[14px] ${
                  notice.tone === 'warning' ? 'border-warn/30 bg-warn-soft text-warn' : 'border-line bg-fill text-ink-2'
                }`}
              >
                {notice.text}
              </div>
            ))}
            {fields.map((field) => {
              const value = acct.config[field.name] ?? field.default ?? ''
              return (
                <div key={field.name}>
                  <label className={labelCls}>{field.label}</label>
                  {field.input === 'boolean' ? (
                    <Segmented
                      value={value === true || value === 'true' ? 'true' : 'false'}
                      options={[
                        { value: 'false', label: '关闭' },
                        { value: 'true', label: '启用' },
                      ]}
                      onChange={(next) => setField(field.name, next === 'true')}
                    />
                  ) : field.input === 'select' ? (
                    <Select<string>
                      className="w-full justify-between px-3.5 py-3 text-[15px]"
                      value={String(value)}
                      onChange={(next) => setField(field.name, next)}
                      options={field.options ?? []}
                    />
                  ) : (
                    <input
                      className={inputCls}
                      type={field.input}
                      placeholder={field.placeholder}
                      value={String(value)}
                      onChange={(event) => {
                        const nextValue =
                          field.input === 'number'
                            ? event.target.value === ''
                              ? undefined
                              : Number(event.target.value)
                            : event.target.value
                        setField(field.name, nextValue)
                      }}
                    />
                  )}
                  {field.help && <div className="mt-1 text-[12px] text-ink-3">{field.help}</div>}
                </div>
              )
            })}
            {acct.channel === 'gm' && (
              <fieldset className="mt-4">
                <legend className="text-[13px] text-ink-2">选择一种连接方式</legend>
                <p className="mt-1 text-[12px] text-ink-3">只需配置其中一种。</p>
                {/* fieldset 不映射为 radiogroup，选项仍是 radio 语义，故在此显式补 role 与名字。 */}
                <div role="radiogroup" aria-label="连接方式" className="mt-3 divide-y divide-line border-y border-line">
                  {GM_CONNECTION_OPTIONS.map((option) => {
                    const selected = acct.gmConnectionMode === option.value
                    // 色条两行恒在（未选中透明）：只给选中行加会让文字每次切换横移 3px。
                    return (
                      <div
                        key={option.value}
                        className={`border-l-[3px] pl-3 transition-colors duration-200 motion-reduce:transition-none ${
                          selected ? 'border-accent' : 'border-transparent'
                        }`}
                      >
                        <button
                          ref={(node) => {
                            gmModeButtonRefs.current[option.value] = node
                          }}
                          type="button"
                          role="radio"
                          aria-checked={selected}
                          tabIndex={selected ? 0 : -1}
                          className="group -mx-2 flex w-[calc(100%+1rem)] cursor-pointer items-start gap-3 rounded-lg bg-transparent px-2 py-3.5 text-left transition-colors duration-200 hover:bg-fill focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent motion-reduce:transition-none"
                          onClick={() => setGMConnectionMode(option.value)}
                          onKeyDown={(event) => {
                            let nextMode: GMConnectionMode | null = null
                            if (event.key === 'ArrowLeft' || event.key === 'ArrowUp' || event.key === 'Home') nextMode = 'terminal'
                            if (event.key === 'ArrowRight' || event.key === 'ArrowDown' || event.key === 'End') nextMode = 'service'
                            if (nextMode === null) return
                            event.preventDefault()
                            moveGMConnectionMode(nextMode)
                          }}
                        >
                          <span>
                            <span
                              className={`block text-[16px] font-[620] transition-colors duration-200 motion-reduce:transition-none ${
                                selected ? 'text-accent' : 'text-ink-1'
                              }`}
                            >
                              {option.label}
                            </span>
                            <span className="mt-0.5 block text-[13px] leading-relaxed text-ink-2">{option.description}</span>
                          </span>
                        </button>
                        {/*
                          两个参数区都常挂，靠 grid-fr 在 0fr↔1fr 间收放：条件挂载会让下方选项
                          瞬间上蹿、点击目标从光标底下跑掉。收放走布局流，兄弟自然 reflow，
                          故此处不再叠 panel-fade-in（一个对象只跑一套范式）。
                        */}
                        <div
                          inert={!selected}
                          className={`grid transition-[grid-template-rows] duration-200 ease-[cubic-bezier(.4,0,.2,1)] motion-reduce:transition-none ${
                            selected ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'
                          }`}
                        >
                          <div className="min-h-0 overflow-hidden">
                            <div className="pb-4">
                              <label className="mb-1.5 block text-[13px] text-ink-2">{option.fieldLabel}</label>
                              <input
                                className={inputCls}
                                placeholder={option.placeholder}
                                value={String(acct.config[option.targetKey] ?? '')}
                                onChange={(e) => setField(option.targetKey, e.target.value)}
                              />
                              <p className="mt-2 text-[12px] leading-relaxed text-ink-3">{option.hint}</p>
                            </div>
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </fieldset>
            )}
          </div>
        </WizardPage>
      </div>
      <WizardNav
        prevTo="/setup/acct/channel"
        nextTo="/setup/acct/portfolio"
        nextDisabled={!acct.name.trim() || missingRequired || gmError !== null}
      />
    </div>
  )
}

/* -------- 3 绑定组合 -------- */
export function AcctPortfolio() {
  const { acct, setAcct } = useWizardStore()
  const portfolios = useDomainStore((s) => s.portfolios)
  const list = portfolios ?? []

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 overflow-y-auto">
        <WizardPage kicker="账户设置 · 3 / 6" title="用哪个组合？" lead="账户按组合算出的目标持仓来调仓。">
          <div className="grid grid-cols-1 gap-3">
            {portfolios == null && <p className="text-[14px] text-ink-2">加载组合…</p>}
            {list.map((p) => (
              <button
                key={p.id}
                className={`flex w-full items-start gap-4 rounded-[14px] border p-[18px] text-left transition ${acct.portfolioId === p.id ? 'border-accent bg-accent-soft shadow-[inset_0_0_0_1px_var(--color-accent)]' : 'border-line bg-surface hover:border-ink-3/30'}`}
                onClick={() => setAcct({ portfolioId: p.id })}
              >
                <span className="grid h-11 w-11 flex-none place-items-center rounded-xl bg-fill text-[22px]">🎯</span>
                <span>
                  <span className="block text-[16px] font-[620]">{p.name}</span>
                  <span className="mt-0.5 block text-[13px] text-ink-2">{p.market}{p.description ? ` · ${p.description}` : ''}</span>
                </span>
              </button>
            ))}
            <Link to="/setup/pf/name" className="flex items-center gap-4 rounded-[14px] border border-dashed border-line p-[18px] text-ink-2 hover:border-ink-3/30">
              <span className="grid h-11 w-11 flex-none place-items-center rounded-xl bg-fill text-[22px]">＋</span>
              <span>
                <span className="block text-[16px] font-[620]">新建组合</span>
                <span className="mt-0.5 block text-[13px] text-ink-2">跳到组合设置</span>
              </span>
            </Link>
          </div>
        </WizardPage>
      </div>
      <WizardNav prevTo="/setup/acct/connect" nextTo="/setup/acct/trade" nextDisabled={acct.portfolioId == null} />
    </div>
  )
}

/* -------- 4 交易方式 -------- */
export function AcctTrade() {
  const { acct, setAcct } = useWizardStore()
  const descriptor = useChannelDescriptor(acct.channel)
  const market = marketForChannel(acct.channel)
  const leverageLimits = descriptor?.leverage
  const showShortLeverage = descriptor?.ui.show_short_leverage ?? market !== 'ashare'
  const timeoutErr = executionTimeoutError(acct.executionTimeout)
  const longLeverageErr = leverageError(acct.longLeverage, leverageLimits)
  const shortLeverageErr = showShortLeverage ? leverageError(acct.shortLeverage, leverageLimits) : null
  const leverageErr = longLeverageErr ?? shortLeverageErr

  // 切渠道（市场变化）时，把主交易算法重置为该市场的默认，避免带着上个市场的算法过界。
  const prevMarket = useRef(market)
  useEffect(() => {
    if (prevMarket.current !== market) {
      prevMarket.current = market
      setAcct({ algorithm: descriptor?.defaults.trade_algorithm ?? defaultAlgorithm(market, 'trade') })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [market])

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 overflow-y-auto">
        <WizardPage kicker="账户设置 · 4 / 6" title="怎么交易？" lead="选想要的结果，参数系统替你配。">
          <label className="mb-2 block text-[13px] text-ink-2">交易方式</label>
          <AlgorithmEditor
            slot="trade"
            channel={acct.channel}
            value={acct.algorithm}
            onChange={(v) => setAcct({ algorithm: v ?? descriptor?.defaults.trade_algorithm ?? defaultAlgorithm(market, 'trade') })}
          />

          <div className="mt-6 max-w-[560px]">
            <div className="grid grid-cols-1 gap-3 border-t border-line py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start sm:gap-6">
              <div className="min-w-0">
                <label htmlFor="account-execution-timeout" className="text-[15px] text-ink-1">
                  执行超时
                </label>
                <div
                  id="account-execution-timeout-help"
                  className={`mt-0.5 text-[12px] ${timeoutErr ? 'text-warn' : 'text-ink-3'}`}
                >
                  {timeoutErr ?? '限制一次执行最多运行多久；超时后停止开新单。'}
                </div>
              </div>
              <ExecutionTimeoutInput
                id="account-execution-timeout"
                describedBy="account-execution-timeout-help"
                invalid={Boolean(timeoutErr)}
                value={acct.executionTimeout}
                onChange={(executionTimeout) => setAcct({ executionTimeout })}
              />
            </div>
          </div>

          <div className="mt-6 max-w-[560px]">
            <label className="mb-1.5 block text-[13px] text-ink-2">
              {descriptor?.ui.leverage_title ?? '杠杆'}{' '}
              <span className="text-ink-3">（{descriptor?.ui.leverage_note ?? '多空可分设'}）</span>
            </label>
            <div className="grid grid-cols-1 gap-3 border-t border-line py-3 text-[15px] sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start sm:gap-6">
              <div>
                <label htmlFor="account-long-leverage">{descriptor?.ui.long_leverage_label ?? '做多杠杆'}</label>
                <div
                  id="account-long-leverage-help"
                  className={`mt-0.5 text-[12px] ${longLeverageErr ? 'text-warn' : 'text-ink-3'}`}
                >
                  {longLeverageErr ?? `${leverageLimits?.min ?? 0}–${leverageLimits?.max ?? '不限'}，步进 ${leverageLimits?.step ?? 0.1}`}
                </div>
              </div>
              <LeverageInput
                id="account-long-leverage"
                describedBy="account-long-leverage-help"
                invalid={Boolean(longLeverageErr)}
                limits={leverageLimits}
                value={acct.longLeverage}
                onChange={(longLeverage) => setAcct({ longLeverage })}
              />
            </div>
            {showShortLeverage && (
              <div className="grid grid-cols-1 gap-3 border-t border-line py-3 text-[15px] sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start sm:gap-6">
                <div>
                  <label htmlFor="account-short-leverage">{descriptor?.ui.short_leverage_label ?? '做空杠杆'}</label>
                  <div
                    id="account-short-leverage-help"
                    className={`mt-0.5 text-[12px] ${shortLeverageErr ? 'text-warn' : 'text-ink-3'}`}
                  >
                    {shortLeverageErr ?? '0 = 不做空'}
                  </div>
                </div>
                <LeverageInput
                  id="account-short-leverage"
                  describedBy="account-short-leverage-help"
                  invalid={Boolean(shortLeverageErr)}
                  limits={leverageLimits}
                  value={acct.shortLeverage}
                  onChange={(shortLeverage) => setAcct({ shortLeverage })}
                />
              </div>
            )}
          </div>
        </WizardPage>
      </div>
      <WizardNav
        prevTo="/setup/acct/portfolio"
        nextTo="/setup/acct/timer"
        nextDisabled={Boolean(timeoutErr || leverageErr)}
      />
    </div>
  )
}

/* -------- 5 定时 -------- */
export function AcctTimer() {
  const { acct, setAcct } = useWizardStore()
  const market = marketForChannel(acct.channel)

  const timerValue: TimerEditorState = {
    autoOn: acct.autoOn,
    presetIds: acct.presetIds,
    supN: acct.supN,
    supM: acct.supM,
    rawCron: acct.rawCron,
    timerTab: acct.timerTab,
    scheduleRules: acct.scheduleRules,
    selectedRuleId: acct.selectedRuleId,
    customCronOn: acct.customCronOn,
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 overflow-y-auto">
        <WizardPage kicker="账户设置 · 5 / 6" title="什么时候自动执行？" lead="开启后 axile 按下面的节奏自动调仓。时间均为北京时间。">
          <TimerEditor
            market={market}
            value={timerValue}
            onChange={(next) => {
              const v = typeof next === 'function' ? next(timerValue) : next
              setAcct({
                autoOn: v.autoOn,
                presetIds: v.presetIds,
                supN: v.supN,
                supM: v.supM,
                rawCron: v.rawCron,
                timerTab: v.timerTab,
                scheduleRules: v.scheduleRules,
                selectedRuleId: v.selectedRuleId,
                customCronOn: v.customCronOn,
              })
            }}
          />
        </WizardPage>
      </div>
      <WizardNav prevTo="/setup/acct/trade" nextTo="/setup/acct/confirm" />
    </div>
  )
}

export function AcctConfirm() {
  const { acct, resetAcct } = useWizardStore()
  const navigate = useNavigate()
  const toast = useToastStore((s) => s.toast)
  const refreshAccounts = useDomainStore((s) => s.refreshAccounts)
  const descriptor = useChannelDescriptor(acct.channel)
  const market = marketForChannel(acct.channel)
  const showShortLeverage = descriptor?.ui.show_short_leverage ?? market !== 'ashare'
  const [rows, setRows] = useState<[string, number][] | null>(null)

  const cronList = resolveCronList(market, acct)
  const cronExpr = cronToExpr(cronList) || '0 8 * * *'

  const intentText = algorithmSummary(acct.algorithm)
  const levText = showShortLeverage
    ? `做多 ${acct.longLeverage}x / 做空 ${acct.shortLeverage}x`
    : `${descriptor?.ui.long_leverage_label ?? '做多杠杆'} ${acct.longLeverage}`

  const preview = async () => {
    if (acct.portfolioId == null) {
      toast('请先绑定组合再试跑')
      return
    }
    try {
      const w = await getLatestWeights(acct.portfolioId, acct.channel)
      setRows(Object.entries(w).filter(([, v]) => Math.abs(v) > 1e-9).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])))
    } catch (e) {
      toast(`试跑失败：${e instanceof Error ? e.message : String(e)}`)
      setRows([])
    }
  }

  const submit = async () => {
    try {
      if (acct.channel === 'gm') {
        const connectionError = gmConnectionError(acct.config as Record<string, string>, acct.gmConnectionMode)
        if (connectionError) {
          toast(`连接信息不完整：${connectionError}`)
          return
        }
      }
      const algo = acct.algorithm
      const paramErr = validateAlgorithmParams(algo.params)
      if (paramErr) {
        toast(`算法参数非法：${paramErr}`)
        return
      }
      const timeoutErr = executionTimeoutError(acct.executionTimeout)
      if (timeoutErr) {
        toast(`执行超时有误：${timeoutErr}`)
        return
      }
      const longLeverageErr = leverageError(acct.longLeverage, descriptor?.leverage)
      const shortLeverageErr = showShortLeverage ? leverageError(acct.shortLeverage, descriptor?.leverage) : null
      if (longLeverageErr || shortLeverageErr) {
        toast(`杠杆有误：${longLeverageErr ?? shortLeverageErr}`)
        return
      }
      const account = await createAccount({
        name: acct.name,
        market: MARKET_LABEL[market] ?? descriptor?.market ?? market,
        trade_channel: acct.channel,
        account_control_preset: 'default',
        account_control_override: null,
        account_config: {
          ...(acct.channel === 'gm' ? normalizeGMConnection(acct.config as Record<string, string>, acct.gmConnectionMode) : acct.config),
        },
        is_started: acct.autoOn,
        cron_expr: cronExpr,
        remark: '由建号向导创建',
        brokerage: acct.channel,
        weight_precision: 0.01,
        long_leverage: Number(acct.longLeverage),
        short_leverage: showShortLeverage ? Number(acct.shortLeverage) : 0,
        algorithm: algo,
        empty_positions_algorithm: descriptor ? descriptor.defaults.empty_positions_algorithm : emptyAlgorithm(market),
        trade_rules: null,
        forbidden_symbols: null,
        risk_symbols: null,
        feishu_key: null,
        portfolio_id: acct.portfolioId,
        write_empty_record: null,
        execution_timeout: Number(acct.executionTimeout),
      })
      toast(`账户「${account.name}」已创建`)
      resetAcct()
      void refreshAccounts()
      navigate(account.id != null ? `/accounts/${account.id}` : '/')
    } catch (e) {
      toast(`创建失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 overflow-y-auto">
        <WizardPage kicker="账户设置 · 6 / 6" title="确认无误就开跑">
          <div className="rounded-2xl bg-ok-soft px-7 py-6 text-[19px] leading-loose">
            这个账户 <b className="font-[680]">{acct.name || '（未命名）'}</b> 在 <b className="font-[680]">{descriptor?.label ?? acct.channel}</b> 上，
            绑定组合 <b className="font-[680]">#{acct.portfolioId ?? '—'}</b>，用 <b className="font-[680]">{intentText}</b> 的方式，
            {acct.autoOn ? '自动' : '手动'}调仓，杠杆 <b className="font-[680]">{levText}</b>。
          </div>
          <div className="mt-2 text-xs text-ink-3">
            执行超时 {acct.executionTimeout} 秒 · cron：
            <code className="rounded bg-fill px-1.5 py-0.5 font-mono">{cronExpr}</code>
          </div>

          <div className="mt-5">
            <button className="cursor-pointer rounded-[11px] border-0 bg-ink-1 px-[22px] py-2.5 text-[14px] font-[550] text-surface" onClick={preview}>
              ▶ 试跑（不下单）
            </button>
            <div className="mt-[18px] max-w-[460px] rounded-[14px] border border-dashed border-line bg-surface p-5">
              {rows == null && <div className="py-5 text-center text-[14px] text-ink-3">试跑看这套组合此刻会调成什么样</div>}
              {rows != null && rows.length === 0 && <div className="py-5 text-center text-[14px] text-ink-3">无目标持仓。</div>}
              {rows?.map(([sym, w]) => (
                <div key={sym} className="flex items-center justify-between border-b border-line py-2.5 text-[15px] last:border-b-0">
                  <span className="font-[520]">{sym}</span>
                  <span className={`num text-ink-2 ${w < 0 ? 'text-bad' : ''}`}>{(w * 100).toFixed(1)}%</span>
                </div>
              ))}
            </div>
          </div>
        </WizardPage>
      </div>
      <WizardNav prevTo="/setup/acct/timer" nextLabel="创建并开跑" onNext={submit} nextDisabled={acct.portfolioId == null || !acct.name.trim()} />
    </div>
  )
}
