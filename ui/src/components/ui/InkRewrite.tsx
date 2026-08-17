/**
 * 同槽日记式换字（in-place text crossfade）。
 *
 * 纸/槽不动，旧句退场、新句进场——Tom Riddle 日记气质的蒸馏版：墨褪再显。
 * 不是 FLIP、不是共享元素、不是内容 morph。首帧就位不播；仅 text 真变时重写。
 *
 * 墨随句走：颜色/流光类（``textClassName``）按层快照——旧句以旧色褪、新句以新色显，
 * 槽外父级瞬时改色染不到退场层（琥珀告警不会被先染蓝再退场）。
 *
 * tone:
 * - ``label``：控件标签（如 启动↔暂停），纯 opacity 交叉淡。
 * - ``prose``：状态句，淡 + 极轻 blur（墨晕收锐），略日记一点。
 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react'

/**
 * 与 theme.css ``ink-rewrite-*`` 时长对齐（ms）。
 *
 * 比工具台默认 130–160ms 慢一档：贴近电影里墨褪再显，而不是控件闪一下。
 * label（按钮）略短；prose（状态句）更慢、更「写完一行」。
 */
export const INK_REWRITE_MS_LABEL = 420
export const INK_REWRITE_MS_PROSE = 620

/** fluid 槽宽过渡时长/缓动（略短于溶字，让版面先落定、字随后收干）。数值为眼调起点。 */
const FLUID_W_MS = 440
const FLUID_W_EASE = 'cubic-bezier(.4,0,.2,1)'
/** @deprecated 取 prose 上限，供单测/门禁「仍在交叉淡档」用。 */
export const INK_REWRITE_MS = INK_REWRITE_MS_PROSE

export type InkTone = 'label' | 'prose'

/** 按笔法取退场清理时长。 */
export function inkRewriteMs(tone: InkTone): number {
  return tone === 'prose' ? INK_REWRITE_MS_PROSE : INK_REWRITE_MS_LABEL
}

export type InkPair = {
  cur: string
  /** cur 层的「墨」（颜色/流光类）：随句快照，进层穿新墨。 */
  curCls: string
  prev: string | null
  /** prev 层的旧墨：旧句以旧色退场，不被新态瞬时染色。 */
  prevCls: string | null
  gen: number
}

/**
 * 计算下一帧日记对（纯函数，供测试与组件共用）。
 *
 * 颜色/流光是句子身份的一部分，随句快照进对：出层穿 ``prevCls``（旧墨以旧色褪），
 * 进层穿 ``curCls``（新墨以新色显）——槽外父级若瞬时改色，只影响当前态元素，
 * 染不到正在退场的旧句。
 *
 * Parameters
 * ----------
 * pair : InkPair
 *     当前对。
 * text : string
 *     目标文案。
 * cls : string
 *     目标文案的墨（颜色/流光类名）。
 * first : boolean
 *     是否首帧（首帧只就位、不退场）。
 *
 * Returns
 * -------
 * InkPair
 *     更新后的对；文案未变时墨就地换（不重写），全同则返回原引用。
 */
export function nextInkPair(pair: InkPair, text: string, cls: string, first: boolean): InkPair {
  if (first) return { cur: text, curCls: cls, prev: null, prevCls: null, gen: 0 }
  if (pair.cur === text) {
    // 文案未变、墨变（罕：同句换态类）：就地换墨即可，别触发重写。
    return pair.curCls === cls ? pair : { ...pair, curCls: cls }
  }
  return { cur: text, curCls: cls, prev: pair.cur, prevCls: pair.curCls, gen: pair.gen + 1 }
}

interface InkRewriteProps {
  /** 当前应显示的文案；变化时触发重写。 */
  text: string
  /** label=按钮浅淡；prose=状态句带轻 blur。 */
  tone?: InkTone
  className?: string
  /**
   * 叠在「可见字层」（进/出场层）上的类名——颜色/流光皆属「墨」，随句快照：
   * 进层穿新墨、出层穿旧墨，旧句退场途中不被新态染色。
   *
   * 必须挂在真正有文字节点的层上：像 ``exec-flow`` 这类 ``background-clip: text``
   * 不能套在槽根——子节点只继承透明字色、吃不到渐变，字会「消失」。
   */
  textClassName?: string
  /**
   * 流体宽：前后句长短悬殊时（如长告警句↔「正在执行」）用。
   *
   * 默认（等长标签，如 启动↔暂停）走网格双层同格叠淡、槽宽即 cur 宽——长短悬殊时会被
   * 退场层撑成 max(prev, cur)，短句左对齐、右侧留一大片空。开启后两可见层改绝对定位、
   * 不再撑宽（无空隙），退场长句由 overflow 从右裁掉；并对槽宽做 CSS 过渡（旧宽→新宽），
   * 下游兄弟随 reflow 连续挪，读作「纸收窄、旧墨随之退」。
   *
   * 自激防线（曾两度翻车，此番的构造前提）：① 量 ``sizer`` 的 **inline-block 固有宽**
   * （恒为终点，不随过渡中的 slot inline width 变）→ 动画中途的轮询 re-render 读到的仍是
   * 终点、dx≈0 跳过，不自触发；② 消费方**不得**再挂 transform-FLIP 采样本槽宽或下游
   * ``offsetLeft``——两套范式同管一物必抢。二者缺一即抖。
   */
  fluid?: boolean
}

/**
 * 同槽交叉淡替换文字。
 *
 * Parameters
 * ----------
 * text : string
 *     目标文案。
 * tone : InkTone
 *     深浅笔法。
 * className : string
 *     叠在槽根上的类名。
 * textClassName : string
 *     叠在可见字层上的类名（流光等 clip-text 效果用此位）。
 * fluid : bool
 *     前后句长短悬殊时改绝对层（无空隙）并对槽宽做 CSS 过渡；见 ``InkRewriteProps.fluid``。
 */
export function InkRewrite({
  text,
  tone = 'label',
  className = '',
  textClassName = '',
  fluid = false,
}: InkRewriteProps) {
  const first = useRef(true)
  const cls = textClassName.trim()
  const [pair, setPair] = useState<InkPair>({
    cur: text,
    curCls: cls,
    prev: null,
    prevCls: null,
    gen: 0,
  })

  // 用 layout effect（而非 useEffect）：换字与触发它的父级布局变化（进执行那刻的圆点/相位
  // 挂载、主句宽变）收进同一次提交前，箭头 FLIP 只测一次终态、只滑一次；亦免新字满不透明闪一帧。
  useLayoutEffect(() => {
    if (first.current) {
      first.current = false
      setPair((p) => ({ ...p, cur: text, curCls: cls }))
      return
    }
    setPair((p) => nextInkPair(p, text, cls, false))
  }, [text, cls])

  useEffect(() => {
    if (pair.prev == null) return
    const id = window.setTimeout(() => {
      setPair((p) => (p.prev != null ? { ...p, prev: null, prevCls: null } : p))
    }, inkRewriteMs(tone))
    return () => window.clearTimeout(id)
  }, [pair.gen, pair.prev, tone])

  // 槽宽过渡（仅 fluid）：cur 变更后把槽从旧宽平滑收/展到新宽，下游兄弟随 reflow 连续挪，
  // 主句「纸收窄、旧墨随之被 overflow 从右裁掉」。安全前提（此番才敢重加）：
  //   1) 量 `sizer`（**inline-block 固有宽**，恒为终点、不随 slot 的 inline width 变）——动画中途
  //      的轮询 re-render 读到的仍是终点，dx≈0 跳过，不自触发；
  //   2) 消费方**不再挂 transform-FLIP** 采样本槽宽或下游 offsetLeft（箭头已改纯 reflow 跟随），
  //      故无第二套范式来抢——上一版两处自激由此从构造上消除。
  const slotRef = useRef<HTMLSpanElement>(null)
  const sizerRef = useRef<HTMLSpanElement>(null)
  const lastW = useRef<number | null>(null)
  const wRaf = useRef<number | undefined>(undefined)
  const wClear = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useLayoutEffect(() => {
    if (!fluid) return
    const slot = slotRef.current
    const sizer = sizerRef.current
    if (!slot || !sizer) return
    const w = sizer.offsetWidth
    const prev = lastW.current
    lastW.current = w
    if (prev == null || Math.abs(prev - w) < 0.5) return
    const reduce =
      typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (reduce) return
    if (wRaf.current) cancelAnimationFrame(wRaf.current)
    if (wClear.current) clearTimeout(wClear.current)
    // 先无过渡就位到旧宽，强制重排落定起点，下一帧过渡到新宽；到时清 inline 复原为 auto(=cur)。
    slot.style.transition = 'none'
    slot.style.width = `${prev}px`
    void slot.offsetWidth
    wRaf.current = requestAnimationFrame(() => {
      slot.style.transition = `width ${FLUID_W_MS}ms ${FLUID_W_EASE}`
      slot.style.width = `${w}px`
      wClear.current = setTimeout(() => {
        slot.style.transition = ''
        slot.style.width = ''
      }, FLUID_W_MS + 60)
    })
  })
  useLayoutEffect(
    () => () => {
      if (wRaf.current) cancelAnimationFrame(wRaf.current)
      if (wClear.current) clearTimeout(wClear.current)
    },
    [],
  )

  const animate = pair.gen > 0
  const inCls = animate ? (tone === 'prose' ? 'ink-rewrite-in-prose' : 'ink-rewrite-in') : ''
  const outCls = tone === 'prose' ? 'ink-rewrite-out-prose' : 'ink-rewrite-out'

  if (fluid) {
    // 两可见层绝对定位（不撑宽）→ 占位层（inline-block 固有宽，不被槽反向撑动）单独定槽宽，
    // 不占 max(prev,cur)、无空隙。overflow-hidden 把退场长句从右裁掉，不外溢压到相位/箭头。
    // 槽宽的旧→新由上面的 layout effect 做 CSS 过渡（下游随 reflow 连续挪）。父级 items-center
    // 对齐，overflow 改基线无碍。
    return (
      <span
        ref={slotRef}
        className={`ink-rewrite-slot relative inline-block max-w-full overflow-hidden ${className}`.trim()}
      >
        <span ref={sizerRef} className="invisible inline-block whitespace-nowrap" aria-hidden>
          {pair.cur}
        </span>
        {pair.prev != null && (
          <span
            className={`absolute left-0 top-0 whitespace-nowrap ${outCls} ${pair.prevCls ?? ''}`.trim()}
            aria-hidden
          >
            {pair.prev}
          </span>
        )}
        <span
          key={pair.gen}
          className={`absolute left-0 top-0 whitespace-nowrap ${inCls} ${pair.curCls}`.trim()}
        >
          {pair.cur}
        </span>
      </span>
    )
  }

  return (
    <span className={`ink-rewrite-slot inline-grid max-w-full ${className}`.trim()}>
      {/* 占位定宽高，避免进出双层把行高撑抖 */}
      <span className="invisible col-start-1 row-start-1 truncate whitespace-nowrap" aria-hidden>
        {pair.cur}
      </span>
      {pair.prev != null && (
        <span
          className={`col-start-1 row-start-1 truncate whitespace-nowrap ${outCls} ${pair.prevCls ?? ''}`.trim()}
          aria-hidden
        >
          {pair.prev}
        </span>
      )}
      <span
        key={pair.gen}
        className={`col-start-1 row-start-1 truncate whitespace-nowrap ${inCls} ${pair.curCls}`.trim()}
      >
        {pair.cur}
      </span>
    </span>
  )
}
