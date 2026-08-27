/**
 * 定时任务编辑器（向导「定时」步与账户编辑页共用）。
 *
 * 总开关 + 快捷|高级|自定义 + 补发 + 排程预览。
 * ``layout='step'``（默认，向导窄栏）：单栏，预览在底部。
 * ``layout='page'``（账户编辑页宽栏）：页面级两列，预览为右侧通高列，
 * 预览条数按右栏实际可视高度自适应。
 * 动效与 :component:`AcctTimer` 原实现一致：panel-fade / grid 展开 / Segmented 滑块。
 */

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Segmented } from '@/components/ui/Segmented'
import { Select } from '@/components/ui/Select'
import { ScheduleTimeRow } from '@/components/ui/ScheduleTimeRow'
import { MOTION_LAYOUT, useRemountFade } from '@/lib/viewTransition'
import { executionReasonText } from '@/features/account/executionReason'
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
import {
  appendSchedulePreview,
  PREVIEW_MIN_ITEMS,
  PREVIEW_PREFETCH_ROWS,
  PREVIEW_ROW_PITCH,
  previewLimitForHeight,
  schedulePreviewItemPresentation,
} from '@/features/setup/previewTimeline'
import { previewSchedule, type SchedulePreview } from '@/lib/api/accounts'
import type { TradeChannel } from '@/types/api'

export type { TimerEditorState }

const PREVIEW_SENTINEL_MARGIN = PREVIEW_ROW_PITCH * 2
const PREVIEW_WIDE_QUERY = '(min-width: 1120px)'
const PREVIEW_CASCADE_DELAY_STEP = 16
const PREVIEW_CASCADE_DELAY_MAX = 160
const PREVIEW_CASCADE_SETTLE_MS = 380

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
function calendarSummary(preview: SchedulePreview | null): { text: string; warning: boolean } {
  if (!preview) return { text: '交易日历 · 正在判断', warning: false }
  const calendar = preview.calendar
  if (calendar.requirement === 'not_required') return { text: '无需交易日历 · 24/7', warning: false }
  if (calendar.availability === 'available') {
    const coverage = calendar.coverage_end ? ` · 覆盖至 ${calendar.coverage_end}` : ''
    return { text: `${calendar.label ?? '中国交易日历'} · 可用${coverage}`, warning: false }
  }
  const reason = calendar.unavailable_reason === 'uncovered' ? '日期超出覆盖' : '读取失败'
  return {
    text: `${calendar.label ?? '中国交易日历'} · ${reason}，按排程执行`,
    warning: true,
  }
}

export function TimerEditor({ tradeChannel, scheduleKind, nightSchedule, value, onChange, layout = 'step' }: TimerEditorProps) {
  const v = value
  const tabFade = useRemountFade(v.timerTab)
  const [schedulePreview, setSchedulePreview] = useState<SchedulePreview | null>(null)
  const [previewLoadingMore, setPreviewLoadingMore] = useState(false)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [previewMoreError, setPreviewMoreError] = useState<string | null>(null)
  const [previewWide, setPreviewWide] = useState(false)
  const [previewLimit, setPreviewLimit] = useState(PREVIEW_MIN_ITEMS)
  const [previewCascade, setPreviewCascade] = useState({ generation: 0, active: false })
  const previewRequestId = useRef(0)
  const previewAppendRequestId = useRef(0)
  const previewAppendController = useRef<AbortController | null>(null)
  const previewListRef = useRef<HTMLDivElement | null>(null)
  const previewSentinelRef = useRef<HTMLDivElement | null>(null)
  const previewLimitRef = useRef(PREVIEW_MIN_ITEMS)
  const previewResultKey = useRef<string | null>(null)
  const previewCascadePending = useRef(false)

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
  const previewKey = tradeChannel && cronExpr ? `${tradeChannel}\u0000${cronExpr}` : ''
  // 是否会发起预览请求（与下方 effect 的提前返回条件一致）：首帧据此直接上骨架，
  // 避免「占位文案 → 骨架 → 列表」三段跳闪。
  const expectPreview = Boolean(tradeChannel) && v.autoOn && !rawErr && Boolean(cronExpr)

  // 右栏列表区是真实可视槽：直接量它的高度换算请求条数，窗口尺寸变化由
  // ResizeObserver 驱动；窄视口退回 5 条，避免自然高度布局形成测量反馈环。
  useEffect(() => {
    if (layout !== 'page') {
      previewLimitRef.current = PREVIEW_MIN_ITEMS
      setPreviewWide(false)
      setPreviewLimit(PREVIEW_MIN_ITEMS)
      return
    }
    const list = previewListRef.current
    if (!list) return
    const media = window.matchMedia(PREVIEW_WIDE_QUERY)
    const updateLimit = () => {
      const wide = media.matches
      setPreviewWide(wide)
      if (!wide) {
        previewLimitRef.current = PREVIEW_MIN_ITEMS
        setPreviewLimit(PREVIEW_MIN_ITEMS)
        return
      }
      const height = list.clientHeight
      if (height <= 0) return
      const next = previewLimitForHeight(height)
      previewLimitRef.current = next
      setPreviewLimit((current) => (current === next ? current : next))
    }
    updateLimit()
    const observer = new ResizeObserver(updateLimit)
    observer.observe(list)
    media.addEventListener('change', updateLimit)
    return () => {
      observer.disconnect()
      media.removeEventListener('change', updateLimit)
    }
  }, [layout])

  // 重算级联只覆盖新数据换入的约 340ms；随后移除 animation class，确保
  // ResizeObserver 导致的增减行静默发生，不把窗口调整误演成「重新排程」。
  useEffect(() => {
    if (!previewCascade.active) return
    const generation = previewCascade.generation
    const timer = window.setTimeout(() => {
      setPreviewCascade((current) => (
        current.generation === generation ? { ...current, active: false } : current
      ))
    }, PREVIEW_CASCADE_SETTLE_MS)
    return () => window.clearTimeout(timer)
  }, [previewCascade.active, previewCascade.generation])

  // 规则/渠道变化建立一条新的未来时间线；resize 只更新后续批次大小，不进入依赖，
  // 因此不会把已看到的内容清空再从「现在」重抓。
  useEffect(() => {
    const requestId = ++previewRequestId.current
    previewAppendRequestId.current += 1
    previewAppendController.current?.abort()
    previewAppendController.current = null
    setPreviewLoadingMore(false)
    setPreviewMoreError(null)

    if (!tradeChannel || !v.autoOn || rawErr || !cronExpr || !previewKey) {
      previewResultKey.current = null
      previewCascadePending.current = false
      setSchedulePreview(null)
      setPreviewError(null)
      return
    }

    const priorKey = previewResultKey.current
    previewCascadePending.current = layout === 'page' && priorKey != null && priorKey !== previewKey
    previewResultKey.current = null
    setSchedulePreview(null)
    setPreviewError(null)
    if (layout === 'page') previewListRef.current?.scrollTo({ top: 0 })

    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      const limit = layout === 'page' ? previewLimitRef.current : PREVIEW_MIN_ITEMS
      void previewSchedule(tradeChannel, cronExpr, { limit }, controller.signal)
        .then((next) => {
          if (requestId !== previewRequestId.current) return
          previewResultKey.current = previewKey
          setSchedulePreview(next)
          if (previewCascadePending.current) {
            setPreviewCascade((current) => ({ generation: current.generation + 1, active: true }))
          }
          previewCascadePending.current = false
        })
        .catch((error) => {
          if (controller.signal.aborted || requestId !== previewRequestId.current) return
          previewCascadePending.current = false
          setPreviewError(error instanceof Error ? error.message : String(error))
        })
    }, 250)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [tradeChannel, v.autoOn, rawErr, cronExpr, layout, previewKey])

  const loadMore = useCallback(() => {
    const cursor = schedulePreview?.next_cursor
    if (
      layout !== 'page'
      || !previewWide
      || !tradeChannel
      || !v.autoOn
      || rawErr
      || !cronExpr
      || !previewKey
      || !cursor
      || !schedulePreview.has_more
      || previewLoadingMore
      || previewAppendController.current != null
    ) return

    const requestId = ++previewAppendRequestId.current
    const controller = new AbortController()
    previewAppendController.current = controller
    setPreviewLoadingMore(true)
    setPreviewMoreError(null)
    void previewSchedule(
      tradeChannel,
      cronExpr,
      { after: cursor, limit: previewLimit },
      controller.signal,
    )
      .then((next) => {
        if (requestId !== previewAppendRequestId.current || previewResultKey.current !== previewKey) return
        setSchedulePreview((current) => (
          current ? appendSchedulePreview(current, next, cursor) : current
        ))
        setPreviewLoadingMore(false)
        if (previewAppendController.current === controller) previewAppendController.current = null
      })
      .catch((error) => {
        if (controller.signal.aborted || requestId !== previewAppendRequestId.current) return
        setPreviewMoreError(error instanceof Error ? error.message : String(error))
        setPreviewLoadingMore(false)
        if (previewAppendController.current === controller) previewAppendController.current = null
      })
  }, [
    layout,
    previewWide,
    tradeChannel,
    v.autoOn,
    rawErr,
    cronExpr,
    previewKey,
    previewLimit,
    previewLoadingMore,
    schedulePreview?.has_more,
    schedulePreview?.next_cursor,
  ])

  // 底部哨兵提前两行触发；续取失败时停住自动重试，交给底部「重试」命令。
  useEffect(() => {
    if (
      layout !== 'page'
      || !previewWide
      || !schedulePreview?.has_more
      || !schedulePreview.next_cursor
      || previewLoadingMore
      || previewMoreError
    ) return
    const root = previewListRef.current
    const sentinel = previewSentinelRef.current
    if (!root || !sentinel) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) loadMore()
      },
      { root, rootMargin: `0px 0px ${PREVIEW_SENTINEL_MARGIN}px 0px` },
    )
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [
    layout,
    previewWide,
    schedulePreview?.has_more,
    schedulePreview?.next_cursor,
    previewLoadingMore,
    previewMoreError,
    loadMore,
  ])

  useEffect(() => () => {
    previewRequestId.current += 1
    previewAppendRequestId.current += 1
    previewAppendController.current?.abort()
  }, [])

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
  const summary = calendarSummary(schedulePreview)

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
      </div>
      <div className={`mb-2.5 text-xs ${summary.warning ? 'text-warn' : 'text-ink-3'}`}>
        {summary.text}
      </div>
    </>
  )

  const cascadeRows = layout === 'page' && previewCascade.active

  // !v.autoOn 只在 page 布局可达（step 的预览随总开关收进折叠区，不会渲染）。
  const previewBody = !v.autoOn ? (
    <p className="text-[14px] text-ink-3">开启自动调仓后显示。</p>
  ) : !tradeChannel ? (
    <p className="text-[14px] text-ink-3">选择交易渠道后显示。</p>
  ) : rawErr ? (
    <p className="text-[14px] text-ink-3">修正自定义节奏后显示。</p>
  ) : customEmpty ? (
    <p className="text-[14px] text-ink-3">输入自定义节奏后显示。</p>
  ) : previewError ? (
    <p className="border-l-2 border-warn px-3 text-[14px] text-warn">预览暂不可用，仍可保存。{previewError}</p>
  ) : expectPreview && !schedulePreview ? (
    <div className="space-y-2" aria-label="正在加载排程预览">{Array.from({ length: 4 }, (_, index) => <div key={index} className="h-4 w-full animate-pulse rounded bg-fill motion-reduce:animate-none" />)}</div>
  ) : schedulePreview?.items.length ? (
    <div key={previewCascade.generation} role="list" aria-label="未来排程预览" className="space-y-1.5">
      {schedulePreview.items.map((item, index) => {
        const presentation = schedulePreviewItemPresentation(item, executionReasonText)
        return (
          <ScheduleTimeRow
            key={item.scheduled_at}
            scheduledAt={item.scheduled_at}
            trailing={presentation.text}
            now={Date.parse(schedulePreview.evaluated_at)}
            tone={presentation.tone}
            className={cascadeRows ? 'schedule-preview-row-in' : ''}
            style={cascadeRows ? {
              animationDelay: `${Math.min(index * PREVIEW_CASCADE_DELAY_STEP, PREVIEW_CASCADE_DELAY_MAX)}ms`,
            } : undefined}
          />
        )
      })}
      {layout === 'page' && previewWide && schedulePreview.has_more && (
        <div ref={previewSentinelRef} className="pt-1">
          {previewLoadingMore ? (
            <div className="space-y-2" aria-label="正在推演更多未来排程">
              {Array.from({ length: PREVIEW_PREFETCH_ROWS }, (_, index) => (
                <div key={index} className="h-4 w-full animate-pulse rounded bg-fill motion-reduce:animate-none" />
              ))}
            </div>
          ) : previewMoreError ? (
            <div className="flex items-center justify-between gap-2 border-l-2 border-warn px-2 text-[13px] text-warn">
              <span title={previewMoreError}>未来排程续取失败</span>
              <button type="button" className="flex-none font-semibold hover:underline" onClick={loadMore}>
                重试
              </button>
            </div>
          ) : (
            <div className="h-px" aria-hidden="true" />
          )}
        </div>
      )}
    </div>
  ) : (
    <p className="text-[14px] text-ink-3">选择有效节奏后显示。</p>
  )

  // page 布局：预览是页面级右列——与编辑流同起于开关行，高度由外层高度链（视口）
  // 决定、与左列内容完全解耦，两列各自内部滚动，页面本身不滚。常挂载：关自动调仓
  // 时显示提示而非整列消失，避免开关切换引发布局跳动。step 布局：底部通栏。
  const previewPanel = layout === 'page' ? (
    <aside className="flex flex-col rounded-[14px] border border-line bg-surface px-4 py-3.5 min-[1120px]:min-h-0">
      <div className="flex-none">{previewHeader}</div>
      <div
        ref={previewListRef}
        className="quiet-scrollbar min-h-0 flex-1 min-[1120px]:overflow-y-auto min-[1120px]:overscroll-contain min-[1120px]:[scrollbar-gutter:stable]"
      >
        {previewBody}
      </div>
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
