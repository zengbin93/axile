import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type KeyboardEvent } from 'react'
import { Check, FileUp, LoaderCircle, RefreshCw, Save, Undo2 } from 'lucide-react'

import { ConfirmModal, type ConfirmSpec } from '@/components/ui/ConfirmModal'
import { PythonFunctionEditor } from '@/components/ui/PythonFunctionEditor'
import { Segmented } from '@/components/ui/Segmented'
import { Select } from '@/components/ui/Select'
import {
  getCalendarDiagnostics,
  getCalendarOverrides,
  getCalendarStatus,
  importCalendarCsv,
  previewCalendarCsv,
  refreshCalendar,
  restoreCalendarOverrides,
  saveCalendarFunction,
  saveCalendarOverrides,
  validateCalendarFunction,
  type CalendarDiagnostic,
  type CalendarFunctionResult,
  type CalendarOverride,
  type CalendarPreview,
  type CalendarRefreshKind,
  type CalendarStatus,
} from '@/lib/api/tradingCalendar'
import { getCalendarRequirements } from '@/lib/api/system'
import { useToastStore } from '@/stores/ui'

const TEMPLATE = `from datetime import date, timedelta

def get_trading_calendar(calendar_id: str, start: date, end: date) -> list[dict]:
    rows = []
    current = start
    while current <= end:
        rows.append({
            "calendar_id": calendar_id,
            "cal_date": current.isoformat(),
            "is_open": current.weekday() < 5,
        })
        current += timedelta(days=1)
    return rows
`

const pad = (value: number) => String(value).padStart(2, '0')
const dateIso = (value: Date) => `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`
const addDays = (value: string, days: number) => {
  const [year, month, day] = value.split('-').map(Number)
  return new Date(Date.UTC(year, month - 1, day + days)).toISOString().slice(0, 10)
}
const stateText = (value: boolean | null) => value == null ? '缺失' : value ? '开市' : '休市'

export function TradingCalendarPage() {
  const toast = useToastStore((state) => state.toast)
  const today = useMemo(() => dateIso(new Date()), [])
  const [calendarId, setCalendarId] = useState('china')
  const [calendarOptions, setCalendarOptions] = useState<Array<{ value: string; label: string }>>([])
  const [status, setStatus] = useState<CalendarStatus | null>(null)
  const [mode, setMode] = useState<CalendarRefreshKind>('csv')
  const [code, setCode] = useState(TEMPLATE)
  const [functionResult, setFunctionResult] = useState<CalendarFunctionResult | null>(null)
  const [running, setRunning] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<CalendarPreview | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const [start, setStart] = useState(today)
  const [end, setEnd] = useState(addDays(today, 14))
  const [rows, setRows] = useState<CalendarDiagnostic[]>([])
  const [edits, setEdits] = useState<Record<string, boolean>>({})
  const [overrides, setOverrides] = useState<CalendarOverride[]>([])
  const [confirm, setConfirm] = useState<ConfirmSpec | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const previewRequest = useRef(0)

  const refresh = useCallback(async () => {
    const [nextStatus, nextOverrides] = await Promise.all([
      getCalendarStatus(calendarId),
      getCalendarOverrides(calendarId),
    ])
    setStatus(nextStatus)
    setOverrides(nextOverrides)
    setMode(nextStatus.refreshKind ?? 'csv')
    setCode(nextStatus.functionCode || TEMPLATE)
  }, [calendarId])

  useEffect(() => {
    void getCalendarRequirements().then((requirements) => {
      const options = requirements.map((item) => ({
        value: item.calendar_id,
        label: `${item.label} · ${item.channel_labels.join('、')}`,
      }))
      setCalendarOptions(options.length > 0 ? options : [{ value: 'china', label: '中国交易日历' }])
      setCalendarId((current) => options.some((item) => item.value === current) ? current : options[0]?.value ?? current)
    })
  }, [])
  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => {
    setFunctionResult(null)
    setSaveError(null)
  }, [code])

  const loadRange = useCallback(async () => {
    try {
      setRows(await getCalendarDiagnostics(calendarId, start, end))
      setEdits({})
    } catch (error) {
      toast(`加载失败：${error instanceof Error ? error.message : String(error)}`)
    }
  }, [calendarId, end, start, toast])

  const afterReplacement = async () => {
    setSelectedFile(null)
    setPreview(null)
    setUploadError(null)
    await refresh()
    if (rows.length > 0) await loadRange()
  }

  const replaceWithConfirmation = (label: string, action: () => Promise<void>) => {
    if (!status?.overrideCount) {
      void action()
      return
    }
    setConfirm({
      title: `用${label}替换当前日历？`,
      body: `替换成功后将清除当前 ${status.overrideCount} 条人工调整。`,
      okText: '替换并清除调整',
      onConfirm: () => void action(),
    })
  }

  const chooseFile = async (file: File) => {
    const request = ++previewRequest.current
    setSelectedFile(file)
    setPreview(null)
    setUploadError(null)
    setUploading(true)
    try {
      const result = await previewCalendarCsv(calendarId, file)
      if (request === previewRequest.current) setPreview(result)
    } catch (error) {
      if (request !== previewRequest.current) return
      const message = error instanceof Error ? error.message : String(error)
      setUploadError(message)
      toast(`CSV 预检失败：${message}`)
    } finally {
      if (request === previewRequest.current) setUploading(false)
    }
  }

  const importCsv = () => {
    if (!selectedFile) return
    replaceWithConfirmation('CSV', async () => {
      try {
        await importCalendarCsv(calendarId, selectedFile)
        toast('CSV 日历已替换')
        await afterReplacement()
      } catch (error) {
        toast(`导入失败：${error instanceof Error ? error.message : String(error)}`)
      }
    })
  }

  const runFunction = async () => {
    setRunning(true)
    try {
      setFunctionResult(await validateCalendarFunction(calendarId, code, today, addDays(today, 6)))
    } catch (error) {
      toast(`试跑失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setRunning(false)
    }
  }

  const canSaveFunction = Boolean(code.trim() && functionResult?.valid && !running && !saving)

  const saveFunction = () => {
    if (!canSaveFunction) return
    replaceWithConfirmation('自定义函数', async () => {
      setSaving(true)
      setSaveError(null)
      try {
        await saveCalendarFunction(calendarId, code)
        toast('自定义函数日历已刷新并保存')
        await afterReplacement()
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        setSaveError(message)
        toast(`保存失败：${message}`)
      } finally {
        setSaving(false)
      }
    })
  }

  const saveEdits = async () => {
    const entries = Object.entries(edits).map(([calDate, isOpen]) => ({ calDate, isOpen }))
    try {
      await saveCalendarOverrides(calendarId, entries)
      toast(`已保存 ${entries.length} 条人工调整`)
      await Promise.all([loadRange(), refresh()])
    } catch (error) {
      toast(`保存失败：${error instanceof Error ? error.message : String(error)}`)
    }
  }

  const restoreDates = async (dates: string[]) => {
    try {
      await restoreCalendarOverrides(calendarId, dates)
      toast(`已恢复 ${dates.length} 个日期`)
      await Promise.all([loadRange(), refresh()])
    } catch (error) {
      toast(`恢复失败：${error instanceof Error ? error.message : String(error)}`)
    }
  }

  const unavailableDetail = status?.unavailableReason === 'read_failed'
    ? '日历读取失败，自动排程继续执行。'
    : status?.unavailableReason === 'uncovered'
      ? '基础数据未覆盖今天，自动排程继续执行。'
      : '尚未配置日历，自动排程继续执行。'

  return (
    <div className="min-h-full bg-bg">
      <main className="mx-auto max-w-[1080px] px-5 py-7 sm:px-10 sm:py-9">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="text-[12px] font-[620] text-ink-3">设置</div>
            <h1 className="mt-1 text-[24px] font-[680]">交易日历</h1>
          </div>
          <Select
            ariaLabel="交易日历"
            className="min-w-[220px]"
            value={calendarId}
            onChange={setCalendarId}
            options={calendarOptions}
          />
        </div>

        <div className="mt-5 border-b border-line pb-5" role="status">
          <div className="flex items-center gap-2 text-[14px] font-[620]">
            <span aria-hidden="true" className={`h-2 w-2 rounded-full ${status?.availability === 'available' ? 'bg-accent' : 'bg-warn'}`} />
            {status?.availability === 'available' ? '交易日历可用' : '交易日历不可用'}
          </div>
          <div className="mt-1 pl-4 text-[12.5px] text-ink-2">
            {status?.availability === 'available' ? '今天的开闭市状态可以确定。' : unavailableDetail}
          </div>
        </div>

        <section className="mt-6 grid grid-cols-2 gap-px overflow-hidden rounded-[8px] border border-line bg-line text-[13px] sm:grid-cols-4">
          {[
            ['刷新方式', status?.refreshKind === 'python' ? '自定义函数' : status?.refreshKind === 'csv' ? 'CSV' : '未配置'],
            ['有效覆盖', status?.coverageStart ? `${status.coverageStart} 至 ${status.coverageEnd}` : '暂无'],
            ['同步状态', status?.lastSyncAt ? status.lastSyncAt.replace('T', ' ') : '尚未同步'],
            ['人工调整', `${status?.overrideCount ?? 0} 条`],
          ].map(([label, value]) => (
            <div key={label} className="bg-surface px-4 py-3">
              <div className="text-ink-3">{label}</div><div className="mt-1 font-[560] text-ink-1">{value}</div>
            </div>
          ))}
        </section>
        <section className="mt-8">
          <div className="flex items-center justify-between gap-4">
            <h2 className="text-[15px] font-[620]">基础日历</h2>
            <Segmented
              size="sm"
              value={mode}
              options={[{ value: 'csv', label: 'CSV' }, { value: 'python', label: '自定义函数' }]}
              onChange={(value) => setMode(value as CalendarRefreshKind)}
            />
          </div>
          <p className="mt-1 text-[12.5px] text-ink-2">成功替换基础日历时，人工调整会一并清除。</p>

          {(['csv', 'python'] as const).map((kind) => {
            const active = mode === kind
            return (
              <div key={kind} inert={!active} className={`grid transition-[grid-template-rows] duration-200 motion-reduce:transition-none ${active ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}>
                <div className="min-h-0 overflow-hidden">
                  <div className="pt-4">
                    {kind === 'csv' ? (
                      <>
                        <input ref={fileInput} type="file" accept=".csv,text/csv" className="sr-only" onChange={(event) => { const file = event.target.files?.[0]; if (file) void chooseFile(file); event.currentTarget.value = '' }} />
                        <div
                          role="button"
                          tabIndex={uploading ? -1 : 0}
                          className={`flex min-h-[160px] cursor-pointer select-none flex-col items-center justify-center rounded-[8px] border border-dashed px-6 text-center outline-none ${dragging ? 'border-accent bg-accent-soft' : uploadError ? 'border-warn bg-warn-soft' : preview ? 'border-accent bg-accent-soft' : 'border-border-strong bg-bg-subtle hover:border-accent'}`}
                          onClick={() => !uploading && fileInput.current?.click()}
                          onKeyDown={(event: KeyboardEvent<HTMLDivElement>) => { if (!uploading && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); fileInput.current?.click() } }}
                          onDragEnter={(event) => { event.preventDefault(); setDragging(true) }}
                          onDragOver={(event) => event.preventDefault()}
                          onDragLeave={() => setDragging(false)}
                          onDrop={(event: DragEvent<HTMLDivElement>) => { event.preventDefault(); setDragging(false); const file = event.dataTransfer.files[0]; if (file) void chooseFile(file) }}
                        >
                          {uploading ? <><LoaderCircle className="mb-3 animate-spin text-accent motion-reduce:animate-none" /><span>正在校验 {selectedFile?.name}</span></>
                            : uploadError ? <><span className="font-[620] text-warn">CSV 校验未通过</span><span className="mt-2 text-[12.5px] text-ink-2">{uploadError}</span></>
                              : preview ? <><Check className="mb-3 text-accent" /><span className="font-[620]">{selectedFile?.name}</span><span className="mt-2 text-[12.5px] text-accent">{preview.start} 至 {preview.end} · {preview.total} 天</span></>
                                : <><FileUp className="mb-3 text-accent" /><span className="font-[620]">选择交易日历 CSV</span></>}
                        </div>
                        {preview && (
                          <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-line pt-4 text-[13px]">
                            <span className="text-ink-2">新增 {preview.added} · 变化 {preview.changed} · 不变 {preview.unchanged}</span>
                            <span className="flex-1" />
                            <button className="rounded-[8px] bg-ink-1 px-4 py-2 text-surface" onClick={importCsv}>确认替换</button>
                          </div>
                        )}
                      </>
                    ) : (
                      <>
                        <PythonFunctionEditor code={code} onChange={setCode} running={running} result={functionResult} onRun={() => void runFunction()} disabled={saving} resultContent={functionResult?.valid ? <p className="mt-3 text-[13px] text-ink-2">返回 {functionResult.entries.length} 个连续自然日。</p> : null} />
                        <div className="mt-3 flex flex-wrap gap-2">
                          <button className="inline-flex items-center gap-1.5 rounded-[8px] bg-ink-1 px-4 py-2 text-[13px] text-surface disabled:cursor-default disabled:opacity-45" disabled={!canSaveFunction} onClick={saveFunction}>
                            {saving ? <LoaderCircle size={14} className="animate-spin motion-reduce:animate-none" /> : <Save size={14} />}
                            {saving ? '正在生成并保存…' : '保存并刷新'}
                          </button>
                          {status?.refreshKind === 'python' && (
                            <button className="inline-flex items-center gap-1.5 rounded-[8px] border border-line px-4 py-2 text-[13px] text-ink-2" onClick={async () => { const result = await refreshCalendar(calendarId); toast(result.message); await refresh() }}><RefreshCw size={14} /> 立即刷新</button>
                          )}
                        </div>
                        {saveError && <p className="mt-2 text-[12.5px] text-warn" role="alert">保存失败：{saveError}</p>}
                      </>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
        </section>

        <section className="mt-10 border-t border-line pt-6">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div><h2 className="text-[15px] font-[620]">人工调整</h2></div>
            <div className="flex flex-wrap items-center gap-2">
              <input type="date" value={start} onChange={(event) => setStart(event.target.value)} className="rounded-[8px] border border-line bg-surface px-3 py-2 text-[13px]" />
              <span className="text-ink-3">至</span>
              <input type="date" value={end} onChange={(event) => setEnd(event.target.value)} className="rounded-[8px] border border-line bg-surface px-3 py-2 text-[13px]" />
              <button className="rounded-[8px] border border-line px-3 py-2 text-[13px]" onClick={() => void loadRange()}>加载</button>
            </div>
          </div>
          {rows.length > 0 && (
            <div className="mt-4 overflow-x-auto border-y border-line">
              <div className="grid min-w-[650px] grid-cols-[130px_1fr_1fr_auto] gap-4 border-b border-line px-3 py-2 text-[12px] text-ink-3"><span>日期</span><span>基础状态</span><span>人工状态</span><span>最终状态</span></div>
              {rows.map((row) => {
                const value = edits[row.calDate] ?? row.overrideIsOpen ?? row.isOpen ?? true
                const original = row.overrideIsOpen ?? row.baseIsOpen
                const effective = edits[row.calDate] ?? row.isOpen
                return (
                  <div key={row.calDate} className="grid min-w-[650px] grid-cols-[130px_1fr_1fr_auto] items-center gap-4 border-b border-line px-3 py-2.5 text-[13px] last:border-0">
                    <span className="num">{row.calDate}</span>
                    <span className={row.baseIsOpen == null ? 'text-ink-3' : 'text-ink-2'}>{stateText(row.baseIsOpen)}</span>
                    <Segmented size="sm" value={value ? 'open' : 'closed'} options={[{ value: 'open', label: '开市' }, { value: 'closed', label: '休市' }]} onChange={(next) => setEdits((current) => { const changed = next === 'open'; const updated = { ...current }; if (changed === original) delete updated[row.calDate]; else updated[row.calDate] = changed; return updated })} />
                    <span className="text-ink-2">{effective == null ? '日历不可用 · 执行' : effective ? '开市 · 执行' : '休市 · 跳过'}</span>
                  </div>
                )
              })}
              <div className="flex justify-end gap-2 border-t border-line px-3 py-3">
                <button className="inline-flex items-center gap-1.5 rounded-[8px] border border-line px-3 py-2 text-[13px] text-ink-2 disabled:opacity-45" disabled={!rows.some((row) => row.overrideIsOpen != null)} onClick={() => void restoreDates(rows.filter((row) => row.overrideIsOpen != null).map((row) => row.calDate))}><Undo2 size={14} /> 恢复区间</button>
                <button className="inline-flex items-center gap-1.5 rounded-[8px] bg-ink-1 px-4 py-2 text-[13px] text-surface disabled:opacity-45" disabled={Object.keys(edits).length === 0} onClick={() => void saveEdits()}><Save size={14} /> 保存 {Object.keys(edits).length} 项</button>
              </div>
            </div>
          )}
        </section>

        <section className="mt-10 border-t border-line pt-6">
          <h2 className="text-[15px] font-[620]">当前人工调整</h2>
          {overrides.length === 0 ? <p className="mt-4 text-[13px] text-ink-3">暂无人工调整</p> : (
            <div className="mt-4 divide-y divide-line border-y border-line">
              {overrides.map((entry) => (
                <div key={entry.calDate} className="grid grid-cols-[1fr_auto_auto] items-center gap-4 py-3 text-[13px]">
                  <span className="num">{entry.calDate}</span>
                  <span className="text-ink-2">{stateText(entry.baseIsOpen)} → {entry.isOpen ? '人工开市' : '人工休市'}</span>
                  <button className="inline-flex items-center gap-1.5 rounded-[8px] border border-line px-3 py-1.5 text-ink-2" onClick={() => void restoreDates([entry.calDate])}><Undo2 size={14} /> 恢复</button>
                </div>
              ))}
            </div>
          )}
        </section>
      </main>
      <ConfirmModal spec={confirm} onClose={() => setConfirm(null)} />
    </div>
  )
}
