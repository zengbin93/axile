/**
 * 账户详情「自动执行」轻量节奏弹层（方案 B）。
 *
 * 只做高频：总开关 + 快捷预设 + 补发 + 下次预览。高级 / 多规则 / 裸 cron 链到编辑页。
 * 壳与 :component:`ImportModal` 同级（居中 dialog + scrim），不进完整 :component:`TimerEditor`。
 */

import { useEffect, useState } from 'react'
import { Link } from '@/components/ui/nav'
import { Select } from '@/components/ui/Select'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { MOTION_LAYOUT, usePanelFadeReady } from '@/lib/viewTransition'
import {
  DEFAULT_PRESET,
  PRESETS,
  cronExprEqual,
  defaultTimerEditorState,
  fmtFire,
  nextFires,
  parseTimerIntent,
  resolveCronList,
  ruleFromPreset,
  timerStateToCronExpr,
  type ScheduleKind,
  type TimerEditorState,
} from '@/features/setup/cron'
import { updateAccount } from '@/lib/api/accounts'
import { useToastStore } from '@/stores/ui'
import { useChannelDescriptor } from '@/stores/channels'

function Switch({ on, onClick }: { on: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={onClick}
      className={`relative h-[27px] w-[46px] flex-none rounded-full transition-colors ${MOTION_LAYOUT} ${
        on ? 'bg-accent' : 'bg-border-strong'
      }`}
    >
      <span
        className={`absolute top-[3px] h-[21px] w-[21px] rounded-full bg-surface shadow transition-all ${MOTION_LAYOUT} ${
          on ? 'left-[22px]' : 'left-[3px]'
        }`}
      />
    </button>
  )
}

/**
 * 打开弹层时的草稿：能落在快捷则原样；高级/自定义则降级为快捷默认，并标 ``fromComplex``。
 */
function draftFromCron(market: ScheduleKind, cronExpr: string): { state: TimerEditorState; fromComplex: boolean } {
  const parsed = parseTimerIntent(market, cronExpr)
  const quick = parsed.timerTab === 'quick' && !parsed.customCronOn
  if (quick) return { state: { ...parsed, timerTab: 'quick', customCronOn: false, rawCron: '' }, fromComplex: false }

  // 有表达式但非快捷：保留开关，预设回到市场默认，避免误把高级时刻当已选中。
  const base = defaultTimerEditorState(market)
  return {
    state: {
      ...base,
      autoOn: parsed.autoOn,
      timerTab: 'quick',
      customCronOn: false,
      rawCron: '',
    },
    fromComplex: parsed.autoOn,
  }
}

/** 编译时强制快捷意图（弹层不允许 custom / advanced 编译路径）。 */
function asQuickIntent(market: ScheduleKind, s: TimerEditorState): TimerEditorState {
  const id = s.presetIds[0] ?? DEFAULT_PRESET[market]
  const rule = ruleFromPreset(market, id)
  return {
    ...s,
    timerTab: 'quick',
    customCronOn: false,
    rawCron: '',
    presetIds: [id],
    scheduleRules: [rule],
    selectedRuleId: rule.id,
  }
}

export interface TimerQuickModalProps {
  open: boolean
  accountId: number
  accountName: string
  tradeChannel: string
  /** 当前存储的 cron_expr。 */
  cronExpr: string
  onClose: () => void
  /** 保存成功后刷新详情 / next_run / 仪表盘。 */
  onSaved: () => void
}

/**
 * 轻量定时弹层。
 */
function TimerQuickModalReady({
  open,
  accountId,
  accountName,
  scheduleKind,
  cronExpr,
  onClose,
  onSaved,
}: TimerQuickModalProps & { scheduleKind: ScheduleKind }) {
  const toast = useToastStore((s) => s.toast)
  const market = scheduleKind
  const bodyFade = usePanelFadeReady()

  const [state, setState] = useState<TimerEditorState>(() => draftFromCron(market, cronExpr).state)
  const [fromComplex, setFromComplex] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<Error | null>(null)

  useEffect(() => {
    if (!open) return
    const d = draftFromCron(market, cronExpr)
    setState(d.state)
    setFromComplex(d.fromComplex)
    setSaving(false)
    setSaveError(null)
  }, [open, market, cronExpr])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !saving) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose, saving])

  const patch = (p: Partial<TimerEditorState>) => {
    setSaveError(null)
    setState((prev) => ({ ...prev, ...p }))
  }

  const pickPreset = (id: string) => {
    const rule = ruleFromPreset(market, id)
    patch({
      presetIds: [id],
      scheduleRules: [rule],
      selectedRuleId: rule.id,
      timerTab: 'quick',
      customCronOn: false,
      rawCron: '',
    })
    setFromComplex(false)
  }

  const intent = asQuickIntent(market, state)
  const cronNext = timerStateToCronExpr(market, intent)
  const dirty = !cronExprEqual(cronNext, cronExpr)
  const fires = state.autoOn ? nextFires(resolveCronList(market, intent), 4) : []

  const save = async () => {
    if (!dirty) {
      onClose()
      return
    }
    setSaving(true)
    setSaveError(null)
    try {
      await updateAccount(accountId, { cron_expr: cronNext })
      toast(cronNext ? '节奏已更新' : '已关闭自动调仓节奏')
      onSaved()
      onClose()
    } catch (e) {
      setSaveError(e instanceof Error ? e : new Error(String(e)))
    } finally {
      setSaving(false)
    }
  }

  const presetCardT =
    'transition-[border-color,background-color,box-shadow] duration-200 ease-[cubic-bezier(0.4,0,0.2,1)] motion-reduce:transition-none'

  return (
    <>
      <div
        className={`fixed inset-0 z-[35] bg-scrim transition-opacity duration-150 ${
          open ? 'opacity-100' : 'pointer-events-none opacity-0'
        }`}
        onClick={() => !saving && onClose()}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="调整定时节奏"
        className={`fixed left-1/2 top-1/2 z-[36] flex max-h-[86vh] w-[480px] max-w-[92vw] -translate-x-1/2 flex-col rounded-[18px] bg-surface shadow-[0_24px_60px_rgba(0,0,0,0.24)] transition-all duration-150 ${
          open ? '-translate-y-1/2 opacity-100' : 'pointer-events-none -translate-y-[46%] opacity-0'
        }`}
      >
        {open && (
          <>
            <div className="flex items-start justify-between px-[22px] pt-5 pb-3">
              <div>
                <div className="text-[17px] font-[640]">定时节奏</div>
                <div className="mt-1 text-[13px] text-ink-2">
                  {accountName} · 快捷预设 · 时间均为北京时间
                </div>
              </div>
              <button
                type="button"
                className="cursor-pointer text-[20px] leading-none text-ink-3 hover:text-ink-1"
                onClick={() => !saving && onClose()}
                aria-label="关闭"
              >
                ✕
              </button>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto px-[22px] pb-2">
              {fromComplex && (
                <div className="mb-4 rounded-[10px] border-l-2 border-warn/60 bg-warn-tint/50 py-2 pl-3 pr-2 text-[12.5px] text-ink-2">
                  当前为高级或自定义节奏。在此保存将改为下方快捷预设；完整编辑请到账户编辑页。
                </div>
              )}

              <div className="space-y-5">
                <div className="flex items-center gap-3">
                  <Switch on={state.autoOn} onClick={() => patch({ autoOn: !state.autoOn })} />
                  <div>
                    <div className="text-sm font-[640]">{state.autoOn ? '自动调仓已开' : '自动调仓已关'}</div>
                    <div className="text-xs text-ink-3">
                      {state.autoOn ? '按下方节奏自动执行' : '仅手动 / 外接触发'}
                    </div>
                  </div>
                </div>

                <div
                  className={`grid transition-[grid-template-rows,opacity] ${MOTION_LAYOUT} ${
                    state.autoOn ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'
                  }`}
                >
                  <div className="overflow-hidden">
                    <div className={`space-y-4 ${state.autoOn && bodyFade.current ? 'panel-fade-in' : ''}`}>
                      <div>
                        <div className="mb-2 text-sm font-[640]">节奏</div>
                        <div className="flex flex-wrap gap-2">
                          {PRESETS[market].map((p) => {
                            const on = state.presetIds.includes(p.id)
                            return (
                              <button
                                key={p.id}
                                type="button"
                                onClick={() => pickPreset(p.id)}
                                className={`min-w-[92px] rounded-[11px] border p-2.5 text-left ${presetCardT} ${
                                  on
                                    ? 'border-accent bg-accent-soft shadow-[inset_0_0_0_1px_var(--color-accent)]'
                                    : 'border-line bg-surface'
                                }`}
                              >
                                <div className="text-sm font-[640]">{p.label}</div>
                                {p.sub && <div className="text-xs text-ink-3">{p.sub}</div>}
                              </button>
                            )
                          })}
                        </div>
                      </div>

                      <div className="flex flex-wrap items-center gap-2 text-sm">
                        <span className="text-ink-3">到点后补发</span>
                        <Select<number>
                          ariaLabel="补发次数"
                          value={state.supN}
                          onChange={(supN) => patch({ supN })}
                          options={[0, 1, 2, 3, 4].map((n) => ({ value: n, label: String(n) }))}
                        />
                        <span className="text-ink-3">次 · 每隔</span>
                        <Select<number>
                          ariaLabel="补发间隔分钟"
                          value={state.supM}
                          onChange={(supM) => patch({ supM })}
                          options={[1, 2, 3, 5].map((n) => ({ value: n, label: String(n) }))}
                        />
                        <span className="text-ink-3">分</span>
                      </div>

                      <div>
                        <div className="mb-1 text-sm font-[640]">
                          下次排程 <span className="text-xs font-normal text-ink-3">预览 · 北京时间</span>
                        </div>
                        <div className="flex flex-wrap gap-x-3 gap-y-1">
                          {fires.length ? (
                            fires.map((f, i) => (
                              <span key={i} className={`text-sm ${i === 0 ? 'font-[640]' : 'text-ink-3'}`}>
                                {fmtFire(f)}
                              </span>
                            ))
                          ) : (
                            <span className="text-sm text-ink-3">— 选择节奏后显示 —</span>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="border-t border-line pt-3">
                  <Link
                    to={`/accounts/${accountId}/edit/timer`}
                    className="text-[12.5px] font-semibold text-accent hover:underline"
                    onClick={onClose}
                  >
                    高级节奏 · 多时刻 / Cron 表达式 →
                  </Link>
                </div>
              </div>
              <ErrorNotice title="保存定时节奏失败" error={saveError} variant="mutation" onRetry={save} />
            </div>

            <div className="mt-1 flex justify-end gap-2.5 border-t border-line px-5 py-3.5">
              <button
                type="button"
                className="cursor-pointer rounded-[9px] border border-line bg-surface px-4 py-2 text-sm text-ink-2 disabled:opacity-45"
                onClick={onClose}
                disabled={saving}
              >
                取消
              </button>
              <button
                type="button"
                className="cursor-pointer rounded-[9px] border border-ink-1 bg-ink-1 px-[18px] py-2 text-sm font-[550] text-surface disabled:opacity-45"
                onClick={() => void save()}
                disabled={saving || !dirty}
              >
                {saving ? '保存中…' : '保存'}
              </button>
            </div>
          </>
        )}
      </div>
    </>
  )
}

/** 渠道能力未加载时不猜测调度类型，也不挂载可编辑弹层。 */
export function TimerQuickModal(props: TimerQuickModalProps) {
  const scheduleKind = useChannelDescriptor(props.tradeChannel)?.schedule.kind
  return scheduleKind ? <TimerQuickModalReady {...props} scheduleKind={scheduleKind} /> : null
}
