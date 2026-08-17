import { useEffect, useRef, useState } from 'react'
import { python } from '@codemirror/lang-python'
import { lintGutter, setDiagnostics, type Diagnostic } from '@codemirror/lint'
import { oneDark } from '@codemirror/theme-one-dark'
import { EditorView } from '@codemirror/view'
import CodeMirror, { type ReactCodeMirrorRef } from '@uiw/react-codemirror'
import { ConfirmModal, type ConfirmSpec } from '@/components/ui/ConfirmModal'
import { Segmented } from '@/components/ui/Segmented'
import { Select } from '@/components/ui/Select'
import { ImportModal } from '@/features/portfolio/ImportModal'
import type { DraftStrategy } from '@/features/portfolio/diff'
import { FOLD, equalize, normalize, summary } from '@/features/portfolio/strategies'
import { previewWeights, validateCustomCalc } from '@/lib/api/portfolios'
import { barColor } from '@/lib/derive'
import { useDomainStore } from '@/stores/domain'
import type { LatestWeights, TradeChannel, ValidateCustomCalcResult } from '@/types/api'

/** CodeMirror 外观：透明底（交给外层 bg-code-bg）、去边框描边、等宽字体。 */
const cmEditorTheme = EditorView.theme({
  '&': { backgroundColor: 'transparent', fontSize: '13px' },
  '&.cm-focused': { outline: 'none' },
  '.cm-gutters': { backgroundColor: 'transparent', border: 'none' },
  '.cm-content': { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace' },
})

/** 当前 tab 的「试跑」结论，供父层「下一步」软拦截读取。 */
export interface VerifiedState {
  /** 是否试跑通过（成功产出合法目标权重）。 */
  ok: boolean
}

interface StrategyComposerProps {
  mode: 'compose' | 'custom'
  onModeChange: (m: 'compose' | 'custom') => void
  strategies: DraftStrategy[]
  onStrategiesChange: (s: DraftStrategy[]) => void
  customCode: string
  onCustomCodeChange: (c: string) => void
  /** 策略组合试跑所用渠道（由市场决定）；缺省则不显示策略组合的试跑。 */
  tradeChannel?: TradeChannel
  /** 当前 tab 试跑结论的回调；改动配置会回传 null，供父层「下一步」软拦截读取。 */
  onVerifiedChange?: (v: VerifiedState | null) => void
  /** 是否允许「策略组合」档；false（未配置数据源）时隐藏分段、仅留自定义逻辑。默认 true。 */
  allowCompose?: boolean
}

/** 组合的策略配置编辑器：策略组合（导入/加行/等权/归一）或自定义代码。复用于建号向导与发版页。 */
export function StrategyComposer({
  mode,
  onModeChange,
  strategies,
  onStrategiesChange,
  customCode,
  onCustomCodeChange,
  tradeChannel,
  onVerifiedChange,
  allowCompose = true,
}: StrategyComposerProps) {
  const [filter, setFilter] = useState('')
  const [importOpen, setImportOpen] = useState(false)
  const [confirm, setConfirm] = useState<ConfirmSpec | null>(null)
  /** 各行名字输入的 ref，供「追加即聚焦」定位。 */
  const nameRefs = useRef<Map<number, HTMLInputElement>>(new Map())
  /** 待聚焦的行下标；追加新行后由 effect 消费。 */
  const [focusIdx, setFocusIdx] = useState<number | null>(null)

  // ——— 试跑运行态与结果 ———
  /** 本次试跑运行中（自定义或策略组合）。 */
  const [validating, setValidating] = useState(false)
  /** 自定义逻辑试跑的完整返回（成功权重或错误 + traceback），编辑代码即清空。 */
  const [validateResult, setValidateResult] = useState<ValidateCustomCalcResult | null>(null)
  /** 试跑数据源：null=空跑（样例上下文），否则为选中的真实账户 id。 */
  const [validateAccountId, setValidateAccountId] = useState<number | null>(null)
  /** 上次试跑实际所用的数据源，用于状态条显示「拿什么跑的」（空跑 / 某账户）。 */
  const [validatedSourceId, setValidatedSourceId] = useState<number | null>(null)
  /** 策略组合试跑结果：成功携带解析出的品种目标，失败携带错误消息。 */
  const [previewResult, setPreviewResult] = useState<{ ok: boolean; target?: LatestWeights; error?: string } | null>(
    null,
  )
  const accounts = useDomainStore((s) => s.accounts) ?? []
  /** CodeMirror 实例引用，供聚焦与下发 lint 诊断。 */
  const cmRef = useRef<ReactCodeMirrorRef>(null)

  // 代码变动即让自定义试跑结果失效（「编辑即失效」）。
  useEffect(() => {
    setValidateResult(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customCode])

  // 策略改动即让策略组合试跑结果失效。
  useEffect(() => {
    setPreviewResult(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [strategies])

  // 统一把「当前 tab 的试跑结论」上报父层，供「下一步」软拦截；配置未跑/改动即为 null。
  useEffect(() => {
    const ran = mode === 'custom' ? validateResult != null : previewResult != null
    const ok = mode === 'custom' ? !!validateResult?.valid : !!previewResult?.ok
    onVerifiedChange?.(ran ? { ok } : null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, validateResult, previewResult])

  // 把后端定位到的出错行下发为 CodeMirror lint 诊断：出错行红色下划线 + 侧栏标记 + 悬停消息。
  useEffect(() => {
    const view = cmRef.current?.view
    if (!view) return
    const diags: Diagnostic[] = []
    if (validateResult && !validateResult.valid && validateResult.error_line != null) {
      const lineNo = Math.min(Math.max(validateResult.error_line, 1), view.state.doc.lines)
      const line = view.state.doc.line(lineNo)
      const message = [validateResult.error_type, validateResult.error_message].filter(Boolean).join(': ')
      diags.push({ from: line.from, to: line.to, severity: 'error', message: message || '试跑未通过' })
    }
    view.dispatch(setDiagnostics(view.state, diags))
  }, [validateResult])

  /** 自定义逻辑试跑：account_id 为空走空跑（样例上下文），否则借真实账户上下文。 */
  const runValidate = async (accountId: number | null) => {
    if (!customCode.trim() || validating) return
    setValidating(true)
    setValidatedSourceId(accountId)
    try {
      const res = await validateCustomCalc({ custom_calc_py_code: customCode, account_id: accountId })
      setValidateResult(res)
    } catch (e) {
      // 账户不存在等调用错误会抛 ApiError；作为一次失败结果就地展示（无代码行定位）。
      setValidateResult({
        valid: false,
        target: null,
        error: e instanceof Error ? e.message : String(e),
        traceback: null,
        error_line: null,
        error_offset: null,
        error_type: null,
        error_message: e instanceof Error ? e.message : String(e),
      })
    } finally {
      setValidating(false)
    }
  }

  /** 策略组合试跑：把当前策略配置按渠道合成一次目标（不落库），看解析出的品种目标。 */
  const runPreview = async () => {
    const rows = strategies.filter((r) => r.name.trim()).map((r) => ({ name: r.name.trim(), weight: r.weight / 100 }))
    if (!rows.length || validating || !tradeChannel) return
    setValidating(true)
    try {
      const target = await previewWeights(rows, tradeChannel)
      setPreviewResult({ ok: true, target })
    } catch (e) {
      setPreviewResult({ ok: false, error: e instanceof Error ? e.message : String(e) })
    } finally {
      setValidating(false)
    }
  }

  const sum = summary(strategies)
  const near100 = Math.abs(sum.sum - 100) < 0.5
  const folded = strategies.length > FOLD

  // 追加行后聚焦其名字输入：待列表长度更新、新行渲染出来再 focus。
  useEffect(() => {
    if (focusIdx == null) return
    nameRefs.current.get(focusIdx)?.focus()
    setFocusIdx(null)
  }, [focusIdx, strategies.length])

  const setRow = (i: number, patch: Partial<DraftStrategy>) =>
    onStrategiesChange(strategies.map((r, k) => (k === i ? { ...r, ...patch } : r)))
  const rmRow = (i: number) => onStrategiesChange(strategies.filter((_, k) => k !== i))

  /** 唯一的「加一行」入口：追加空行、清过滤（保证新行可见）、聚焦其名字格。 */
  const addRow = () => {
    setFilter('')
    setFocusIdx(strategies.length)
    onStrategiesChange([...strategies, { name: '', weight: 0 }])
  }

  const clearAll = () =>
    setConfirm({
      title: '清空整个组合？',
      body: `将移除全部 ${strategies.length} 个策略，此步不可撤销（未发布前）。`,
      okText: '清空',
      danger: true,
      onConfirm: () => {
        onStrategiesChange([])
        setFilter('')
      },
    })

  /** 从剪贴板读取并填入粘贴区；失败（权限/非安全上下文）则聚焦文本框让用户手动 Ctrl+V。 */
  const pasteFromClipboard = async () => {
    try {
      const text = await navigator.clipboard.readText()
      if (text) onCustomCodeChange(text)
      else cmRef.current?.view?.focus()
    } catch {
      cmRef.current?.view?.focus()
    }
  }

  // 自定义逻辑验证状态：驱动状态条底色与编辑器左缘健康色。
  const hasCode = customCode.trim().length > 0
  const sourceName = (id: number | null) =>
    id == null ? '空跑' : (accounts.find((a) => a.account_id === id)?.name ?? `账户 #${id}`)
  const validateStatus = validating
    ? 'running'
    : validateResult == null
      ? 'unverified'
      : validateResult.valid
        ? 'pass'
        : 'fail'
  // 失败摘要：把「第几行 + 类型: 消息」拼进状态条（详情行内标在代码上，完整 traceback 收进「展开」）。
  const failBody = (() => {
    const loc = validateResult?.error_line != null ? `第 ${validateResult.error_line} 行` : ''
    const msg = [validateResult?.error_type, validateResult?.error_message].filter(Boolean).join(': ')
    const tail = [loc, msg].filter(Boolean).join(' · ')
    return tail ? `✗ 未通过 · ${tail}` : '✗ 未通过'
  })()
  const statusStyle = {
    running: { rail: 'border-accent', band: 'border-accent/30 bg-accent-soft', text: 'text-accent', body: '◌ 试跑中…' },
    unverified: { rail: 'border-warn', band: 'border-warn/30 bg-warn/10', text: 'text-warn', body: '● 未试跑 — 点「试跑」确认' },
    pass: { rail: 'border-ok', band: 'border-ok/30 bg-ok/10', text: 'text-ok', body: `✓ 已试跑 · ${sourceName(validatedSourceId)}` },
    fail: { rail: 'border-bad', band: 'border-bad/30 bg-bad/10', text: 'text-bad', body: failBody },
  }[validateStatus]

  return (
    <div>
      {allowCompose ? (
        <Segmented
          className="mb-4"
          value={mode}
          options={[
            { value: 'compose', label: '策略组合' },
            { value: 'custom', label: '自定义逻辑' },
          ]}
          onChange={onModeChange}
        />
      ) : (
        // 未配置数据源：策略权重无源可取，仅保留自定义逻辑（父层已强制 mode='custom'）。
        <div className="mb-4 rounded-[11px] border border-line bg-surface px-3.5 py-2.5 text-[13px] text-ink-2">
          未配置量化数据源，仅支持<b className="text-ink-1">自定义逻辑</b>组合。要用策略组合，请先在系统配置里补上数据源。
        </div>
      )}

      {/* key={mode}：每次切换重挂面板子树，触发 .panel-fade-in 入场淡入；滑块滑动仍由 Segmented 自理。 */}
      <div key={mode} className="panel-fade-in">
      {mode === 'compose' ? (
        <div className="max-w-[660px]">
          {strategies.length === 0 ? (
            <div className="rounded-[14px] border border-dashed border-line px-6 py-9 text-center">
              <div className="text-[15px] font-[550]">从你的清单开始</div>
              <div className="mt-1.5 text-[13px] text-ink-2">已有一份组合（可多达上百个策略）？把策略名粘进来，一次导入。</div>
              <div className="mt-4 flex items-center justify-center gap-4">
                <button
                  className="cursor-pointer rounded-[11px] border-0 bg-ink-1 px-[18px] py-2.5 text-[14px] font-[550] text-surface"
                  onClick={() => setImportOpen(true)}
                >
                  粘贴导入组合
                </button>
                <button className="cursor-pointer text-[14px] text-accent" onClick={() => addRow()}>
                  或逐个添加
                </button>
              </div>
            </div>
          ) : (
            <>
              {/* 摘要 + 操作 */}
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <span className="text-[13px] text-ink-2">
                  <b>{sum.count}</b> 个策略 · 合计{' '}
                  <b className={near100 ? 'text-ok' : 'text-warn'}>{sum.sum.toFixed(sum.sum % 1 ? 1 : 0)}%</b>
                  {sum.count > 1 && (
                    <span className="text-ink-3">
                      {' '}· 最大 {sum.max.toFixed(0)}% / 最小 {sum.min.toFixed(0)}%
                    </span>
                  )}
                </span>
                <div className="flex gap-3 text-[13px]">
                  <button className="cursor-pointer text-accent" onClick={() => setImportOpen(true)}>导入</button>
                  <button className="cursor-pointer text-accent" onClick={() => onStrategiesChange(equalize(strategies))}>等权</button>
                  <button className="cursor-pointer text-accent" onClick={() => onStrategiesChange(normalize(strategies))}>归一化</button>
                  <button className="cursor-pointer text-ink-3 hover:text-bad" onClick={clearAll}>清空</button>
                </div>
              </div>

              {folded && (
                <input
                  className="mb-2 w-full rounded-lg border border-ink-3/30 bg-surface px-3 py-2 text-[14px] outline-none focus:border-ink-2"
                  placeholder="在组合里查找策略…"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                />
              )}

              <div className="rounded-[14px] border border-line">
                {strategies.map((r, i) => {
                  if (filter && !r.name.toLowerCase().includes(filter.toLowerCase())) return null
                  return (
                    <div key={i} className="flex items-center gap-3 border-b border-line px-4 py-3 last:border-b-0">
                      <span className="h-2.5 w-2.5 flex-none rounded-full" style={{ background: barColor(i) }} />
                      <input
                        ref={(el) => {
                          if (el) nameRefs.current.set(i, el)
                          else nameRefs.current.delete(i)
                        }}
                        className="flex-1 rounded-lg border border-ink-3/30 bg-surface px-3 py-2 text-[14px] outline-none focus:border-ink-2"
                        placeholder="策略名（须与数据源一致，如 BTC_1H_P11）"
                        value={r.name}
                        onChange={(e) => setRow(i, { name: e.target.value })}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault()
                            addRow()
                          }
                        }}
                      />
                      <input
                        className="w-20 rounded-lg border border-ink-3/30 bg-surface px-2 py-2 text-right text-[14px] outline-none focus:border-ink-2"
                        type="number"
                        value={r.weight || ''}
                        onChange={(e) => setRow(i, { weight: Number(e.target.value) })}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault()
                            addRow()
                          }
                        }}
                      />
                      <span className="text-[13px] text-ink-3">%</span>
                      <button className="cursor-pointer text-ink-3 hover:text-bad" onClick={() => rmRow(i)}>✕</button>
                    </div>
                  )
                })}
              </div>

              {/* 追加一行：与空态「逐个添加」同一入口，回车亦可在行内接着加 */}
              <button className="mt-3 cursor-pointer text-[14px] font-semibold text-accent" onClick={addRow}>
                ＋ 添加策略
              </button>

              {/* 权重可视化：少则条+图例，多则折叠为一句 */}
              {folded ? (
                <p className="mt-4 text-[13px] text-ink-3">策略较多（{sum.count} 个），占比明细已折叠——合计见上方摘要。</p>
              ) : (
                sum.count > 0 &&
                sum.sum > 0 && (
                  <div className="mt-4">
                    <div className="flex h-2 overflow-hidden rounded-full bg-line">
                      {strategies.map((r, i) =>
                        r.weight > 0 ? (
                          <span
                            key={i}
                            className="block h-full [&+&]:border-l [&+&]:border-surface"
                            style={{ width: `${((r.weight / sum.sum) * 100).toFixed(2)}%`, background: barColor(i) }}
                          />
                        ) : null,
                      )}
                    </div>
                    <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
                      {strategies.map((r, i) =>
                        r.weight > 0 ? (
                          <span key={i} className="flex items-center gap-1.5 text-[12.5px] text-ink-2">
                            <span className="h-2 w-2 rounded-full" style={{ background: barColor(i) }} />
                            <span className="truncate max-w-[180px]">{r.name || '（未命名）'}</span>
                            <span className="num text-ink-3">{((r.weight / sum.sum) * 100).toFixed(0)}%</span>
                          </span>
                        ) : null,
                      )}
                    </div>
                  </div>
                )
              )}

              {/* 策略组合试跑：把当前策略配置按渠道合成一次目标（不落库），看解析出的品种目标 */}
              {tradeChannel && (
                <div className="mt-5 border-t border-line pt-4">
                  <div className="flex items-center gap-2.5">
                    <button
                      className="cursor-pointer rounded-[9px] border-0 bg-ink-1 px-[18px] py-1.5 text-[13.5px] font-[550] text-surface disabled:opacity-45"
                      onClick={runPreview}
                      disabled={validating || !strategies.some((r) => r.name.trim())}
                    >
                      试跑
                    </button>
                    <span className="text-[12.5px] text-ink-3">
                      {validating ? '试跑中…' : '看这些策略此刻解析出的品种目标'}
                    </span>
                  </div>
                  {previewResult != null && (
                    <div className={`mt-3 transition-opacity ${validating ? 'opacity-60' : ''}`}>
                      {previewResult.ok ? (
                        <WeightResult target={previewResult.target ?? {}} />
                      ) : (
                        <div className="rounded-[12px] border border-bad/40 bg-bad/5 px-4 py-3">
                          <span className="text-[13px] text-bad">✗ 试跑失败：{previewResult.error}</span>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      ) : (
        <div className="max-w-[820px]">
          {/* 工具行：填代码的帮手（有代码时露出「粘贴」覆盖，空态由中间大按钮承担） */}
          <div className="mb-2 flex items-center justify-end gap-4">
            {hasCode && (
              <button className="cursor-pointer text-[13px] text-accent" onClick={pasteFromClipboard}>
                📋 粘贴
              </button>
            )}
            <a className="text-[13px] text-accent" href="/docs/custom-calc" target="_blank" rel="noopener">
              开发文档 ↗
            </a>
          </div>

          {/* 编辑器 + 状态条：共享左缘 3px 健康色，一眼知道这段代码「绿了没有」 */}
          <div className={`overflow-hidden rounded-[14px] border-l-[3px] ${hasCode ? statusStyle.rail : 'border-line'}`}>
            <div className="relative bg-code-bg">
              <CodeMirror
                ref={cmRef}
                value={customCode}
                onChange={onCustomCodeChange}
                height="280px"
                theme="none"
                extensions={[oneDark, cmEditorTheme, python(), lintGutter(), EditorView.lineWrapping]}
                basicSetup={{
                  foldGutter: false,
                  highlightActiveLine: false,
                  highlightActiveLineGutter: false,
                  autocompletion: false,
                }}
              />
              {!hasCode && (
                /* 空态：中间大按钮从剪贴板粘贴；覆盖层不拦截点击，点空白处仍可聚焦输入 */
                <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-2">
                  <button
                    className="pointer-events-auto cursor-pointer rounded-[12px] border border-line bg-surface px-5 py-3 text-[14px] font-[550] text-ink-1 shadow-sm hover:border-ink-3"
                    onClick={pasteFromClipboard}
                  >
                    📋 从剪贴板粘贴代码
                  </button>
                  <span className="text-[12.5px] text-ink-3">或点此直接输入 / Ctrl+V</span>
                </div>
              )}
            </div>

            {hasCode && (
              /* 状态条：左=状态（含拿什么验的），右=数据源 + 单「验证」；随状态变底色 */
              <div className={`flex items-center gap-2.5 border-t px-3.5 py-2.5 ${statusStyle.band}`}>
                <span
                  className={`min-w-0 flex-1 truncate text-[13px] font-[520] ${statusStyle.text}`}
                  title={statusStyle.body}
                >
                  {statusStyle.body}
                </span>
                <span className="flex-none text-[12.5px] text-ink-3">用</span>
                <Select<number | null>
                  ariaLabel="试跑用账户"
                  value={validateAccountId}
                  onChange={setValidateAccountId}
                  options={[
                    { value: null, label: '空跑' },
                    ...accounts.map((a) => ({ value: a.account_id, label: a.name })),
                  ]}
                />
                <button
                  className="cursor-pointer rounded-[9px] border-0 bg-ink-1 px-[18px] py-1.5 text-[13.5px] font-[550] text-surface disabled:opacity-45"
                  onClick={() => runValidate(validateAccountId)}
                  disabled={validating}
                >
                  试跑
                </button>
              </div>
            )}
          </div>

          {/* 结果详情：通过→权重条形；未通过→错误已标在出错行 + 状态条，这里只收起完整 traceback。
              （验证中保留上次结果、仅降透明度，避免抖动） */}
          {validateResult != null && (validateResult.valid || validateResult.traceback) && (
            <div className={`mt-3 transition-opacity ${validating ? 'opacity-60' : ''}`} aria-busy={validating}>
              {validateResult.valid ? (
                <WeightResult target={validateResult.target ?? {}} />
              ) : (
                <details className="rounded-[12px] border border-line bg-code-bg px-4 py-3">
                  <summary className="cursor-pointer select-none text-[12.5px] text-ink-3">完整 traceback</summary>
                  <pre className="mt-2 max-h-[220px] overflow-auto whitespace-pre-wrap font-mono text-[12px] leading-relaxed text-bad">
                    {validateResult.traceback}
                  </pre>
                </details>
              )}
            </div>
          )}
        </div>
      )}
      </div>

      <ImportModal
        open={importOpen}
        existing={strategies}
        onClose={() => setImportOpen(false)}
        onApply={onStrategiesChange}
      />
      <ConfirmModal spec={confirm} onClose={() => setConfirm(null)} />
    </div>
  )
}

/** 验证成功的权重结果：条形 + 合计校验（合计≈1、负权重标红）。 */
function WeightResult({ target }: { target: Record<string, number> }) {
  const entries = Object.entries(target).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
  const total = entries.reduce((acc, [, w]) => acc + w, 0)
  const maxAbs = entries.reduce((acc, [, w]) => Math.max(acc, Math.abs(w)), 0) || 1
  const nearOne = Math.abs(total - 1) < 0.01

  if (entries.length === 0) {
    return (
      <div className="rounded-[12px] border border-line px-4 py-4 text-[13.5px] text-ink-2">
        ✓ 验证通过 · 返回空仓 <span className="text-ink-3">{'{}'}</span>
      </div>
    )
  }

  return (
    <div className="rounded-[12px] border border-line px-4 py-3.5">
      <div className="mb-2.5 flex items-center justify-between text-[13px]">
        <span className="font-[550] text-ok">✓ 返回权重</span>
        <span className="text-ink-3">
          合计 <span className={`num ${nearOne ? 'text-ink-2' : 'text-warn'}`}>{total.toFixed(2)}</span>
        </span>
      </div>
      <div className="flex flex-col gap-2">
        {entries.map(([sym, w], i) => (
          <div key={sym} className="flex items-center gap-3 text-[13px]">
            <span className="w-[110px] flex-none truncate font-[520]">{sym}</span>
            <span className="h-2 flex-1 overflow-hidden rounded-full bg-line">
              <span
                className="block h-full rounded-full"
                style={{ width: `${((Math.abs(w) / maxAbs) * 100).toFixed(1)}%`, background: w < 0 ? 'var(--color-bad)' : barColor(i) }}
              />
            </span>
            <span className={`num w-[52px] flex-none text-right ${w < 0 ? 'text-bad' : 'text-ink-2'}`}>{w.toFixed(2)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
