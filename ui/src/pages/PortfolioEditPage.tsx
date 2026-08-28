import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useViewTransitionState } from 'react-router'
import { Clipboard, Play } from 'lucide-react'
import { Link } from '@/components/ui/nav'
import { Skeleton } from '@/components/ui/Skeleton'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { InkRewrite } from '@/components/ui/InkRewrite'
import { Select } from '@/components/ui/Select'
import { PythonFunctionEditor, type PythonEditorHandle } from '@/components/ui/PythonFunctionEditor'
import { PythonRunPanel } from '@/components/ui/PythonRunPanel'
import { TEXT } from '@/features/account/editUi'
import { channelLabel } from '@/features/dashboard/display'
import { WeightResult } from '@/features/portfolio/CustomFunctionEditor'
import { useCustomCalcValidation } from '@/features/portfolio/useCustomCalcValidation'
import { usePolling } from '@/lib/hooks/usePolling'
import { getPortfolio, updatePortfolio } from '@/lib/api/portfolios'
import { useDomainStore } from '@/stores/domain'
import { useToastStore } from '@/stores/ui'

/**
 * 组合工作台（VSCode 式布局）：左栏放一切控制——身份（标题 + 脏标记）、名称、
 * 跟随账户、试跑（上下文 + 按钮）、工具（粘贴/文档），底部是 dirty 才展开的保存区；
 * 右侧代码编辑器吃满整列高度，试跑结果走编辑器下方的可折叠 panel。
 * 保存成功后留在原地（改 → 试跑 → 保存 → 再改的循环不被打断）。
 * 窄视口（<md）退化为单列堆叠，编辑器保底 420px 高、页面恢复滚动。
 */
export function PortfolioEditPage() {
  const { id } = useParams()
  const portfolioId = Number(id)
  const toast = useToastStore((state) => state.toast)
  const portfolio = usePolling(useCallback((signal: AbortSignal) => getPortfolio(portfolioId, signal), [portfolioId]), {
    queryKey: `portfolio:${portfolioId}`,
    intervalMs: 0,
  })
  const accounts = useDomainStore((state) => state.accounts)
  const accountsError = useDomainStore((state) => state.accountsError)
  const refreshPortfolios = useDomainStore((state) => state.refreshPortfolios)
  const [ready, setReady] = useState(false)
  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const [original, setOriginal] = useState({ name: '', code: '' })
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<Error | null>(null)
  const editorRef = useRef<PythonEditorHandle>(null)
  const pf = portfolio.data

  useEffect(() => {
    if (!pf || ready) return
    setName(pf.name)
    setCode(pf.custom_calc_py_code)
    setOriginal({ name: pf.name, code: pf.custom_calc_py_code })
    setReady(true)
  }, [pf, ready])

  const followers = useMemo(
    () => (accounts ?? []).filter((account) => account.portfolio_id === portfolioId),
    [accounts, portfolioId],
  )

  // 试跑状态机（与初始化向导共用）：上下文选择、结果、stale、Ctrl+Enter 的回调目标。
  const calc = useCustomCalcValidation(code)

  // 组合名共享元素：详情 hero ↔ 本页左栏标题槽（同账户域「详情头 ↔ 标题槽」协议）。
  const tDetail = useViewTransitionState(`/portfolios/${portfolioId}`)

  const changes: string[] = []
  if (name.trim() !== original.name) changes.push('组合名称已改')
  if (code !== original.code) changes.push('目标计算函数已改')
  const dirty = changes.length > 0
  const blocked = !name.trim() || !code.trim() || accounts == null || Boolean(accountsError)

  // 保存后留在原地：toast 确认、基线更新为已保存态，迭代循环不跳出工作台。
  const publish = async () => {
    if (blocked || saving || !dirty) return
    setSaving(true)
    setSaveError(null)
    try {
      await updatePortfolio(portfolioId, { name: name.trim(), custom_calc_py_code: code })
      toast('组合已更新')
      setOriginal({ name: name.trim(), code })
      void refreshPortfolios()
    } catch (error) {
      setSaveError(error instanceof Error ? error : new Error(String(error)))
    } finally {
      setSaving(false)
    }
  }

  // Ctrl/Cmd+S 保存（工作台肌肉记忆）；编辑器内按键同样冒泡到 window。
  const publishRef = useRef(publish)
  useEffect(() => {
    publishRef.current = publish
  })
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === 's') {
        event.preventDefault()
        void publishRef.current()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const paste = async () => {
    try {
      const text = await navigator.clipboard.readText()
      if (text) {
        setCode(text)
        setSaveError(null)
      }
    } finally {
      editorRef.current?.focus()
    }
  }

  if (portfolio.loading || (!pf && !portfolio.error) || (pf && !ready)) {
    return (
      <section className="mx-auto flex h-full w-full max-w-[1440px] flex-col">
        <div className="flex min-h-0 flex-1 flex-col gap-6 md:flex-row md:gap-8">
          <div className="w-full md:w-[264px] md:flex-none">
            <Skeleton className="h-5 w-40" />
            <Skeleton className="mt-6 h-4 w-16" />
            <Skeleton className="mt-2 h-[38px] w-full" />
          </div>
          <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="mt-2 min-h-[300px] w-full flex-1" />
            <Skeleton className="mt-3 h-9 w-full" />
          </div>
        </div>
      </section>
    )
  }
  if (portfolio.error || !pf) {
    return (
      <section>
        <ErrorNotice title="组合加载失败" error={portfolio.error ?? new Error('组合不存在')} onRetry={portfolio.refresh} />
      </section>
    )
  }

  return (
    <section className="mx-auto flex h-full w-full max-w-[1440px] flex-col">
      <div className="flex min-h-0 flex-1 flex-col gap-6 md:flex-row md:gap-8">
        {/* 左栏（VSCode 侧栏位）：身份 → 元信息 → 控制，保存区钉在栏底。 */}
        <aside className="flex min-h-0 w-full flex-col md:w-[264px] md:flex-none">
          <h1 className="flex-none text-[16px] font-[640] leading-snug">
            组合 ·{' '}
            <span style={tDetail ? { viewTransitionName: `portfolio-name-${portfolioId}` } : undefined}>
              {original.name}
            </span>
            {dirty && (
              <span className="ml-1.5 align-middle text-accent" title="有未保存改动" aria-label="有未保存改动">
                ●
              </span>
            )}
          </h1>

          <div className="flex-none">
            <div className="mt-5">
              <div className="text-[12px] font-semibold tracking-wide text-ink-3">组合名称</div>
              <input
                className={`${TEXT} mt-2`}
                value={name}
                onChange={(event) => {
                  setName(event.target.value)
                  setSaveError(null)
                }}
              />
            </div>

            {followers.length > 0 && (
              <div className="mt-7">
                <div className="text-[12px] font-semibold tracking-wide text-ink-3">跟随账户 · {followers.length}</div>
                <ul className="mt-1.5 flex flex-col">
                  {followers.map((account) => (
                    <li key={account.account_id}>
                      <Link
                        to={`/accounts/${account.account_id}`}
                        className="group -mx-2 flex items-center gap-2 rounded-[8px] px-2 py-1.5 hover:bg-fill"
                      >
                        <span className="min-w-0 truncate text-[14px] text-ink-1">{account.name}</span>
                        <span className="flex-none rounded-chip bg-fill px-1.5 py-px text-[11.5px] text-ink-2">
                          {channelLabel(account.trade_channel, account.market)}
                        </span>
                        <span className="ml-auto flex-none text-ink-3 transition-colors group-hover:text-ink-1" aria-hidden>
                          ›
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="mt-7">
              <div className="text-[12px] font-semibold tracking-wide text-ink-3">试跑</div>
              <div className="mt-2 flex flex-col gap-2">
                <Select<number | null>
                  ariaLabel="试跑数据来源"
                  value={calc.accountId}
                  onChange={calc.setAccountId}
                  options={calc.contextOptions}
                  className="w-full justify-between px-3 py-2 text-[14px]"
                />
                {/* 来源说明：同一槽位原地换字（InkRewrite 是单行槽，文案必须压进一行）。
                    账户名不重复——Select 触发器上已有。选真实账户升琥珀：主动交易有真实委托。 */}
                <p
                  className={`border-l-2 pl-2 text-[12.5px] leading-5 ${
                    calc.accountId == null ? 'border-transparent' : 'border-warn'
                  }`}
                >
                  <InkRewrite
                    text={
                      calc.accountId == null
                        ? '假数据 · 不连真实渠道 · 只验证逻辑'
                        : '真实数据 · 主动交易将产生真实委托'
                    }
                    tone="label"
                    textClassName={calc.accountId == null ? 'text-ink-3' : 'text-warn'}
                  />
                </p>
                <button
                  type="button"
                  className="inline-flex w-full cursor-pointer items-center justify-center gap-1.5 rounded-[8px] border-0 bg-ink-1 px-4 py-2 text-[14.5px] font-[550] text-surface disabled:cursor-default disabled:opacity-45"
                  onClick={() => void calc.run()}
                  disabled={!calc.canRun}
                >
                  <Play size={14} /> {calc.validating ? '试跑中…' : '试跑'}
                </button>
              </div>
            </div>

            <div className="mt-7">
              <div className="text-[12px] font-semibold tracking-wide text-ink-3">工具</div>
              <div className="mt-2 flex items-center gap-4">
                <button
                  type="button"
                  className="inline-flex cursor-pointer items-center gap-1.5 text-[14px] text-accent"
                  onClick={() => void paste()}
                >
                  <Clipboard size={14} /> 粘贴
                </button>
                <a className="text-[14px] text-accent" href="/docs/custom-calc" target="_blank" rel="noopener">
                  开发文档 ↗
                </a>
              </div>
            </div>
          </div>

          {/* 试跑结果 split pane：吃满左栏余高；动作（试跑）与反馈（结果）同栏相邻。 */}
          <div className="mt-7 flex-none text-[12px] font-semibold tracking-wide text-ink-3">试跑结果</div>
          <PythonRunPanel
            className="mt-2 max-md:h-[240px] md:min-h-[140px] md:flex-1"
            running={calc.validating}
            result={calc.editorResult}
            stale={calc.stale}
            resultContent={
              calc.result?.valid && calc.result.target ? <WeightResult target={calc.result.target} /> : null
            }
          />

          {/* 保存区：clean 完全静默；dirty 时 grid-fr 就地展开，风险后果句贴着保存动作。 */}
          <div
            inert={!dirty}
            className={`flex-none grid transition-[grid-template-rows] duration-200 motion-reduce:transition-none ${
              dirty ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'
            }`}
          >
            <div className="min-h-0 overflow-hidden">
              <div className="border-t border-line pt-4">
                <div className="text-[12px] font-semibold tracking-wide text-ink-3">
                  待保存 · {changes.length} 项{blocked && <span className="text-warn"> · 有错误</span>}
                </div>
                <div className="mt-1 text-[13.5px] leading-5 text-ink-1">{changes.join(' · ')}</div>
                {accountsError ? (
                  <p className="mt-2 border-l-2 border-warn pl-2.5 text-[13px] leading-5 text-warn">
                    绑定关系暂不可用，恢复前无法保存
                  </p>
                ) : (
                  followers.length > 0 && (
                    <p className="mt-2 border-l-2 border-warn pl-2.5 text-[13px] leading-5 text-ink-1">
                      保存后 <b>{followers.length}</b> 个账户会在下次调仓时执行新函数
                    </p>
                  )
                )}
                <div className="mt-3 flex items-center gap-3">
                  <button
                    type="button"
                    className="inline-flex flex-1 cursor-pointer items-center justify-center rounded-[9px] border-0 bg-ink-1 px-5 py-2 text-[14.5px] font-semibold text-surface disabled:cursor-default disabled:opacity-45"
                    onClick={() => void publish()}
                    disabled={blocked || saving}
                  >
                    {saving ? '保存中…' : '保存'}
                  </button>
                  <Link to={`/portfolios/${portfolioId}`} className="flex-none text-[14px] text-ink-2 hover:text-ink-1">
                    取消
                  </Link>
                </div>
                <ErrorNotice title="保存失败" error={saveError} variant="mutation" onRetry={() => void publish()} />
              </div>
            </div>
          </div>
        </aside>

        {/* 右列（编辑器位）：纯代码区吃满整列高度，无任何工具条/标签占位。 */}
        <div className="flex min-h-[420px] min-w-0 flex-1 flex-col md:min-h-0">
          <PythonFunctionEditor
            ref={editorRef}
            layout="workbench"
            fill
            code={code}
            onChange={(value) => {
              setCode(value)
              setSaveError(null)
            }}
            running={calc.validating}
            stale={calc.stale}
            result={calc.editorResult}
            onRun={() => void calc.run()}
          />
        </div>
      </div>
    </section>
  )
}
