import { useState } from 'react'
import { ThemeToggle } from '@/components/ThemeToggle'
import { Toast } from '@/components/Toast'
import { ConfirmModal, type ConfirmSpec } from '@/components/ui/ConfirmModal'
import { Select } from '@/components/ui/Select'
import { WizardPage } from '@/features/setup/WizardNav'
import { ApiError } from '@/lib/api/client'
import {
  initStatus,
  saveInit,
  testQuantData,
  testDb,
  testFeishu,
  testTradingCalendar,
  type InitValues,
} from '@/lib/api/init'
import { useToastStore } from '@/stores/ui'

/** 向导运行模式：首启初始化 vs 已配置后从主页进入的系统配置。 */
export type WizardMode = 'init' | 'edit'

const inputCls =
  'w-full rounded-[11px] border border-ink-3/30 bg-surface px-3.5 py-3 text-[15px] outline-none focus:border-ink-2'
const labelCls = 'mb-1.5 mt-4 block text-[13px] text-ink-2 first:mt-0'

const DEFAULT_DB_URI = 'sqlite+aiosqlite:///./axile.db'
const DEFAULT_CALENDAR_API = 'https://api.shengkezhi.com/open/v1/market/trading-calendar'
const DEFAULT_QUANT_DATA_API = 'https://api.shengkezhi.com/open/v1/research/strategies/positions/latest'

/** 随模式切换的文案；`init`=首启初始化，`edit`=已配置后的系统配置。 */
interface Copy {
  /** 头部与左栏的向导名。 */
  brand: string
  /** 各步 kicker 前缀（如「初始化 · 1 / 3」）。 */
  kicker: string
  /** 第 3 步标题。 */
  confirmTitle: string
  /** 第 3 步引导语。 */
  confirmLead: string
  /** 末步主按钮文案。 */
  saveLabel: string
  /** 保存进行中的按钮文案。 */
  savingLabel: string
  /** 保存成功后的 toast。 */
  savedToast: string
  /** 数据源那步「跳过（清空并进确认页）」的文案。 */
  skipLabel: string
}

const COPY: Record<WizardMode, Copy> = {
  init: {
    brand: '初始化',
    kicker: '初始化',
    confirmTitle: '确认并启动',
    confirmLead: '确认无误后保存；axile 会写入配置并自动重启进入正常模式。',
    saveLabel: '保存并启动',
    savingLabel: '启动中…',
    savedToast: '配置已保存，axile 正在启动…',
    skipLabel: '跳过 · 仅自定义组合',
  },
  edit: {
    brand: '系统配置',
    kicker: '系统配置',
    confirmTitle: '确认并保存',
    confirmLead: '确认无误后保存；axile 会写入配置并重启服务以生效，期间会中断进行中的执行。',
    saveLabel: '保存并重启',
    savingLabel: '重启中…',
    savedToast: '配置已保存，axile 正在重启…',
    skipLabel: '清空数据源 · 仅自定义组合',
  },
}

// 三个可选集成各自成步（都带「测试」按钮，需要按钮+结果的横向空间）：量化数据源、交易日历、执行告警飞书。
// 数据库/环境/日志等有可用默认值、无需连通性自检，收进确认页的「高级选项」。
const STEP_LABELS = ['量化数据源', '交易日历', '执行告警'] as const

/** 表单草稿；`algorithm_modules` / `algorithm_directories` 以每行一项的文本承载，保存时切分为数组。 */
interface Draft {
  sqlalchemy_database_uri: string
  quant_data_token: string
  quant_data_api: string
  trading_calendar_token: string
  trading_calendar_api: string
  exe_err_feishu_key: string
  environment: string
  app_log_dir: string
  axile_log_rotation: string
  algorithm_modules: string
  algorithm_directories: string
}

type TestState = { ok: boolean; message: string } | 'busy' | null

function errText(e: unknown): string {
  return e instanceof ApiError ? e.message : String(e)
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/**
 * 「测试连接」按钮 + 结果徽标。`idleLabel` 覆盖空闲文案，`disabled` 用于「未填写即不可测」。
 *
 * 结果色走 accent（蓝，✓）/ warn（琥珀，✗）——成败不占红绿（红绿留给涨跌）。
 */
function TestRow({
  state,
  onTest,
  idleLabel = '测试连接',
  disabled = false,
}: {
  state: TestState
  onTest: () => void
  idleLabel?: string
  disabled?: boolean
}) {
  return (
    <div className="mt-4 flex items-center gap-3">
      <button
        className="cursor-pointer rounded-[11px] border border-line bg-surface px-4 py-2.5 text-[14px] text-ink-2 disabled:opacity-45"
        onClick={onTest}
        disabled={disabled || state === 'busy'}
      >
        {state === 'busy' ? '测试中…' : idleLabel}
      </button>
      {state && state !== 'busy' && (
        <span className={`text-[13px] ${state.ok ? 'text-accent' : 'text-warn'}`}>
          {state.ok ? '✓ ' : '✗ '}
          {state.message}
        </span>
      )}
    </div>
  )
}

/**
 * 左侧步骤栏。
 *
 * `freeNav=false`（init 向导）：逐级解锁，仅「已完成 / 当前」可点击回跳，已完成项打绿勾。
 * `freeNav=true`（edit 设置页）：各节可任意跳转、不显示进度绿勾——系统已配好，这里是随取随改的导航而非线性流程。
 */
function Rail({
  step,
  steps,
  title,
  onJump,
  freeNav = false,
}: {
  step: number
  steps: readonly string[]
  title: string
  onJump: (i: number) => void
  freeNav?: boolean
}) {
  return (
    <aside className="w-[248px] flex-none overflow-y-auto border-r border-line bg-surface px-[18px] py-7">
      <div className="px-2.5 pb-3.5 text-xs font-semibold tracking-wide text-ink-3">{title}</div>
      {steps.map((label, i) => {
        const done = !freeNav && i < step
        const cur = i === step
        const clickable = freeNav || i <= step
        return (
          <button
            key={label}
            onClick={() => clickable && onJump(i)}
            className={`flex w-full items-center gap-3 rounded-[10px] p-2.5 text-left text-[14px] ${
              cur ? 'bg-accent-soft font-semibold text-ink-1' : 'text-ink-2'
            } ${clickable ? 'cursor-pointer' : 'cursor-default'}`}
          >
            <span
              className={`grid h-6 w-6 flex-none place-items-center rounded-full border text-xs ${
                done
                  ? 'border-ok bg-ok text-white'
                  : cur
                    ? 'border-accent text-accent'
                    : 'border-border-strong bg-surface text-ink-3'
              }`}
            >
              {done ? '✓' : i + 1}
            </span>
            {label}
          </button>
        )
      })}
    </aside>
  )
}

/**
 * 配置向导（整屏）。
 *
 * 两种模式共用一套表单，但**导航范式不同**：
 * - `init`=首启初始化（由 `AppRoot` 在未配置时整屏渲染）：线性向导，逐级「下一步」推进，Rail 仅回跳已过步骤。
 * - `edit`=已配置后从齿轮进入的系统配置（由 `SystemConfigPage` 承载，带关闭回调）：**设置页**，
 *   Rail 各节任意跳转、页脚常驻「保存并重启」，可从任意节直接保存——系统早已配好，无须逐级点按。
 *
 * 采集数据库地址与量化数据源等配置，保存后后端写入 config.toml 并自重启；
 * 期间轮询 `/init/status`，就绪后刷新页面进入正常应用。编辑态保存前先弹确认（重启会中断执行）。
 */
export function InitWizard({
  initial,
  mode = 'init',
  onClose,
}: {
  initial: InitValues
  /** 运行模式，默认首启初始化。 */
  mode?: WizardMode
  /** 编辑态的关闭回调（返回主应用）；首启态不传。 */
  onClose?: () => void
}) {
  const copy = COPY[mode]
  const steps = [...STEP_LABELS, copy.confirmTitle]
  const isEdit = mode === 'edit'

  const toast = useToastStore((s) => s.toast)
  const [step, setStep] = useState(0)
  const [saving, setSaving] = useState(false)
  const [dbTest, setDbTest] = useState<TestState>(null)
  const [quantDataTest, setQuantDataTest] = useState<TestState>(null)
  const [calendarTest, setCalendarTest] = useState<TestState>(null)
  const [feishuTest, setFeishuTest] = useState<TestState>(null)
  const [confirm, setConfirm] = useState<ConfirmSpec | null>(null)

  const [draft, setDraft] = useState<Draft>({
    sqlalchemy_database_uri: initial.sqlalchemy_database_uri || DEFAULT_DB_URI,
    quant_data_token: initial.quant_data_token,
    quant_data_api: initial.quant_data_api || DEFAULT_QUANT_DATA_API,
    trading_calendar_token: initial.trading_calendar_token ?? '',
    trading_calendar_api: initial.trading_calendar_api || DEFAULT_CALENDAR_API,
    exe_err_feishu_key: initial.exe_err_feishu_key ?? '',
    environment: initial.environment || 'local',
    app_log_dir: initial.app_log_dir || './logs',
    axile_log_rotation: initial.axile_log_rotation || '1 day',
    algorithm_modules: (initial.algorithm_modules ?? []).join('\n'),
    algorithm_directories: (initial.algorithm_directories ?? []).join('\n'),
  })
  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }))

  const runDbTest = async () => {
    setDbTest('busy')
    try {
      setDbTest(await testDb(draft.sqlalchemy_database_uri))
    } catch (e) {
      setDbTest({ ok: false, message: errText(e) })
    }
  }

  const runQuantDataTest = async () => {
    setQuantDataTest('busy')
    try {
      setQuantDataTest(await testQuantData(draft.quant_data_token, draft.quant_data_api))
    } catch (e) {
      setQuantDataTest({ ok: false, message: errText(e) })
    }
  }

  const runFeishuTest = async () => {
    setFeishuTest('busy')
    try {
      setFeishuTest(await testFeishu(draft.exe_err_feishu_key))
    } catch (e) {
      setFeishuTest({ ok: false, message: errText(e) })
    }
  }

  const runCalendarTest = async () => {
    setCalendarTest('busy')
    try {
      setCalendarTest(await testTradingCalendar(draft.trading_calendar_token, draft.trading_calendar_api))
    } catch (e) {
      setCalendarTest({ ok: false, message: errText(e) })
    }
  }

  /** 保存后轮询就绪状态，容忍重启期间的请求失败，就绪或超时后刷新。 */
  const waitReadyAndReload = async () => {
    const deadline = Date.now() + 90_000
    while (Date.now() < deadline) {
      await sleep(1500)
      try {
        const s = await initStatus()
        if (s.configured) break
      } catch {
        // 后端正在重启，继续轮询。
      }
    }
    window.location.reload()
  }

  const doSave = async () => {
    setSaving(true)
    try {
      const splitLines = (s: string) =>
        s
          .split('\n')
          .map((m) => m.trim())
          .filter(Boolean)
      await saveInit({
        ...draft,
        algorithm_modules: splitLines(draft.algorithm_modules),
        algorithm_directories: splitLines(draft.algorithm_directories),
      })
      toast(copy.savedToast)
      await waitReadyAndReload()
    } catch (e) {
      setSaving(false)
      toast('保存失败：' + errText(e))
    }
  }

  /** 编辑态保存前先弹确认（重启会中断进行中的执行）；首启态直接保存。 */
  const onSave = () => {
    if (isEdit) {
      setConfirm({
        title: '保存并重启服务',
        body: '保存后 axile 会写入配置并重启服务以生效，正在进行中的执行会被中断。确认继续?',
        okText: '保存并重启',
        danger: true,
        onConfirm: () => void doSave(),
      })
    } else {
      void doSave()
    }
  }

  // 「下一步」= 带数据源继续，需两项都填；空 / 半填改走左下角「跳过」（清空并进下一步）。
  // 执行告警（step 1）为选填，空即不推送，从不拦「下一步」；数据库地址护栏落在确认页（末步）。
  const dataSourceReady = Boolean(draft.quant_data_token.trim() && draft.quant_data_api.trim())
  const confirmStep = steps.length - 1
  const nextDisabled =
    (step === 0 && !dataSourceReady) || (step === confirmStep && !draft.sqlalchemy_database_uri.trim())

  // 数据源半填（只填其一）后端必 422；edit 态可从任意节直接保存，故在此统一拦截。
  const dataSourceHalf =
    Boolean(draft.quant_data_token.trim()) !== Boolean(draft.quant_data_api.trim())
  const calendarHalf = Boolean(draft.trading_calendar_token.trim()) && !draft.trading_calendar_api.trim()
  const saveDisabled = saving || !draft.sqlalchemy_database_uri.trim() || dataSourceHalf || calendarHalf

  // edit 态是设置页而非向导：kicker 去掉「n / N」序号，只留分节标签。
  const kickerOf = (n: number) => (isEdit ? copy.kicker : `${copy.kicker} · ${n} / ${steps.length}`)

  const onNext = () => {
    if (step < steps.length - 1) setStep(step + 1)
    else onSave()
  }

  /** 跳过数据源：清空两项与其测试结果，以「仅自定义组合」模式进入下一步（仅 init 向导）。 */
  const onSkip = () => {
    set({ quant_data_token: '', quant_data_api: '' })
    setQuantDataTest(null)
    setStep(step + 1)
  }

  /** 清空数据源：edit 态原地清空两项（转「仅自定义组合」），不跳步——设置页由 Rail 导航。 */
  const onClearDataSource = () => {
    set({ quant_data_token: '', quant_data_api: '' })
    setQuantDataTest(null)
  }

  return (
    <div className="flex h-screen flex-col">
      <header className="flex h-14 flex-none items-center gap-3.5 border-b border-line bg-surface px-6">
        <span className="font-[650] tracking-wide">axile</span>
        <span className="text-[14px] text-ink-2">· {copy.brand}</span>
        <span className="ml-auto" />
        <ThemeToggle />
        {isEdit && onClose && (
          <button
            className="cursor-pointer rounded-chip border border-line px-3 py-1.5 text-[13px] text-ink-2 hover:border-ink-3/40 hover:text-ink-1"
            onClick={onClose}
          >
            关闭
          </button>
        )}
      </header>

      <div className="flex flex-1 overflow-hidden">
        <Rail step={step} steps={steps} title={copy.brand} onJump={setStep} freeNav={isEdit} />
        <div className="flex flex-1 flex-col overflow-hidden">
          <div className="flex-1 overflow-y-auto">
            {step === 0 && (
              <WizardPage
                kicker={kickerOf(1)}
                title="量化数据源（选填）"
                lead="策略权重组合需要量化数据服务；只用自定义组合可直接「跳过」。要用策略组合请两项都填，并点「测试连接」确认。"
              >
                <div className="max-w-[560px]">
                  <label className={labelCls}>数据接口地址</label>
                  <input
                    className={inputCls}
                    value={draft.quant_data_api}
                    onChange={(e) => set({ quant_data_api: e.target.value })}
                    placeholder={DEFAULT_QUANT_DATA_API}
                  />
                  <label className={labelCls}>访问令牌</label>
                  <input
                    className={inputCls}
                    value={draft.quant_data_token}
                    onChange={(e) => set({ quant_data_token: e.target.value })}
                    placeholder="粘贴访问令牌"
                  />
                  <TestRow state={quantDataTest} onTest={runQuantDataTest} />
                </div>
              </WizardPage>
            )}

            {step === 1 && (
              <WizardPage
                kicker={kickerOf(2)}
                title="交易日历（选填）"
                lead="配置与胜可知交易日历契约兼容的接口后，axile 会把 SSE 与 CFFEX 日历保存到本地数据库，并在覆盖不足时自动补齐。留空令牌则关闭自动同步。"
              >
                <div className="max-w-[560px]">
                  <label className={labelCls}>交易日历接口</label>
                  <input
                    className={inputCls}
                    value={draft.trading_calendar_api}
                    onChange={(e) => set({ trading_calendar_api: e.target.value })}
                    placeholder={DEFAULT_CALENDAR_API}
                  />
                  <label className={labelCls}>开放平台令牌</label>
                  <input
                    className={inputCls}
                    type="password"
                    value={draft.trading_calendar_token}
                    onChange={(e) => set({ trading_calendar_token: e.target.value })}
                    placeholder="sk_xxx；留空则不自动同步"
                  />
                  <TestRow
                    state={calendarTest}
                    onTest={runCalendarTest}
                    disabled={!draft.trading_calendar_token.trim() || !draft.trading_calendar_api.trim()}
                  />
                </div>
              </WizardPage>
            )}

            {step === 2 && (
              <WizardPage
                kicker={kickerOf(3)}
                title="执行错误告警（选填）"
                lead="任一账户执行异常时，axile 会把错误卡片推送到此飞书机器人；系统级，区别于各账户自己的「飞书通知」。留空则不推送，可先「测试推送」发一张示例卡片确认联通。"
              >
                <div className="max-w-[560px]">
                  <label className={labelCls}>飞书机器人 key</label>
                  <input
                    className={inputCls}
                    value={draft.exe_err_feishu_key}
                    onChange={(e) => set({ exe_err_feishu_key: e.target.value })}
                    placeholder="留空则不推送"
                  />
                  <TestRow
                    state={feishuTest}
                    onTest={runFeishuTest}
                    idleLabel="测试推送"
                    disabled={!draft.exe_err_feishu_key.trim()}
                  />
                </div>
              </WizardPage>
            )}

            {step === 3 && (
              <WizardPage
                kicker={kickerOf(steps.length)}
                title={copy.confirmTitle}
                lead={copy.confirmLead}
              >
                <div className="max-w-[560px]">
                  <dl className="rounded-[14px] border border-line bg-surface px-4 py-2 text-[14px]">
                    {[
                      ['数据接口', draft.quant_data_api || '（未配置 · 仅自定义组合）'],
                      ['数据令牌', draft.quant_data_token ? '已填写' : '（空）'],
                      ['交易日历', draft.trading_calendar_token ? '已配置自动同步' : '（未配置 · 工作日回退）'],
                      ['执行告警', draft.exe_err_feishu_key ? '已配置飞书推送' : '（未配置 · 不推送）'],
                    ].map(([k, v]) => (
                      <div key={k} className="flex justify-between gap-4 border-b border-line py-2.5 last:border-0">
                        <dt className="text-ink-3">{k}</dt>
                        <dd className="truncate text-ink-1">{v}</dd>
                      </div>
                    ))}
                  </dl>

                  <details className="mt-4 rounded-[14px] border border-line bg-surface px-4 py-3">
                    <summary className="cursor-pointer text-[14px] text-ink-2">高级选项（一般保持默认）</summary>
                    <label className={labelCls}>数据库地址</label>
                    <input
                      className={inputCls}
                      value={draft.sqlalchemy_database_uri}
                      onChange={(e) => set({ sqlalchemy_database_uri: e.target.value })}
                      placeholder={DEFAULT_DB_URI}
                    />
                    <TestRow state={dbTest} onTest={runDbTest} />
                    <label className={labelCls}>运行环境</label>
                    <Select<string>
                      ariaLabel="运行环境"
                      className="w-full justify-between px-3 py-2 text-[14px]"
                      value={draft.environment}
                      onChange={(v) => set({ environment: v })}
                      options={[
                        { value: 'local', label: '本地开发（local）' },
                        { value: 'staging', label: '预发布（staging）' },
                        { value: 'production', label: '生产（production）' },
                      ]}
                    />
                    <p className="mt-1.5 text-[12px] leading-relaxed text-ink-3">
                      仅影响日志详细程度：「本地开发」打印较详细日志（INFO
                      及以上），「预发布 / 生产」更安静（仅警告及以上）。
                      <span className="text-ink-2">不改变交易行为，与实盘 / 模拟无关。</span>
                    </p>
                    <label className={labelCls}>日志目录</label>
                    <input
                      className={inputCls}
                      value={draft.app_log_dir}
                      onChange={(e) => set({ app_log_dir: e.target.value })}
                    />
                    <label className={labelCls}>日志滚动</label>
                    <input
                      className={inputCls}
                      value={draft.axile_log_rotation}
                      onChange={(e) => set({ axile_log_rotation: e.target.value })}
                    />
                    <label className={labelCls}>用户算法目录（每行一个）</label>
                    <textarea
                      className={`${inputCls} min-h-[72px] font-mono`}
                      value={draft.algorithm_directories}
                      onChange={(e) => set({ algorithm_directories: e.target.value })}
                      placeholder="./my_algorithms"
                    />
                    <p className="mt-1.5 text-[12px] leading-relaxed text-ink-3">
                      指向存放自定义算法的目录，启动时扫描其中的 <span className="num">.py</span> 并加载注册的算法；
                      保存后服务重启生效，随后在账户「怎么交易」里可选。
                    </p>
                    <label className={labelCls}>算法模块（每行一个 · 进阶）</label>
                    <textarea
                      className={`${inputCls} min-h-[72px] font-mono`}
                      value={draft.algorithm_modules}
                      onChange={(e) => set({ algorithm_modules: e.target.value })}
                      placeholder="package.module"
                    />
                  </details>
                </div>
              </WizardPage>
            )}
          </div>

          <div className="flex gap-3 border-t border-line bg-surface px-12 py-3.5">
            {isEdit ? (
              // edit=设置页：不逐级推进。左侧仅在数据源节给「清空」便捷键；右侧常驻「保存并重启」，可从任意节直接保存（经确认弹窗）。
              <>
                {step === 0 && (
                  <button
                    className="cursor-pointer rounded-[11px] border border-line bg-surface px-[22px] py-2.5 text-[14px] text-ink-2"
                    onClick={onClearDataSource}
                  >
                    {copy.skipLabel}
                  </button>
                )}
                <span className="flex-1" />
                <button
                  className="cursor-pointer rounded-[11px] border border-ink-1 bg-ink-1 px-[22px] py-2.5 text-[14px] font-[550] text-surface disabled:opacity-45"
                  onClick={onSave}
                  disabled={saveDisabled}
                >
                  {saving ? copy.savingLabel : copy.saveLabel}
                </button>
              </>
            ) : (
              // init=向导：上一步 / 跳过 + 下一步 / 保存，逐级推进。
              <>
                {step > 0 ? (
                  <button
                    className="cursor-pointer rounded-[11px] border border-line bg-surface px-[22px] py-2.5 text-[14px] text-ink-2"
                    onClick={() => setStep(step - 1)}
                  >
                    上一步
                  </button>
                ) : (
                  // 数据源为选填：常驻中性「跳过」，一眼可见这步可跳（不做入场表演、不用状态色）。
                  <button
                    className="cursor-pointer rounded-[11px] border border-line bg-surface px-[22px] py-2.5 text-[14px] text-ink-2"
                    onClick={onSkip}
                  >
                    {copy.skipLabel}
                  </button>
                )}
                <span className="flex-1" />
                <button
                  className="cursor-pointer rounded-[11px] border border-ink-1 bg-ink-1 px-[22px] py-2.5 text-[14px] font-[550] text-surface disabled:opacity-45"
                  onClick={onNext}
                  disabled={nextDisabled || saving}
                >
                  {saving ? copy.savingLabel : step === steps.length - 1 ? copy.saveLabel : '下一步'}
                </button>
              </>
            )}
          </div>
        </div>
      </div>
      <ConfirmModal spec={confirm} onClose={() => setConfirm(null)} />
      <Toast />
    </div>
  )
}
