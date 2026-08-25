/**
 * 定时节奏编辑器（向导「定时」步与账户编辑页共用）。
 *
 * 总开关 + 快捷|高级 + 补发 + 排程预览；自定义表达式仅在高级 tab 底部。
 * 动效与 :component:`AcctTimer` 原实现一致：panel-fade / grid 展开 / Segmented 滑块。
 */

import { useEffect, useRef, useState } from 'react'
import { Link } from '@/components/ui/nav'
import { OverflowText } from '@/components/ui/OverflowText'
import { Segmented } from '@/components/ui/Segmented'
import { Select } from '@/components/ui/Select'
import { MOTION_LAYOUT, usePanelFadeReady } from '@/lib/viewTransition'
import {
  DEFAULT_PRESET,
  PRESETS,
  cronError,
  cronToExpr,
  defaultScheduleRule,
  resolveCronList,
  ruleFromPreset,
  type NightSchedule,
  type ScheduleKind,
  type TimerEditorState,
} from '@/features/setup/cron'
import { TimerAdvanced, TimerCustomCron } from '@/features/setup/TimerAdvanced'
import { previewSchedule, type SchedulePreview, type ScheduleUnavailableReason } from '@/lib/api/accounts'
import type { TradeChannel } from '@/types/api'

export type { TimerEditorState }

/** 自动调仓总开关（accent，与成败红绿解耦）。 */
function Switch({ on, ariaLabel, onClick }: { on: boolean; ariaLabel: string; onClick: () => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-label={ariaLabel}
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

/** 补发行（快捷 / 高级共用）。 */
function SupRow({
  supN,
  supM,
  onN,
  onM,
}: {
  supN: number
  supM: number
  onN: (n: number) => void
  onM: (m: number) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span className="text-ink-3">到点后补发</span>
      <Select<number>
        ariaLabel="补发次数"
        value={supN}
        onChange={onN}
        options={[0, 1, 2, 3, 4].map((n) => ({ value: n, label: String(n) }))}
      />
      <span className="text-ink-3">次 · 每隔</span>
      <Select<number>
        ariaLabel="补发间隔分钟"
        value={supM}
        onChange={onM}
        options={[1, 2, 3, 5].map((n) => ({ value: n, label: String(n) }))}
      />
      <span className="text-ink-3">分</span>
    </div>
  )
}

export interface TimerEditorProps {
  tradeChannel: TradeChannel
  scheduleKind: ScheduleKind
  nightSchedule?: NightSchedule | null
  value: TimerEditorState
  onChange: (next: TimerEditorState | ((prev: TimerEditorState) => TimerEditorState)) => void
}

/**
 * 受控定时编辑器。
 *
 * Parameters
 * ----------
 * scheduleKind : ScheduleKind
 *     渠道调度类型（决定预设与高级默认）。
 * value : TimerEditorState
 *     当前意图状态。
 * onChange : fn
 *     状态更新；支持函数式 patch。
 */
function formatScheduledAt(value: string): string {
  const parts = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(new Date(value))
  const get = (type: Intl.DateTimeFormatPartTypes) => parts.find((part) => part.type === type)?.value ?? ''
  return `${get('month')}-${get('day')} ${get('hour')}:${get('minute')}`
}

function calendarSummary(preview: SchedulePreview | null): { text: string; warning: boolean } {
  if (!preview) return { text: '交易日历 · 正在判断', warning: false }
  const calendar = preview.calendar
  if (calendar.requirement === 'not_required') return { text: '无需交易日历 · 24/7', warning: false }
  if (calendar.availability === 'available') {
    const coverage = calendar.coverage_end ? ` · 覆盖至 ${calendar.coverage_end}` : ''
    return { text: `${calendar.label ?? '交易日历'} · 可用${coverage}`, warning: false }
  }
  const reasonText: Record<ScheduleUnavailableReason, string> = {
    not_configured: '不可用 · 按排程执行',
    uncovered: '当前日期不可用 · 按排程执行',
    read_failed: '暂时不可用 · 按排程执行',
  }
  const reason = calendar.unavailable_reason ?? 'read_failed'
  return {
    text: `${calendar.label ?? '交易日历'} · ${reasonText[reason]}`,
    warning: reason === 'read_failed',
  }
}

export function TimerEditor({ tradeChannel, scheduleKind, nightSchedule, value, onChange }: TimerEditorProps) {
  const tabFade = usePanelFadeReady()
  const bodyFade = usePanelFadeReady()
  const v = value
  const [schedulePreview, setSchedulePreview] = useState<SchedulePreview | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const previewRequestId = useRef(0)
  const previousChannel = useRef(tradeChannel)

  const patch = (p: Partial<TimerEditorState>) => {
    onChange((prev) => ({ ...prev, ...p }))
  }

  // 市场切换时若当前预设不合法，重置到该市场默认（编辑页市场不可改，向导切渠道会触发）。
  const previousScheduleKind = useRef(scheduleKind)
  useEffect(() => {
    const valid = PRESETS[scheduleKind].some((p) => v.presetIds.includes(p.id))
    if (previousScheduleKind.current !== scheduleKind || !valid) {
      previousScheduleKind.current = scheduleKind
      const rule = defaultScheduleRule(scheduleKind)
      onChange({
        ...v,
        presetIds: [DEFAULT_PRESET[scheduleKind]],
        nightOn: false,
        rawCron: '',
        customCronOn: false,
        scheduleRules: [rule],
        selectedRuleId: rule.id,
        timerTab: 'quick',
      })
    }
    // 仅响应调度类型；preset 合法性随调度类型校验
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scheduleKind])

  const rawErr = v.customCronOn && v.rawCron.trim() ? cronError(v.rawCron) : null
  const cronList = v.autoOn ? resolveCronList(scheduleKind, v, nightSchedule) : []
  const cronExpr = rawErr ? '' : cronToExpr(cronList)

  useEffect(() => {
    if (previousChannel.current !== tradeChannel) {
      previousChannel.current = tradeChannel
      setSchedulePreview(null)
      setPreviewError(null)
    }
    const requestId = ++previewRequestId.current
    if (!tradeChannel || !v.autoOn || rawErr || !cronExpr) {
      setSchedulePreview(null)
      setPreviewLoading(false)
      setPreviewError(null)
      return
    }
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      setPreviewLoading(true)
      setPreviewError(null)
      void previewSchedule(tradeChannel, cronExpr, controller.signal)
        .then((next) => {
          if (requestId !== previewRequestId.current) return
          setSchedulePreview(next)
          setPreviewLoading(false)
        })
        .catch((error) => {
          if (controller.signal.aborted || requestId !== previewRequestId.current) return
          setPreviewError(error instanceof Error ? error.message : String(error))
          setPreviewLoading(false)
        })
    }, 250)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [tradeChannel, v.autoOn, rawErr, cronExpr])

  useEffect(() => () => { previewRequestId.current += 1 }, [])

  const summary = tradeChannel
    ? calendarSummary(schedulePreview)
    : { text: '交易日历 · 选择渠道后判断', warning: false }

  const setTab = (tab: 'quick' | 'advanced') => {
    if (tab === 'advanced') {
      if (v.scheduleRules.length >= 1) {
        patch({
          timerTab: 'advanced',
          selectedRuleId: v.selectedRuleId || v.scheduleRules[0]!.id,
        })
        return
      }
      const rule = ruleFromPreset(scheduleKind, v.presetIds[0] ?? DEFAULT_PRESET[scheduleKind])
      patch({ timerTab: 'advanced', scheduleRules: [rule], selectedRuleId: rule.id })
      return
    }
    patch({ timerTab: 'quick', customCronOn: false })
  }

  const togglePreset = (id: string) => {
    if (v.scheduleRules.length >= 2) {
      patch({ presetIds: [id] })
      return
    }
    const rule = ruleFromPreset(scheduleKind, id)
    patch({ presetIds: [id], scheduleRules: [rule], selectedRuleId: rule.id })
  }

  const presetCardT =
    'transition-[border-color,background-color,box-shadow] duration-200 ease-[cubic-bezier(0.4,0,0.2,1)] motion-reduce:transition-none'

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <Switch ariaLabel="自动调仓" on={v.autoOn} onClick={() => patch({ autoOn: !v.autoOn })} />
        <div>
          <div className="text-sm font-[640]">{v.autoOn ? '自动调仓已开' : '自动调仓已关'}</div>
          <div className="text-xs text-ink-3">{v.autoOn ? '按下面的节奏自动执行' : '仅手动 / 外接触发'}</div>
        </div>
      </div>

      <div
        className={`grid transition-[grid-template-rows,opacity] ${MOTION_LAYOUT} ${
          v.autoOn ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'
        }`}
      >
        <div className="overflow-hidden">
          <div className={`space-y-5 ${v.autoOn && bodyFade.current ? 'panel-fade-in' : ''}`}>
            <div className="flex items-center justify-between gap-3">
              <Segmented<'quick' | 'advanced'>
                size="sm"
                value={v.timerTab}
                onChange={setTab}
                options={[
                  { value: 'quick', label: '快捷' },
                  { value: 'advanced', label: '高级' },
                ]}
              />
              <OverflowText
                className={`min-w-0 text-xs ${summary.warning ? 'text-warn' : 'text-ink-3'}`}
                text={previewLoading && !schedulePreview ? '交易日历 · 正在判断' : summary.text}
              />
            </div>

            <div key={v.timerTab} className={tabFade.current ? 'panel-fade-in' : undefined}>
              {v.timerTab === 'quick' ? (
                <div>
                  <div className="mb-2">
                    <label className="text-sm font-[640]">节奏</label>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {PRESETS[scheduleKind].map((p) => {
                      const on = v.presetIds.includes(p.id)
                      return (
                        <button
                          key={p.id}
                          type="button"
                          onClick={() => togglePreset(p.id)}
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
                  {nightSchedule && (
                    <div className="mt-4 flex items-center gap-3">
                      <Switch
                        ariaLabel={nightSchedule.label}
                        on={v.nightOn}
                        onClick={() => patch({ nightOn: !v.nightOn })}
                      />
                      <div className="min-w-0">
                        <div className="text-sm font-[640]">{nightSchedule.label}</div>
                        <div className="text-xs text-ink-3">{nightSchedule.range_label}</div>
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <TimerAdvanced
                  market={scheduleKind}
                  rules={v.scheduleRules}
                  selectedId={v.selectedRuleId}
                  customCronOn={v.customCronOn}
                  onChangeRules={(scheduleRules, selectedRuleId) => patch({ scheduleRules, selectedRuleId })}
                />
              )}
            </div>

            <SupRow
              supN={v.supN}
              supM={v.supM}
              onN={(supN) => patch({ supN })}
              onM={(supM) => patch({ supM })}
            />

            <div className="min-h-[152px] border-y border-line py-3">
              <div className="mb-2 flex items-center justify-between gap-3">
                <div className="text-sm font-[640]">排程预览 · 北京时间</div>
                {schedulePreview?.calendar.requirement === 'required' && <Link to="/settings/trading-calendar" className="text-[12px] text-accent hover:underline">交易日历设置</Link>}
              </div>
              {!tradeChannel ? (
                <p className="text-[13px] text-ink-3">选择交易渠道后显示。</p>
              ) : rawErr ? (
                <p className="text-[13px] text-ink-3">修正 Cron 表达式后显示。</p>
              ) : previewError ? (
                <p className="border-l-2 border-warn px-3 text-[13px] text-warn">预览暂不可用，仍可保存。{previewError}</p>
              ) : previewLoading && !schedulePreview ? (
                <div className="space-y-2" aria-label="正在加载排程预览">{Array.from({ length: 4 }, (_, index) => <div key={index} className="h-4 w-full animate-pulse rounded bg-fill motion-reduce:animate-none" />)}</div>
              ) : schedulePreview?.items.length ? (
                <div className="space-y-1.5">
                  {schedulePreview.items.map((item) => {
                    const tradingDay = item.calendar_day.slice(5)
                    const text = item.reason_code === 'CALENDAR.NO_NIGHT_SESSION'
                      ? '无对应夜盘，已跳过'
                      : item.calendar_status === 'available_open'
                      ? `${tradingDay} 交易日，执行`
                      : item.calendar_status === 'available_closed'
                        ? '休市，已跳过'
                        : item.calendar_status === 'unavailable'
                          ? '日历不可用，按排程执行'
                          : '按排程执行'
                    const warning = item.calendar_status === 'unavailable'
                      && item.unavailable_reason === 'read_failed'
                    return <div key={item.scheduled_at} className={`grid grid-cols-[92px_minmax(0,1fr)] gap-3 text-[13px] ${warning ? 'text-warn' : item.action === 'skip' ? 'text-ink-3' : 'text-ink-2'}`}><span className="num">{formatScheduledAt(item.scheduled_at)}</span><span>{text}</span></div>
                  })}
                </div>
              ) : (
                <p className="text-[13px] text-ink-3">选择有效节奏后显示。</p>
              )}
            </div>

            <div
              className={`grid transition-[grid-template-rows,opacity] ${MOTION_LAYOUT} ${
                v.timerTab === 'advanced' ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'
              }`}
            >
              <div className="overflow-hidden">
                <TimerCustomCron
                  customCronOn={v.customCronOn}
                  rawCron={v.rawCron}
                  rawErr={rawErr}
                  onCustomCronOn={(customCronOn) =>
                    patch({
                      customCronOn,
                      rawCron: customCronOn ? v.rawCron : '',
                    })
                  }
                  onRawCron={(rawCron) => patch({ rawCron, customCronOn: true })}
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

/** 自定义模式开启时的表达式错误；无则 null。 */
export function timerEditorError(state: TimerEditorState): string | null {
  if (!state.autoOn || !state.customCronOn) return null
  return state.rawCron.trim() ? cronError(state.rawCron) : null
}
