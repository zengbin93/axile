import { useEffect, useMemo, useRef, useState, type DragEvent, type KeyboardEvent } from 'react'
import { Check, ChevronDown, Code2, Download, FileUp, LoaderCircle, Trash2, TriangleAlert } from 'lucide-react'
import { InkRewrite } from '@/components/ui/InkRewrite'
import { OverflowText } from '@/components/ui/OverflowText'
import { PythonFunctionEditor } from '@/components/ui/PythonFunctionEditor'
import { ApiError } from '@/lib/api/client'
import {
  previewInitCalendarCsv,
  testInitCalendarFunction,
} from '@/lib/api/init'
import { getCalendarRequirements } from '@/lib/api/system'
import {
  CALENDAR_METHODS,
  calendarSetupSnapshot,
  initialCalendarState,
  type CalendarMethod,
  type CalendarSetupSnapshot,
  type CalendarState,
} from '@/features/init/calendarSetupState'

const errorText = (error: unknown) => error instanceof ApiError ? error.message : String(error)

export function CalendarSetupStep({ onChange }: { onChange: (value: CalendarSetupSnapshot) => void }) {
  const [calendars, setCalendars] = useState<CalendarState[]>([])
  const [activeId, setActiveId] = useState('')
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const snapshot = useMemo(() => calendarSetupSnapshot(calendars), [calendars])

  useEffect(() => {
    let mounted = true
    getCalendarRequirements()
      .then((requirements) => {
        if (!mounted) return
        setCalendars(requirements.map(initialCalendarState))
        setActiveId(requirements[0]?.calendar_id ?? '')
        setLoading(false)
      })
      .catch((error) => {
        if (!mounted) return
        setLoadError(errorText(error))
        setLoading(false)
      })
    return () => { mounted = false }
  }, [])

  useEffect(() => onChange(snapshot), [onChange, snapshot])

  const update = (calendarId: string, updater: (calendar: CalendarState) => CalendarState) => {
    setCalendars((items) => items.map((item) => item.calendar_id === calendarId ? updater(item) : item))
  }
  const active = calendars.find((item) => item.calendar_id === activeId)

  const chooseFile = () => {
    if (!active || active.csv.busy) return
    if (fileRef.current) fileRef.current.value = ''
    fileRef.current?.click()
  }

  const upload = async (file: File) => {
    if (!active) return
    const calendarId = active.calendar_id
    if (!file.name.toLowerCase().endsWith('.csv')) {
      update(calendarId, (calendar) => ({
        ...calendar,
        selectedMethod: calendar.selectedMethod === 'csv' ? null : calendar.selectedMethod,
        csv: { busy: false, preview: null, error: '请选择 .csv 文件。' },
      }))
      return
    }
    update(calendarId, (calendar) => ({
      ...calendar,
      selectedMethod: calendar.selectedMethod === 'csv' ? null : calendar.selectedMethod,
      fileName: file.name,
      csv: { busy: true, preview: null, error: null },
    }))
    try {
      const preview = await previewInitCalendarCsv(calendarId, file)
      update(calendarId, (calendar) => ({
        ...calendar,
        selectedMethod: 'csv',
        csv: { busy: false, preview, error: null },
        python: { ...calendar.python, result: null, error: null },
      }))
    } catch (error) {
      update(calendarId, (calendar) => ({
        ...calendar,
        csv: { busy: false, preview: null, error: errorText(error) },
      }))
    }
  }

  const runPython = async () => {
    if (!active) return
    const calendarId = active.calendar_id
    const code = active.python.code
    update(calendarId, (calendar) => ({
      ...calendar,
      selectedMethod: calendar.selectedMethod === 'python' ? null : calendar.selectedMethod,
      python: { ...calendar.python, busy: true, result: null, error: null },
    }))
    try {
      const result = await testInitCalendarFunction(calendarId, code)
      update(calendarId, (calendar) => result.valid
        ? {
            ...calendar,
            selectedMethod: 'python',
            fileName: '',
            csv: { busy: false, preview: null, error: null },
            python: { ...calendar.python, busy: false, result, error: null },
          }
        : {
            ...calendar,
            python: { ...calendar.python, busy: false, result, error: result.error },
          })
    } catch (error) {
      update(calendarId, (calendar) => ({
        ...calendar,
        python: { ...calendar.python, busy: false, result: null, error: errorText(error) },
      }))
    }
  }

  const downloadTemplate = () => {
    if (!active) return
    const content = `calendar_id,cal_date,is_open\n${active.calendar_id},2026-01-01,false\n${active.calendar_id},2026-01-02,true\n`
    const url = URL.createObjectURL(new Blob([content], { type: 'text/csv;charset=utf-8' }))
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${active.calendar_id}-trading-calendar.csv`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  const removeMethod = (method: CalendarMethod) => {
    if (!active) return
    update(active.calendar_id, (calendar) => method === 'csv'
      ? { ...calendar, selectedMethod: null, fileName: '', csv: { busy: false, preview: null, error: null } }
      : { ...calendar, selectedMethod: null, python: { ...calendar.python, result: null, error: null } })
  }

  if (loading) return <p className="text-[13px] text-ink-2">正在读取交易日历需求…</p>
  if (loadError) return <div className="border-l-2 border-warn bg-warn-soft px-4 py-3 text-[13px] text-warn">无法读取日历需求：{loadError}。可以跳过，自动排程仍会继续执行。</div>
  if (!active) return <p className="text-[13px] text-ink-2">当前渠道无需交易日历，可以继续。</p>

  return (
    <div className="max-w-[900px]">
      {calendars.length > 1 && (
        <div className="mb-4 divide-y divide-line border-y border-line">
          {calendars.map((calendar) => (
            <button key={calendar.calendar_id} type="button" className={`flex w-full items-center gap-3 px-3 py-3 text-left ${calendar.calendar_id === active.calendar_id ? 'bg-accent-soft' : ''}`} onClick={() => setActiveId(calendar.calendar_id)}>
              <span className="min-w-0 flex-1"><span className="block text-[14px] font-[620]">{calendar.label}</span><OverflowText className="text-[12px] text-ink-3" text={`${calendar.channel_labels.join('、')} 使用`} /></span>
              <span className="text-[12px] text-ink-2">{calendar.selectedMethod ? '已配置' : '未配置'}</span>
            </button>
          ))}
        </div>
      )}

      <div className="mb-4">
        <h2 className="text-[16px] font-[650]">{active.label} <span className="font-normal text-ink-3">· {active.channel_labels.join('、')} 使用</span></h2>
        <p className="mt-1 text-[13px] text-ink-2">选择一种刷新方式；不配置也可以继续，自动排程会按原节奏执行。</p>
      </div>

      {CALENDAR_METHODS.map((method) => {
        const expanded = active.expandedMethod === method
        const state = active[method]
        const selected = active.selectedMethod === method
        const label = method === 'python' ? '自定义函数自动刷新' : 'CSV 文件'
        const status = state.busy
          ? { text: '校验中', className: 'text-ink-2' }
          : state.error
            ? { text: '校验失败', className: 'text-warn' }
            : selected
              ? { text: '已配置', className: 'text-ink-2' }
              : { text: '未配置', className: 'text-ink-3' }
        return (
          <div key={method} className={`mb-3 overflow-hidden rounded-[8px] border bg-surface ${expanded ? 'border-accent' : 'border-line'}`}>
            <div className="flex items-center gap-3 px-4 py-3">
              <button type="button" className="flex min-w-0 flex-1 items-center gap-3 text-left" aria-expanded={expanded} onClick={() => update(active.calendar_id, (calendar) => ({ ...calendar, expandedMethod: expanded ? null : method }))}>
                <span className="grid h-9 w-9 flex-none place-items-center rounded-[7px] bg-fill text-ink-2">{method === 'python' ? <Code2 size={18} /> : <FileUp size={18} />}</span>
                <span className="min-w-0 flex-1"><span className="block text-[15px] font-[620]">{label}</span><span className="text-[12.5px] text-ink-2">{method === 'python' ? '验证后保存，后续每日自动补齐' : '导入逐自然日连续的数据'}</span></span>
                <InkRewrite text={status.text} tone="label" className="flex-none text-[12.5px]" textClassName={status.className} />
                <ChevronDown size={16} className={`flex-none text-ink-3 transition-transform duration-200 motion-reduce:transition-none ${expanded ? 'rotate-180' : ''}`} />
              </button>
              {selected && <button type="button" className="grid h-8 w-8 flex-none place-items-center rounded-[7px] text-ink-3 hover:bg-fill hover:text-ink-1" aria-label={`移除${label}`} title={`移除${label}`} onClick={() => removeMethod(method)}><Trash2 size={15} /></button>}
            </div>
            <div className={`grid transition-[grid-template-rows] duration-200 motion-reduce:transition-none ${expanded ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`} inert={!expanded}>
              <div className="min-h-0 overflow-hidden">
                <div className="border-t border-accent/20 p-4 sm:p-5">
                  {method === 'python' ? (
                    <PythonFunctionEditor code={active.python.code} onChange={(code) => update(active.calendar_id, (calendar) => ({ ...calendar, selectedMethod: calendar.selectedMethod === 'python' ? null : calendar.selectedMethod, python: { ...calendar.python, code, result: null, error: null } }))} running={active.python.busy} result={active.python.result} onRun={() => void runPython()} height="auto" minHeight="240px" maxHeight="420px" runLabel="试跑并配置" resultContent={active.python.result?.valid ? <p className="mt-2 text-[13px] text-ink-2">函数已验证，将在保存后立即生成日历并每日刷新。</p> : null} />
                  ) : (
                    <>
                      <input ref={fileRef} type="file" accept=".csv,text/csv" className="sr-only" onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file) }} />
                      <div role="button" tabIndex={active.csv.busy ? -1 : 0} className={`flex min-h-[170px] cursor-pointer select-none flex-col items-center justify-center rounded-[8px] border border-dashed px-6 text-center outline-none sm:min-h-[210px] ${active.dragging ? 'border-accent bg-accent-soft' : active.csv.error ? 'border-warn bg-warn-soft' : active.csv.preview ? 'border-accent bg-accent-soft' : 'border-border-strong bg-bg-subtle hover:border-accent'}`} onClick={chooseFile} onKeyDown={(event: KeyboardEvent<HTMLDivElement>) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); chooseFile() } }} onDragEnter={(event) => { event.preventDefault(); update(active.calendar_id, (calendar) => ({ ...calendar, dragging: true })) }} onDragOver={(event) => event.preventDefault()} onDragLeave={() => update(active.calendar_id, (calendar) => ({ ...calendar, dragging: false }))} onDrop={(event: DragEvent<HTMLDivElement>) => { event.preventDefault(); update(active.calendar_id, (calendar) => ({ ...calendar, dragging: false })); const file = event.dataTransfer.files[0]; if (file) void upload(file) }}>
                        {active.csv.busy ? <><LoaderCircle className="mb-3 animate-spin text-accent motion-reduce:animate-none" /><span>正在校验 {active.fileName}</span></> : active.csv.error ? <><TriangleAlert className="mb-3 text-warn" /><span className="text-warn">CSV 校验未通过</span><span className="mt-2 text-[12.5px] text-ink-2">{active.csv.error}</span></> : active.csv.preview ? <><Check className="mb-3 text-accent" /><span>{active.fileName}</span><span className="mt-2 text-[12.5px] text-ink-2">{active.csv.preview.start} 至 {active.csv.preview.end} · {active.csv.preview.total} 天</span><span className="mt-2 text-[12px] text-ink-3">已加入本次初始化配置</span></> : <><FileUp className="mb-3 text-accent" /><span className="font-[620]">拖入交易日历 CSV</span><span className="mt-1 text-[13px] text-ink-2">或点击选择文件</span></>}
                      </div>
                      <button type="button" className="mt-3 inline-flex items-center gap-1.5 text-[13px] text-accent" onClick={downloadTemplate}><Download size={14} /> 下载 CSV 模板</button>
                    </>
                  )}
                </div>
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
