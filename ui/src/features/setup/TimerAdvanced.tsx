/**
 * 定时「高级」tab：节奏面排版 + 动效语言对齐。
 *
 * 排版：主锚（时刻/频率名）居中，频率全贴合 Segmented 贴顶，周几围下；多条时右侧目录。
 * 动效约定：
 * - 单↔双栏：目录 width/opacity 状态类过渡 200ms（Drawer 语汇，非入场表演）
 * - 主锚日频↔周期：key 重挂 + panel-fade-in（首帧不播，见 usePanelFadeReady）
 * - 自定义区：textarea panel-fade-in
 * - 频率：Segmented 滑块；周几/目录：transition-colors 200ms
 * - 无生命体征 loop；Mac 滚轮菜单自带 select-pop-in
 */

import { MacTimePicker } from '@/components/ui/MacTimePicker'
import { OverflowText } from '@/components/ui/OverflowText'
import { Segmented } from '@/components/ui/Segmented'
import { MOTION_LAYOUT, usePanelFadeReady } from '@/lib/viewTransition'
import type { ScheduleKind } from '@/features/setup/cron'
import {
  isRuleComplete,
  isValidTime,
  makeEmptySlot,
  type CustomFreq,
  type ScheduleRule,
  type Anchor,
} from '@/features/setup/cron'

const DOW_LABELS = ['日', '一', '二', '三', '四', '五', '六'] as const

const FREQ_OPTIONS: { value: CustomFreq; label: string }[] = [
  { value: 'm15', label: '15 分' },
  { value: 'm60', label: '1 小时' },
  { value: 'm120', label: '2 小时' },
  { value: 'm240', label: '4 小时' },
  { value: 'd1', label: '每天' },
]

const FREQ_TITLE: Record<CustomFreq, string> = {
  m15: '每 15 分钟',
  m60: '每小时',
  m120: '每 2 小时',
  m240: '每 4 小时',
  d1: '每天',
}

const CHIP_T =
  'transition-colors duration-200 ease-[cubic-bezier(0.4,0,0.2,1)] motion-reduce:transition-none'

/** 与定时页总开关同款。 */
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

export interface TimerAdvancedProps {
  market: ScheduleKind
  rules: ScheduleRule[]
  selectedId: string
  customCronOn: boolean
  onChangeRules: (rules: ScheduleRule[], selectedId: string) => void
}

export interface TimerCustomCronProps {
  customCronOn: boolean
  rawCron: string
  rawErr: string | null
  onCustomCronOn: (on: boolean) => void
  onRawCron: (v: string) => void
}

function patchRule(rule: ScheduleRule, patch: Partial<ScheduleRule>): ScheduleRule {
  const next = { ...rule, ...patch }
  if (next.freq === 'd1') {
    next.draft = !isValidTime(next.time)
  } else {
    next.draft = false
    if (!next.time) next.time = '00:00'
  }
  return next
}

function defaultDaysHint(): string {
  return '不限日期'
}

function daysSub(days: number[]): string {
  if (!days.length) return defaultDaysHint()
  if (days.length === 7) return '每天'
  const work = [1, 2, 3, 4, 5]
  if (days.length === 5 && work.every((d) => days.includes(d))) return '工作日'
  return `周${[...days]
    .sort((a, b) => a - b)
    .map((d) => DOW_LABELS[d])
    .join('')}`
}

function ruleLines(rule: ScheduleRule): { title: string; sub: string } {
  if (rule.draft && rule.freq === 'd1' && !isValidTime(rule.time)) {
    return { title: '新时间', sub: '未设置' }
  }
  const days = daysSub(rule.days)
  if (rule.freq === 'd1') {
    const t = isValidTime(rule.time) ? rule.time : '—:—'
    return { title: t, sub: days }
  }
  return { title: FREQ_TITLE[rule.freq], sub: days }
}

/** 主锚下方的周几。 */
function DayStrip({
  days,
  onToggle,
  onReset,
}: {
  days: number[]
  onToggle: (d: number) => void
  onReset: () => void
}) {
  const customized = days.length > 0
  return (
    <div className="flex flex-col items-center gap-2">
      <div className="flex items-center gap-2 text-[12px] text-ink-3">
        <span>重复 · {customized ? daysSub(days) : defaultDaysHint()}</span>
        {customized && (
          <button type="button" className="font-semibold text-accent hover:underline" onClick={onReset}>
            默认
          </button>
        )}
      </div>
      <div className="flex flex-wrap justify-center gap-1.5">
        {DOW_LABELS.map((lab, d) => {
          const active = customized && days.includes(d)
          return (
            <button
              key={lab}
              type="button"
              aria-pressed={Boolean(active)}
              onClick={() => onToggle(d)}
              className={`flex h-8 w-8 items-center justify-center rounded-full text-[12.5px] font-[640] ${CHIP_T} ${
                active
                  ? 'bg-accent text-white'
                  : customized
                    ? 'bg-fill text-ink-3 hover:text-ink-1'
                    : 'bg-fill text-ink-2 hover:bg-border-strong/35'
              }`}
            >
              {lab}
            </button>
          )
        })}
      </div>
    </div>
  )
}

/**
 * 高级节奏编辑器。
 */
export function TimerAdvanced({ market, rules, selectedId, customCronOn, onChangeRules }: TimerAdvancedProps) {
  const multi = rules.length >= 2
  const selected = rules.find((r) => r.id === selectedId) ?? rules[0]
  const showTime = selected?.freq === 'd1'
  const showAnchor =
    market !== 'continuous' &&
    selected != null &&
    (selected.freq === 'd1' || selected.freq === 'm240') &&
    !isValidTime(selected.time)

  const heroFade = usePanelFadeReady()
  // 主锚身份：日频合为一类，周期按 freq 分，避免 15↔60 无谓重挂闪。
  const heroKey = showTime ? 'd1-time' : `interval-${selected?.freq ?? 'm15'}`

  const replaceSelected = (patch: Partial<ScheduleRule>) => {
    if (!selected) return
    const next = rules.map((r) => (r.id === selected.id ? patchRule(r, patch) : r))
    onChangeRules(next, selected.id)
  }

  const setFreq = (v: CustomFreq) => {
    if (!selected) return
    if (v === 'd1') {
      const time = isValidTime(selected.time)
        ? selected.time
        : market === 'continuous'
          ? '08:00'
          : selected.time || '09:30'
      replaceSelected({ freq: v, time, draft: !isValidTime(time) })
      return
    }
    replaceSelected({ freq: v, draft: false })
  }

  const enterMulti = () => {
    if (!selected || multi) return
    const first = patchRule(selected, {
      draft: selected.freq === 'd1' ? !isValidTime(selected.time) : false,
    })
    const slot = makeEmptySlot(first)
    onChangeRules([first, slot], slot.id)
  }

  const addSlot = () => {
    const base = selected ?? rules[0]
    if (!base) return
    const slot = makeEmptySlot(base)
    onChangeRules([...rules, slot], slot.id)
  }

  const selectRule = (id: string) => onChangeRules(rules, id)

  const removeRule = (id: string) => {
    const next = rules.filter((r) => r.id !== id)
    if (next.length <= 1) {
      const only = next[0]
      if (!only) return
      onChangeRules([only], only.id)
      return
    }
    const nextSel = selectedId === id ? next[0]!.id : selectedId
    onChangeRules(next, nextSel)
  }

  const toggleDay = (d: number) => {
    if (!selected) return
    if (selected.days.length === 0) {
      replaceSelected({ days: [d] })
      return
    }
    const has = selected.days.includes(d)
    const days = has ? selected.days.filter((x) => x !== d) : [...selected.days, d].sort((a, b) => a - b)
    replaceSelected({ days })
  }

  if (!selected) return null

  const dim = customCronOn

  const surface = (
    <div className={`flex flex-col items-center px-5 py-6 ${dim ? 'pointer-events-none opacity-40' : ''}`}>
      <Segmented<CustomFreq>
        size="sm"
        value={selected.freq}
        onChange={setFreq}
        options={FREQ_OPTIONS}
        className="max-w-full"
      />

      {/* 主锚：身份变才淡；首帧不播 */}
      <div
        key={heroKey}
        className={`mt-6 flex min-h-[88px] flex-col items-center justify-center gap-3 ${
          heroFade.current ? 'panel-fade-in' : ''
        }`}
      >
        {showTime ? (
          <>
            <MacTimePicker
              value={isValidTime(selected.time) ? selected.time : ''}
              onChange={(time) => replaceSelected({ time, draft: !time })}
            />
            <span className="text-[11.5px] text-ink-3">北京时间</span>
          </>
        ) : (
          <div className="text-center">
            <div className="font-mono text-[28px] font-[640] tracking-tight text-ink-1">
              {FREQ_TITLE[selected.freq]}
            </div>
            <div className="mt-1 text-[11.5px] text-ink-3">北京时间</div>
          </div>
        )}

        {showAnchor && (
          <Segmented<Anchor>
            size="sm"
            value={selected.anchor}
            onChange={(v) => replaceSelected({ anchor: v })}
            options={[
              { value: 'open', label: '开盘' },
              { value: 'close', label: '临收' },
            ]}
          />
        )}
      </div>

      <div className="mt-6">
        <DayStrip
          days={selected.days}
          onToggle={toggleDay}
          onReset={() => replaceSelected({ days: [] })}
        />
      </div>

      {/* 组合入口：multi 时用高度/透明度收起，避免硬切消失 */}
      <div
        className={`grid transition-[grid-template-rows,opacity] ${MOTION_LAYOUT} ${
          multi ? 'grid-rows-[0fr] opacity-0' : 'grid-rows-[1fr] opacity-100'
        }`}
      >
        <div className="overflow-hidden">
          <button
            type="button"
            onClick={enterMulti}
            tabIndex={multi ? -1 : 0}
            className="mt-7 text-[12.5px] font-semibold text-accent hover:underline"
          >
            ＋ 加入多个时间
          </button>
        </div>
      </div>
    </div>
  )

  // 目录常挂载，靠 width 过渡进出（状态类切换），保证收起也有动画。
  const catalog = (
    <div
      className={`flex shrink-0 flex-col overflow-hidden border-l transition-[width,opacity,border-color] ${MOTION_LAYOUT} ${
        multi
          ? `w-[156px] border-line sm:w-[176px] ${dim ? 'pointer-events-none opacity-40' : 'opacity-100'}`
          : 'pointer-events-none w-0 border-transparent opacity-0'
      }`}
      aria-hidden={!multi}
    >
      <div className="w-[156px] sm:w-[176px]">
        <div className="px-3 pt-3 pb-1.5 text-[11px] font-semibold tracking-wide text-ink-3">时间</div>
        <ul className="min-h-0">
          {rules.map((r, i) => {
            const active = r.id === selected.id
            const incomplete = !isRuleComplete(r)
            const { title, sub } = ruleLines(r)
            return (
              <li key={r.id}>
                <div
                  className={`group flex items-start gap-0.5 px-2 py-2.5 ${CHIP_T} ${
                    active ? 'bg-accent-soft' : 'hover:bg-bg-subtle'
                  }`}
                >
                  <button type="button" className="min-w-0 flex-1 px-1 text-left" onClick={() => selectRule(r.id)}>
                    <div className="flex min-w-0 items-baseline gap-1.5">
                      <span className="text-[10px] tabular-nums text-ink-3">{i + 1}</span>
                      <OverflowText
                        className={`min-w-0 flex-1 text-[13.5px] font-[620] tabular-nums ${
                          incomplete ? 'text-ink-3' : 'text-ink-1'
                        }`}
                        text={title}
                      />
                    </div>
                    <div className="mt-0.5 pl-4">
                      <OverflowText className="text-[11.5px] text-ink-3" text={sub} />
                    </div>
                  </button>
                  <button
                    type="button"
                    aria-label="删除"
                    className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded text-ink-3 opacity-0 group-hover:opacity-100 hover:bg-fill hover:text-ink-1 ${CHIP_T}`}
                    onClick={() => removeRule(r.id)}
                  >
                    ×
                  </button>
                </div>
              </li>
            )
          })}
        </ul>
        <button
          type="button"
          onClick={addSlot}
          className="w-full border-t border-line px-3 py-2.5 text-left text-[12.5px] font-semibold text-accent hover:underline"
        >
          ＋ 再加一条
        </button>
      </div>
    </div>
  )

  return (
    <div className="flex items-stretch overflow-hidden rounded-[14px] border border-line bg-surface">
      <div
        className={`min-w-0 flex-1 transition-opacity ${MOTION_LAYOUT} ${dim ? 'opacity-40' : 'opacity-100'}`}
      >
        {surface}
      </div>
      {catalog}
    </div>
  )
}

/**
 * 高级 tab 最底部的自定义表达式开关与编辑区。
 */
export function TimerCustomCron({ customCronOn, rawCron, rawErr, onCustomCronOn, onRawCron }: TimerCustomCronProps) {
  const fade = usePanelFadeReady()
  return (
    <div className="border-t border-line pt-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-[14px] font-[640]">Cron 表达式</div>
          <div className="text-xs text-ink-3">开启后以 Cron 为准，上方图形配置不再生效</div>
        </div>
        <Switch on={customCronOn} onClick={() => onCustomCronOn(!customCronOn)} />
      </div>
      {/* grid-rows 过渡：开时展开，关时收起，避免硬切 */}
      <div
        className={`grid transition-[grid-template-rows,opacity] ${MOTION_LAYOUT} ${
          customCronOn ? 'mt-3 grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'
        }`}
      >
        <div className="overflow-hidden">
          <div className={customCronOn && fade.current ? 'panel-fade-in' : ''}>
            <div className="mb-1.5 text-xs text-ink-3">多条用 | 分隔 · 北京时间 · 5 段 Cron</div>
            <textarea
              value={rawCron}
              onChange={(e) => onRawCron(e.target.value)}
              placeholder="0 8 * * * | 0 20 * * 0,2,4"
              tabIndex={customCronOn ? 0 : -1}
              className="min-h-[80px] w-full rounded-[9px] border border-ink-3/30 bg-surface p-3 font-mono text-xs outline-none focus:border-ink-2"
            />
            {rawErr && <div className="mt-1 text-xs text-warn">{rawErr}</div>}
          </div>
        </div>
      </div>
    </div>
  )
}
