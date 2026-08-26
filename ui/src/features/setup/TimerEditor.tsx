/**
 * 定时节奏编辑器（向导「定时」步与账户编辑页共用）。
 *
 * 总开关 + 快捷|高级|自定义 + 补发 + 排程预览。
 * ``layout='step'``（默认，向导窄栏）：单栏，预览在底部。
 * ``layout='page'``（账户编辑页宽栏）：页面级两列，预览为右侧通高列，
 * 日历摘要归入预览头部，预览条目更密（12 条）。
 * 动效与 :component:`AcctTimer` 原实现一致：panel-fade / grid 展开 / Segmented 滑块。
 */

import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from '@/components/ui/nav'
import { OverflowText } from '@/components/ui/OverflowText'
import { Segmented } from '@/components/ui/Segmented'
import { Select } from '@/components/ui/Select'
import { MOTION_LAYOUT, useRemountFade } from '@/lib/viewTransition'
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
import { TimerAdvanced, TimerCustom } from '@/features/setup/TimerAdvanced'
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
  /**
   * 排布上下文。``'step'``（默认）：向导窄栏单栏，预览在底部；
   * ``'page'``：账户编辑页宽栏，预览为右侧通高列（高度由页面高度链决定、
   * 与编辑列解耦，两列各自滚动、页面不滚；窄视口自动退回单栏）。
   */
  layout?: 'page' | 'step'
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

export function TimerEditor({ tradeChannel, scheduleKind, nightSchedule, value, onChange, layout = 'step' }: TimerEditorProps) {
  const v = value
  const tabFade = useRemountFade(v.timerTab)
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
        scheduleRules: [rule],
        selectedRuleId: rule.id,
        timerTab: 'quick',
      })
    }
    // 仅响应调度类型；preset 合法性随调度类型校验
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scheduleKind])

  const customEmpty = v.timerTab === 'custom' && !v.rawCron.trim()
  const rawErr = v.timerTab === 'custom' && !customEmpty ? cronError(v.rawCron) : null
  const cronList = v.autoOn ? resolveCronList(scheduleKind, v, nightSchedule) : []
  const cronExpr = rawErr ? '' : cronToExpr(cronList)
  // 是否会发起预览请求（与下方 effect 的提前返回条件一致）：首帧据此直接上骨架，
  // 避免「占位文案 → 骨架 → 列表」三段跳闪。
  const expectPreview = Boolean(tradeChannel) && v.autoOn && !rawErr && Boolean(cronExpr)

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
      // page 布局的右列通高，条目拉满（100，后端上限）让栏有内容质量；step 底部通栏维持 5 条。
      void previewSchedule(tradeChannel, cronExpr, controller.signal, layout === 'page' ? 100 : 5)
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
  }, [tradeChannel, v.autoOn, rawErr, cronExpr, layout])

  useEffect(() => () => { previewRequestId.current += 1 }, [])

  const summary = tradeChannel
    ? calendarSummary(schedulePreview)
    : { text: '交易日历 · 选择渠道后判断', warning: false }

  const setTab = (tab: 'quick' | 'advanced' | 'custom') => {
    if (tab === 'custom') {
      const rawCron = v.rawCron.trim()
        ? v.rawCron
        : cronToExpr(resolveCronList(scheduleKind, v, nightSchedule))
      patch({ timerTab: 'custom', rawCron })
      return
    }
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
    patch({ timerTab: 'quick' })
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

  const summaryText = previewLoading && !schedulePreview ? '交易日历 · 正在判断' : summary.text

  /** 编辑区列：tabs + 当前 tab 内容 + 补发。 */
  const editorColumn = (
    <>
      <div>
        <Segmented<'quick' | 'advanced' | 'custom'>
          size="sm"
          value={v.timerTab}
          onChange={setTab}
          options={[
            { value: 'quick', label: '快捷' },
            { value: 'advanced', label: '高级' },
            { value: 'custom', label: '自定义' },
          ]}
        />
      </div>

      <div key={v.timerTab} className={tabFade ? 'panel-fade-in' : undefined}>
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
        ) : v.timerTab === 'advanced' ? (
          <TimerAdvanced
            market={scheduleKind}
            rules={v.scheduleRules}
            selectedId={v.selectedRuleId}
            onChangeRules={(scheduleRules, selectedRuleId) => patch({ scheduleRules, selectedRuleId })}
          />
        ) : (
          <TimerCustom
            rawCron={v.rawCron}
            rawErr={rawErr}
            onRawCron={(rawCron) => patch({ rawCron })}
          />
        )}
      </div>

      <div
        inert={v.timerTab === 'custom'}
        className={`grid transition-[grid-template-rows] ${MOTION_LAYOUT} ${
          v.timerTab === 'custom' ? 'grid-rows-[0fr]' : 'grid-rows-[1fr]'
        }`}
      >
        <div className="min-h-0 overflow-hidden">
          <SupRow
            supN={v.supN}
            supM={v.supM}
            onN={(supN) => patch({ supN })}
            onM={(supM) => patch({ supM })}
          />
        </div>
      </div>
    </>
  )

  const previewHeader = (
    <>
      <div className="mb-1.5 flex items-center justify-between gap-3">
        <div className="text-sm font-[640]">排程预览 · 北京时间</div>
        {schedulePreview?.calendar.requirement === 'required' && (
          <Link to="/settings/trading-calendar" className="flex-none text-[12px] text-accent hover:underline">
            交易日历设置
          </Link>
        )}
      </div>
      <OverflowText
        className={`mb-2.5 min-w-0 text-xs ${summary.warning ? 'text-warn' : 'text-ink-3'}`}
        text={summaryText}
      />
    </>
  )

  // !v.autoOn 只在 page 布局可达（step 的预览随总开关收进折叠区，不会渲染）。
  const previewBody = !v.autoOn ? (
    <p className="text-[13px] text-ink-3">开启自动调仓后显示。</p>
  ) : !tradeChannel ? (
    <p className="text-[13px] text-ink-3">选择交易渠道后显示。</p>
  ) : rawErr ? (
    <p className="text-[13px] text-ink-3">修正自定义节奏后显示。</p>
  ) : customEmpty ? (
    <p className="text-[13px] text-ink-3">输入自定义节奏后显示。</p>
  ) : previewError ? (
    <p className="border-l-2 border-warn px-3 text-[13px] text-warn">预览暂不可用，仍可保存。{previewError}</p>
  ) : expectPreview && !schedulePreview ? (
    <div className="space-y-2" aria-label="正在加载排程预览">{Array.from({ length: 4 }, (_, index) => <div key={index} className="h-4 w-full animate-pulse rounded bg-fill motion-reduce:animate-none" />)}</div>
  ) : schedulePreview?.items.length ? (
    <div className="space-y-1.5">
      {schedulePreview.items.map((item) => {
        const tradingDay = item.calendar_day.slice(5)
        const legacy = item.using_legacy_fallback
          ? `${item.label ?? '中国交易日历'} · 存量兼容闭市保护中（A 股日历未覆盖） · `
          : ''
        const text = item.reason_code === 'CALENDAR.NO_NIGHT_SESSION'
          ? '无对应夜盘，已跳过'
          : item.calendar_status === 'available_open'
          ? `${legacy}${tradingDay} 交易日，执行`
          : item.calendar_status === 'available_closed'
            ? `${legacy}休市，已跳过`
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
  )

  // page 布局：预览是页面级右列——与编辑流同起于开关行，高度由外层高度链（视口）
  // 决定、与左列内容完全解耦，两列各自内部滚动，页面本身不滚。常挂载：关自动调仓
  // 时显示提示而非整列消失，避免开关切换引发布局跳动。step 布局：底部通栏。
  const previewPanel = layout === 'page' ? (
    <aside className="rounded-[14px] border border-line bg-surface px-4 py-3.5 min-[1120px]:min-h-0 min-[1120px]:overflow-y-auto">
      {previewHeader}
      {previewBody}
    </aside>
  ) : (
    <div className="min-h-[152px] border-y border-line py-3">
      {previewHeader}
      {previewBody}
    </div>
  )

  const switchRow = (
    <div className="flex items-center gap-3">
      <Switch ariaLabel="自动调仓" on={v.autoOn} onClick={() => patch({ autoOn: !v.autoOn })} />
      <div>
        <div className="text-sm font-[640]">{v.autoOn ? '自动调仓已开' : '自动调仓已关'}</div>
        <div className="text-xs text-ink-3">{v.autoOn ? '按下面的节奏自动执行' : '仅手动 / 外接触发'}</div>
      </div>
    </div>
  )

  const autoOnCollapse = (children: ReactNode) => (
    <div
      className={`grid transition-[grid-template-rows,opacity] ${MOTION_LAYOUT} ${
        v.autoOn ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'
      }`}
    >
      {/* 收放（grid-fr + opacity）已是全部连续性，不再叠 panel-fade-in：
          一个对象只跑一套范式；且该类若在挂载后的无关重渲染补挂，会重播入场闪一下。 */}
      <div className="overflow-hidden">{children}</div>
    </div>
  )

  if (layout === 'page') {
    // 高度链：AppShell(h-full) → section(h-full flex-col) → 包装(flex-1 min-h-0)
    // → 此处 h-full → grid 单行 minmax(0,1fr)，两列拉伸充满、各自滚动。
    return (
      <div className="min-[1120px]:h-full">
        <div className="grid grid-cols-1 gap-6 min-[1120px]:h-full min-[1120px]:grid-cols-[minmax(0,1fr)_300px] min-[1120px]:grid-rows-[minmax(0,1fr)]">
          <div className="min-w-0 space-y-5 min-[1120px]:min-h-0 min-[1120px]:overflow-y-auto">
            {switchRow}
            {autoOnCollapse(<div className="space-y-5">{editorColumn}</div>)}
          </div>
          {previewPanel}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      {switchRow}
      {autoOnCollapse(
        <div className="space-y-5">
          {editorColumn}
          {previewPanel}
        </div>,
      )}
    </div>
  )
}

/** 自定义模式的内容错误；无则 null。 */
export function timerEditorError(state: TimerEditorState): string | null {
  if (!state.autoOn || state.timerTab !== 'custom') return null
  return state.rawCron.trim() ? cronError(state.rawCron) : '自定义节奏不能为空。'
}
