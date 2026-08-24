import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'
import { ConfirmModal, type ConfirmSpec } from '@/components/ui/ConfirmModal'
import { Segmented } from '@/components/ui/Segmented'
import { Select } from '@/components/ui/Select'
import { Toggle } from '@/features/account/editUi'
import { getAlgorithms } from '@/lib/api/system'
import { marketForChannel, type Market } from '@/features/setup/cron'
import { useChannelDescriptor } from '@/stores/channels'
import {
  INTENT_COPY,
  algoLabel,
  defaultAlgorithm,
  describeSingleMakerParams,
  effectiveSingleMakerParams,
  effectiveTargetPosParams,
  intentFromParams,
  resolveAlgorithm,
  registerAlgorithmLabels,
  seedParams,
  validateAlgorithmParams,
  type AlgorithmRef,
  type Intent,
} from '@/features/setup/algorithms'
import { MOTION_LAYOUT } from '@/lib/viewTransition'
import type { AlgorithmInfo, AlgorithmSlot, TradeChannel } from '@/types/api'

/** 意图卡：仅色/边，≤120ms；无阴影浮起（方向 α：更静）。 */
const CARD_T =
  'transition-[border-color,background-color,color] duration-100 ease-[cubic-bezier(0.4,0,0.2,1)] motion-reduce:transition-none'

/** 换 method 时参数区交叉淡半程（总约 140+140ms）。 */
const PARAMS_FADE_MS = 140

/**
 * 换算法时：选择器行外的参数区做短交叉淡 + 高度过渡。
 * 同 method 下改 params 硬更新，不触发淡入（避免拖数字也闪）。
 */
function MethodParamsStage({ method, children }: { method: string; children: ReactNode }) {
  const methodRef = useRef(method)
  const [body, setBody] = useState(children)
  const [opaque, setOpaque] = useState(true)
  const [height, setHeight] = useState<number | undefined>(undefined)
  const innerRef = useRef<HTMLDivElement>(null)
  const heightTimerRef = useRef<number | undefined>(undefined)
  const boot = useRef(true)

  // 同 method：同步最新 children（改参数）。
  useEffect(() => {
    if (method !== methodRef.current) return
    setBody(children)
  }, [children, method])

  // 换 method：先淡出 → 换内容 → 淡入。
  useEffect(() => {
    if (method === methodRef.current) return

    const reduced =
      typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduced || boot.current) {
      methodRef.current = method
      setBody(children)
      setOpaque(true)
      setHeight(undefined)
      boot.current = false
      return
    }

    setHeight(innerRef.current?.offsetHeight)
    setOpaque(false)
    const t = window.setTimeout(() => {
      methodRef.current = method
      setBody(children)
      setOpaque(true)
    }, PARAMS_FADE_MS)
    return () => window.clearTimeout(t)
  }, [method, children])

  useEffect(() => {
    boot.current = false
    return () => {
      if (heightTimerRef.current !== undefined) window.clearTimeout(heightTimerRef.current)
    }
  }, [])

  // 只在 method 替换期间量一次新内容高度；结束后回到 auto，让内部条件展开独立走布局流。
  useLayoutEffect(() => {
    const el = innerRef.current
    if (!el || height === undefined) return
    const frame = window.requestAnimationFrame(() => {
      setHeight(el.offsetHeight)
      if (heightTimerRef.current !== undefined) window.clearTimeout(heightTimerRef.current)
      heightTimerRef.current = window.setTimeout(() => setHeight(undefined), 150)
    })
    return () => window.cancelAnimationFrame(frame)
    // body 是 method 替换的唯一触发源；height 后续变化不应重新采样自身动画。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [body])

  return (
    <div
      className={`overflow-hidden transition-[height,opacity] duration-150 ease-[cubic-bezier(0.4,0,0.2,1)] motion-reduce:transition-none`}
      style={{
        height: height != null ? height : undefined,
        opacity: opaque ? 1 : 0,
      }}
    >
      <div ref={innerRef}>{body}</div>
    </div>
  )
}

/**
 * 统一的执行算法编辑器：一个槽位（主交易 / 清仓）× 一个渠道，产出 `{method, params}`。
 *
 * 「注册表镜像」：内置算法各有专属编辑器（SINGLE-MAKER 复用意图三卡，TWAP/POV/
 * 目标持仓有定制表单），未知算法回退到通用裸 JSON。候选算法由 `/algorithms`
 * 按 `channels ∩ 当前渠道 && slots ∩ 当前槽位` 过滤，渠道/槽位限定由算法自己声明。
 * 默认安静：命中槽位默认算法时只露专属编辑器，换算法藏在折叠里。
 */

// 模块级缓存：算法清单在会话内基本不变，避免每个编辑器各拉一次。
let _algosCache: AlgorithmInfo[] | null = null
let _algosPromise: Promise<AlgorithmInfo[]> | null = null

function useAlgorithms(): AlgorithmInfo[] | null {
  const [algos, setAlgos] = useState<AlgorithmInfo[] | null>(_algosCache)
  useEffect(() => {
    if (_algosCache) return
    let alive = true
    _algosPromise ??= getAlgorithms().then((list) => {
      _algosCache = list
      registerAlgorithmLabels(list)
      return list
    })
    _algosPromise
      .then((list) => {
        if (alive) setAlgos(list)
      })
      .catch(() => {
        // 拉取失败不致命：候选清单退化为「仅当前算法」，专属编辑器仍可用。
        if (alive) setAlgos([])
      })
    return () => {
      alive = false
    }
  }, [])
  return algos
}

/** 数字框：藏原生 spinner + 产品 focus，避免系统亮蓝/箭头掉队。 */
const FIELD =
  'w-28 rounded-[9px] border border-ink-3/30 bg-surface px-3 py-1.5 text-right text-[14px] num outline-none transition-[border-color] duration-200 ease-[cubic-bezier(0.4,0,0.2,1)] focus:border-ink-2 motion-reduce:transition-none [-moz-appearance:textfield] [&::-webkit-inner-spin-button]:m-0 [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:m-0 [&::-webkit-outer-spin-button]:appearance-none'
const ROW = 'flex flex-col gap-2 border-t border-line py-3 sm:flex-row sm:items-center sm:justify-between'
const HINT = 'text-xs text-ink-3'

/** 数字输入行：读写 params 里的某个数值键，超范围时给出琥珀色提示。 */
function NumRow({
  label,
  hint,
  value,
  onChange,
  min,
  max,
  step,
  suffix,
}: {
  label: string
  hint?: string
  value: number
  onChange: (v: number) => void
  min: number
  max?: number
  step?: number
  suffix?: string
}) {
  const bad = value < min || (max !== undefined && value > max) || !Number.isFinite(value)
  return (
    <div className={ROW}>
      <span className="text-[14px]">
        {label} {hint && <span className={HINT}>{hint}</span>}
      </span>
      <span className="flex items-center gap-2">
        <input
          className={FIELD}
          type="number"
          value={Number.isFinite(value) ? value : ''}
          min={min}
          max={max}
          step={step ?? 1}
          onChange={(e) => onChange(Number(e.target.value))}
        />
        {suffix && <span className="w-6 text-[13px] text-ink-3">{suffix}</span>}
        {bad && <span className="text-[12px] text-warn">超范围</span>}
      </span>
    </div>
  )
}

type ParamsEditor = (props: {
  params: Record<string, unknown>
  onChange: (p: Record<string, unknown>) => void
  market: Market
  onApplyIntent?: (intent: Intent) => void
}) => React.ReactNode

/** SINGLE-MAKER 专属：意图三卡（省成本/保成交/平衡），复用向导文案。 */
const SingleMakerEditor: ParamsEditor = ({ params, onChange, market, onApplyIntent }) => {
  const copy = INTENT_COPY[market]
  const active = intentFromParams(params)
  const effective = effectiveSingleMakerParams(params)
  const [advanced, setAdvanced] = useState(false)
  const chaseEnabled = effective.chase_enabled === true
  const paramError = validateAlgorithmParams(params)
  const set = (patch: Record<string, unknown>) => onChange({ ...params, ...patch })
  const numberValue = (key: string): number => {
    const value = Number(effective[key])
    return Number.isFinite(value) ? value : Number.NaN
  }

  return (
    <div>
      <div className="grid grid-cols-1 gap-3.5 md:grid-cols-3">
        {(['save', 'fill', 'balance'] as Intent[]).map((k) => {
          const c = copy[k]
          const on = active === k
          return (
            <button
              key={k}
              type="button"
              aria-pressed={on}
              className={`flex flex-col gap-0.5 rounded-[14px] border p-4 text-left ${CARD_T} ${
                on ? 'border-accent bg-accent-soft' : 'border-line bg-surface'
              }`}
              onClick={() => {
                if (!on) onApplyIntent?.(k)
              }}
            >
              <span className="text-[15px] font-[640]">{c.title}</span>
              <span className="text-[12.5px] text-ink-2">{c.desc}</span>
              {/* 质量：warn=注意极（填不满），其余中性说明，不用涨跌绿表「好」 */}
              <span className={`mt-1 text-xs font-semibold ${c.warn ? 'text-warn' : 'text-ink-3'}`}>{c.note}</span>
            </button>
          )
        })}
      </div>

      <div className="mt-4 flex flex-wrap items-start justify-between gap-x-5 gap-y-2 border-t border-line pt-3">
        <div className="min-w-0 text-[13px] leading-relaxed text-ink-2">
          <span className="mr-2 text-ink-3">当前执行</span>
          {describeSingleMakerParams(params)}
          {!active && <span className="ml-2 font-semibold text-ink-2">自定义参数</span>}
          {paramError && <span className="ml-2 font-semibold text-warn">参数有误</span>}
        </div>
        <button
          type="button"
          className="flex flex-none items-center gap-1 text-[13px] font-semibold text-ink-3 hover:text-ink-1"
          aria-expanded={advanced}
          onClick={() => setAdvanced((value) => !value)}
        >
          高级设置
          <ChevronDown
            size={15}
            className={`transition-transform duration-200 motion-reduce:transition-none ${advanced ? 'rotate-180' : ''}`}
            aria-hidden
          />
        </button>
      </div>

      <div
        inert={!advanced}
        className={`grid transition-[grid-template-rows] ${MOTION_LAYOUT} ${
          advanced ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'
        }`}
      >
        <div className="min-h-0 overflow-hidden">
          <div className="mt-3 max-w-[620px]">
            <div className={ROW}>
              <span className="text-[14px]">下单价格</span>
              <Segmented
                value={String(effective.price_strategy)}
                options={[
                  { value: 'PASSIVE', label: '被动挂单' },
                  { value: 'ACTIVE', label: '主动成交' },
                ]}
                onChange={(value) => set({ price_strategy: value })}
              />
            </div>
            <NumRow
              label="单次等待时间"
              hint="1–3600"
              value={numberValue('max_wait_seconds')}
              min={1}
              max={3600}
              onChange={(value) => set({ max_wait_seconds: value })}
              suffix="秒"
            />
            <div className={ROW}>
              <span className="text-[14px]">追单</span>
              <Toggle
                on={chaseEnabled}
                ariaLabel="启用追单"
                onClick={() => set({ chase_enabled: !chaseEnabled })}
              />
            </div>
            <div
              inert={!chaseEnabled}
              className={`grid transition-[grid-template-rows] ${MOTION_LAYOUT} ${
                chaseEnabled ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'
              }`}
            >
              <div className="min-h-0 overflow-hidden pl-4">
                <NumRow
                  label="价格偏离"
                  hint="1–100"
                  value={numberValue('chase_ticks')}
                  min={1}
                  max={100}
                  onChange={(value) => set({ chase_ticks: value })}
                  suffix="档"
                />
                <NumRow
                  label="最大追单次数"
                  hint="1–50"
                  value={numberValue('max_chase_count')}
                  min={1}
                  max={50}
                  onChange={(value) => set({ max_chase_count: value })}
                  suffix="次"
                />
                <NumRow
                  label="追单间隔"
                  hint="0.1–300"
                  value={numberValue('chase_interval')}
                  min={0.1}
                  max={300}
                  step={0.1}
                  onChange={(value) => set({ chase_interval: value })}
                  suffix="秒"
                />
              </div>
            </div>
            <div className={`${ROW} gap-5`}>
              <span className="text-[14px]">盘口缺失时</span>
              <Select
                className="min-w-[220px] justify-between px-3 py-1.5 text-[14px]"
                value={String(effective.on_missing_book)}
                onChange={(value) => set({ on_missing_book: value })}
                options={[
                  { value: 'skip', label: '跳过本轮（推荐）' },
                  { value: 'active', label: '按对手价成交' },
                  { value: 'market', label: '直接市价成交' },
                ]}
              />
            </div>
            {effective.on_missing_book === 'market' && (
              <div className="-mt-1 pb-3 text-[12px] text-warn">盘口不可用时会直接发市价单，可能放大滑点。</div>
            )}
            {paramError && <div className="pb-3 text-[12px] text-warn">{paramError}</div>}
          </div>
        </div>
      </div>
    </div>
  )
}

const TwapEditor: ParamsEditor = ({ params, onChange }) => {
  const set = (patch: Record<string, unknown>) => onChange({ ...params, ...patch })
  const total = Number(params.total_duration ?? 300)
  const slices = Number(params.slices ?? 10)
  return (
    <div className="max-w-[560px]">
      <NumRow label="总执行时长" hint="秒（1–86400）" value={total} min={1} max={86400} step={30} onChange={(v) => set({ total_duration: v })} suffix="s" />
      <NumRow label="切片数量" hint="均匀切成几片（1–1000）" value={slices} min={1} max={1000} onChange={(v) => set({ slices: v })} suffix="片" />
      <div className={`${ROW} text-[14px]`}>
        <span>单片间隔</span>
        <span className="num text-ink-2">{slices > 0 ? (total / slices).toFixed(1) : '—'} s</span>
      </div>
    </div>
  )
}

const PovEditor: ParamsEditor = ({ params, onChange }) => {
  const set = (patch: Record<string, unknown>) => onChange({ ...params, ...patch })
  const ratePct = Number(params.participation_rate ?? 0.1) * 100
  const interval = Number(params.interval_seconds ?? 5)
  const maxDur = Number(params.max_duration ?? 600)
  const onTimeout = params.complete_on_timeout !== false
  return (
    <div className="max-w-[560px]">
      <NumRow label="参与率" hint="占市场成交量 %（0–100）" value={ratePct} min={0.01} max={100} step={1} onChange={(v) => set({ participation_rate: v / 100 })} suffix="%" />
      <NumRow label="下单节奏" hint="秒（≥0.1）" value={interval} min={0.1} step={0.5} onChange={(v) => set({ interval_seconds: v })} suffix="s" />
      <NumRow label="硬时间上限" hint="秒（1–86400）" value={maxDur} min={1} max={86400} step={60} onChange={(v) => set({ max_duration: v })} suffix="s" />
      <div className={`${ROW} text-[14px]`}>
        <span>
          超时兜底 <span className={HINT}>到点未成交时按市价补足</span>
        </span>
        <Segmented
          value={onTimeout ? 'on' : 'off'}
          options={[
            { value: 'on', label: '补足' },
            { value: 'off', label: '放弃' },
          ]}
          onChange={(v) => set({ complete_on_timeout: v === 'on' })}
        />
      </div>
    </div>
  )
}

const TargetPosEditor: ParamsEditor = ({ params, onChange }) => {
  const effective = effectiveTargetPosParams(params)
  const set = (patch: Record<string, unknown>) => onChange({ ...effective, ...params, ...patch })
  const ps = effective.price_strategy === 'ACTIVE' ? 'ACTIVE' : 'PASSIVE'
  const offset = effective.offset_priority === '今昨' ? '今昨' : '昨今'
  const chaseEnabled = effective.chase_enabled === true
  const paramError = validateAlgorithmParams(effective)
  const numberValue = (key: string): number => {
    const value = Number(effective[key])
    return Number.isFinite(value) ? value : Number.NaN
  }
  return (
    <div className="max-w-[620px]">
      <div className={`${ROW} text-[14px]`}>
        <span>
          价格策略 <span className={HINT}>被动挂单 / 主动吃单</span>
        </span>
        <Segmented
          value={ps}
          options={[
            { value: 'PASSIVE', label: '被动挂单' },
            { value: 'ACTIVE', label: '主动吃单' },
          ]}
          onChange={(v) => set({ price_strategy: v })}
        />
      </div>
      <div className={`${ROW} text-[14px]`}>
        <span>
          平仓优先 <span className={HINT}>先平昨仓还是今仓</span>
        </span>
        <Segmented
          value={offset}
          options={[
            { value: '昨今', label: '先昨后今' },
            { value: '今昨', label: '先今后昨' },
          ]}
          onChange={(v) => set({ offset_priority: v })}
        />
      </div>
      <NumRow
        label="单次等待时间"
        hint="每个合约等待成交（1–3600）"
        value={numberValue('max_wait_seconds')}
        min={1}
        max={3600}
        onChange={(value) => set({ max_wait_seconds: value })}
        suffix="秒"
      />
      <div className={ROW}>
        <span className="text-[14px]">
          追单 <span className={HINT}>行情偏离后撤单重挂</span>
        </span>
        <Toggle
          on={chaseEnabled}
          ariaLabel="启用目标持仓追单"
          onClick={() => set({ chase_enabled: !chaseEnabled })}
        />
      </div>
      <div
        inert={!chaseEnabled}
        className={`grid transition-[grid-template-rows] ${MOTION_LAYOUT} ${
          chaseEnabled ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'
        }`}
      >
        <div className="min-h-0 overflow-hidden pl-4">
          <NumRow
            label="价格偏离"
            hint="触发重挂的最小偏离（1–100）"
            value={numberValue('chase_ticks')}
            min={1}
            max={100}
            onChange={(value) => set({ chase_ticks: value })}
            suffix="档"
          />
          <NumRow
            label="最大追单次数"
            hint="1–50"
            value={numberValue('max_chase_count')}
            min={1}
            max={50}
            onChange={(value) => set({ max_chase_count: value })}
            suffix="次"
          />
          <NumRow
            label="追单间隔"
            hint="0.1–300"
            value={numberValue('chase_interval')}
            min={0.1}
            max={300}
            step={0.1}
            onChange={(value) => set({ chase_interval: value })}
            suffix="秒"
          />
        </div>
      </div>
      {paramError && <div className="pb-3 text-[12px] text-warn">{paramError}</div>}
    </div>
  )
}

/** 通用编辑器：自定义算法无专属 UI，直接编辑裸 JSON 参数。 */
function GenericEditor({
  info,
  params,
  onChange,
}: {
  info: AlgorithmInfo | null
  params: Record<string, unknown>
  onChange: (p: Record<string, unknown>) => void
}) {
  const [text, setText] = useState(() => JSON.stringify(params, null, 2))
  const [err, setErr] = useState<string | null>(null)
  return (
    <div className="max-w-[620px]">
      {info?.description && <div className="mb-1.5 text-[13px] text-ink-2">{info.description}</div>}
      <textarea
        className="w-full rounded-[11px] border border-ink-3/30 bg-surface p-3 font-mono text-[13px] leading-relaxed"
        rows={8}
        spellCheck={false}
        value={text}
        placeholder='{\n  "key": "value"\n}'
        onChange={(e) => {
          const t = e.target.value
          setText(t)
          const trimmed = t.trim()
          if (!trimmed) {
            setErr(null)
            onChange({})
            return
          }
          try {
            const parsed = JSON.parse(trimmed) as unknown
            if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
              setErr('params 必须是 JSON 对象')
              return
            }
            setErr(null)
            onChange(parsed as Record<string, unknown>)
          } catch (e2) {
            setErr(e2 instanceof Error ? e2.message : '无效 JSON')
          }
        }}
      />
      {err && <div className="mt-1 text-[12px] text-warn">JSON 有误：{err}</div>}
    </div>
  )
}

const DEDICATED: Record<string, ParamsEditor> = {
  'SINGLE-MAKER': SingleMakerEditor,
  TWAP: TwapEditor,
  POV: PovEditor,
  'TARGET-POS-TASK': TargetPosEditor,
}

export interface AlgorithmEditorProps {
  /** 槽位：`trade` 主交易 / `empty` 清仓。 */
  slot: AlgorithmSlot
  /** 当前账户渠道，用于过滤候选算法。 */
  channel: TradeChannel
  /** 当前算法引用；`null` 表示未设置（清仓槽可回退后端默认）。 */
  value: AlgorithmRef | null
  onChange: (v: AlgorithmRef | null) => void
  /** 是否允许清空回到「未设置」（清仓槽用）。 */
  allowClear?: boolean
}

/** 执行算法编辑器（见文件顶部说明）。 */
export function AlgorithmEditor({ slot, channel, value, onChange, allowClear }: AlgorithmEditorProps) {
  const algos = useAlgorithms()
  const channelDescriptor = useChannelDescriptor(channel)
  const market = marketForChannel(channel)
  const fallback = slot === 'trade'
    ? (channelDescriptor?.defaults.trade_algorithm ?? defaultAlgorithm(market, slot))
    : (channelDescriptor?.defaults.empty_positions_algorithm ?? defaultAlgorithm(market, slot))
  const defaultMethod = fallback.method

  const candidates = useMemo(() => {
    const list = (algos ?? []).filter(
      (a) =>
        (a.channels === null || a.channels.includes(channel)) &&
        (a.slots === null || a.slots.includes(slot)),
    )
    // 保证当前算法始终可选，即使清单未加载或该算法受限。
    const method = value?.method
    if (method && !list.some((a) => a.name === method)) {
      list.push({
        name: method,
        label: method,
        description: '',
        default_params: {},
        params_schema: {},
        channels: null,
        slots: null,
        builtin: false,
      })
    }
    return list.sort((a, b) => a.name.localeCompare(b.name))
  }, [algos, channel, slot, value?.method])

  const [open, setOpen] = useState(false)
  const [pendingIntent, setPendingIntent] = useState<Intent | null>(null)

  // 值未设置（清仓槽）：只露一行「未设置」+ 设置入口。
  if (value === null) {
    return (
      <div className="text-[14px] text-ink-2">
        <span className="text-ink-3">未设置 · 使用后端默认清仓逻辑</span>
        <button type="button" className="ml-3 cursor-pointer text-accent hover:underline" onClick={() => onChange(fallback)}>
          设置清仓算法
        </button>
      </div>
    )
  }

  const method = value.method
  const info = candidates.find((a) => a.name === method) ?? null
  const Dedicated = DEDICATED[method]
  const isDefault = method === defaultMethod
  // 非默认算法时选择器常开；默认时由 open 控制折叠。
  const showPicker = open || !isDefault

  const pick = (next: string) => {
    if (next === method) return
    const nextInfo = candidates.find((candidate) => candidate.name === next)
    onChange({ method: next, params: nextInfo?.default_params ?? seedParams(next, market) })
  }

  const setParams = (params: Record<string, unknown>) => onChange({ method, params })
  const activeIntent = method === 'SINGLE-MAKER' ? intentFromParams(value.params) : null
  const applyIntent = (intent: Intent) => {
    if (activeIntent === null) {
      setPendingIntent(intent)
      return
    }
    setParams(resolveAlgorithm(intent, market).params)
  }

  const pendingCopy = pendingIntent ? INTENT_COPY[market][pendingIntent] : null
  const confirmPreset: ConfirmSpec | null = pendingIntent && pendingCopy
    ? {
        title: `应用“${pendingCopy.title.replace('（推荐）', '')}”预设？`,
        body: '当前自定义参数将被该预设替换。页面保存前不会写入账户。',
        okText: '应用预设',
        onConfirm: () => setParams(resolveAlgorithm(pendingIntent, market).params),
      }
    : null

  return (
    <div>
      {/* 换算法：仅高度展开，无内部 fade（方向 α） */}
      <div
        className={`grid transition-[grid-template-rows] ${MOTION_LAYOUT} ${
          showPicker ? 'mb-4 grid-rows-[1fr]' : 'grid-rows-[0fr]'
        }`}
      >
        <div className="overflow-hidden">
          <div className="flex flex-wrap items-center gap-3">
            <label className="text-[13px] text-ink-2">执行算法</label>
            <Select
              className="min-w-[220px] justify-between px-3 py-1.5 text-[14px]"
              value={method}
              onChange={pick}
              options={candidates.map((a) => ({
                value: a.name,
                label: a.label || algoLabel(a.name),
                hint: a.builtin ? undefined : '自定义',
              }))}
            />
            {!isDefault && (
              <button
                type="button"
                className="text-[13px] text-ink-3 hover:text-ink-1"
                onClick={() => {
                  onChange(fallback)
                  setOpen(false)
                }}
              >
                恢复默认
              </button>
            )}
            {allowClear && (
              <button type="button" className="text-[13px] text-ink-3 hover:text-warn" onClick={() => onChange(null)}>
                清空
              </button>
            )}
            {isDefault && open && (
              <button
                type="button"
                className="text-[13px] text-ink-3 hover:text-ink-1"
                onClick={() => setOpen(false)}
              >
                收起
              </button>
            )}
          </div>
        </div>
      </div>

      {/* 换 method：仅参数区短交叉淡 + 高度；选择器行不动 */}
      <MethodParamsStage method={method}>
        {Dedicated ? (
          <Dedicated
            params={value.params}
            onChange={setParams}
            market={market}
            onApplyIntent={applyIntent}
          />
        ) : (
          <GenericEditor info={info} params={value.params} onChange={setParams} />
        )}
      </MethodParamsStage>

      {!showPicker && (
        <button
          type="button"
          className="mt-4 flex items-center gap-2 text-[12px] font-semibold tracking-wide text-ink-3 hover:text-ink-1"
          onClick={() => setOpen(true)}
        >
          ▸ 换执行算法
        </button>
      )}
      <ConfirmModal spec={confirmPreset} onClose={() => setPendingIntent(null)} />
    </div>
  )
}
