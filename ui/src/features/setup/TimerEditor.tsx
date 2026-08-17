/**
 * 定时节奏编辑器（向导「定时」步与账户编辑页共用）。
 *
 * 总开关 + 快捷|高级 + 补发 + 下次执行预览；自定义表达式仅在高级 tab 底部。
 * 动效与 :component:`AcctTimer` 原实现一致：panel-fade / grid 展开 / Segmented 滑块。
 */

import { useEffect, useRef } from 'react'
import { Segmented } from '@/components/ui/Segmented'
import { Select } from '@/components/ui/Select'
import { MOTION_LAYOUT, usePanelFadeReady } from '@/lib/viewTransition'
import {
  marketForChannel,
  DEFAULT_PRESET,
  MARKET_NAME,
  PRESETS,
  cronError,
  defaultScheduleRule,
  fmtFire,
  nextFires,
  resolveCronList,
  ruleFromPreset,
  type Market,
  type TimerEditorState,
} from '@/features/setup/cron'
import { TimerAdvanced, TimerCustomCron } from '@/features/setup/TimerAdvanced'

export type { TimerEditorState }

/** 自动调仓总开关（accent，与成败红绿解耦）。 */
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
  market: Market
  value: TimerEditorState
  onChange: (next: TimerEditorState | ((prev: TimerEditorState) => TimerEditorState)) => void
}

/**
 * 受控定时编辑器。
 *
 * Parameters
 * ----------
 * market : Market
 *     账户市场（决定预设与高级默认）。
 * value : TimerEditorState
 *     当前意图状态。
 * onChange : fn
 *     状态更新；支持函数式 patch。
 */
export function TimerEditor({ market, value, onChange }: TimerEditorProps) {
  const tabFade = usePanelFadeReady()
  const bodyFade = usePanelFadeReady()
  const v = value

  const patch = (p: Partial<TimerEditorState>) => {
    onChange((prev) => ({ ...prev, ...p }))
  }

  // 市场切换时若当前预设不合法，重置到该市场默认（编辑页市场不可改，向导切渠道会触发）。
  const prevMarket = useRef(market)
  useEffect(() => {
    const valid = PRESETS[market].some((p) => v.presetIds.includes(p.id))
    if (prevMarket.current !== market || !valid) {
      prevMarket.current = market
      const rule = defaultScheduleRule(market)
      onChange({
        ...v,
        presetIds: [DEFAULT_PRESET[market]],
        rawCron: '',
        customCronOn: false,
        scheduleRules: [rule],
        selectedRuleId: rule.id,
        timerTab: 'quick',
      })
    }
    // 仅响应 market；preset 合法性随 market 校验
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [market])

  const rawErr = v.customCronOn && v.rawCron.trim() ? cronError(v.rawCron) : null
  const cronList = v.autoOn ? resolveCronList(market, v) : []
  const fires = rawErr ? [] : nextFires(cronList, 5)

  const setTab = (tab: 'quick' | 'advanced') => {
    if (tab === 'advanced') {
      if (v.scheduleRules.length >= 1) {
        patch({
          timerTab: 'advanced',
          selectedRuleId: v.selectedRuleId || v.scheduleRules[0]!.id,
        })
        return
      }
      const rule = ruleFromPreset(market, v.presetIds[0] ?? DEFAULT_PRESET[market])
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
    const rule = ruleFromPreset(market, id)
    patch({ presetIds: [id], scheduleRules: [rule], selectedRuleId: rule.id })
  }

  const presetCardT =
    'transition-[border-color,background-color,box-shadow] duration-200 ease-[cubic-bezier(0.4,0,0.2,1)] motion-reduce:transition-none'

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <Switch on={v.autoOn} onClick={() => patch({ autoOn: !v.autoOn })} />
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
              <span className="text-xs text-ink-3">市场 · {MARKET_NAME[market]}</span>
            </div>

            <div key={v.timerTab} className={tabFade.current ? 'panel-fade-in' : undefined}>
              {v.timerTab === 'quick' ? (
                <div>
                  <div className="mb-2">
                    <label className="text-sm font-[640]">节奏</label>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {PRESETS[market].map((p) => {
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
                  {market === 'ctp' && (
                    <div className="mt-2 text-xs text-ink-3">
                      夜盘及品种时段差异大，请用「高级」或自定义表达式。
                    </div>
                  )}
                </div>
              ) : (
                <TimerAdvanced
                  market={market}
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

            <div>
              <div className="mb-1 text-sm font-[640]">
                下次执行 <span className="text-xs font-normal text-ink-3">北京时间</span>
              </div>
              <div className="flex flex-wrap gap-x-3 gap-y-1">
                {rawErr ? (
                  <span className="text-sm text-ink-3">— 修正表达式后显示 —</span>
                ) : fires.length ? (
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

/** 由 trade_channel 解析市场（编辑页便捷 re-export）。 */
export function marketFromChannel(channel: string): Market {
  return marketForChannel(channel)
}

/** 自定义模式开启时的表达式错误；无则 null。 */
export function timerEditorError(state: TimerEditorState): string | null {
  if (!state.autoOn || !state.customCronOn) return null
  return state.rawCron.trim() ? cronError(state.rawCron) : null
}
