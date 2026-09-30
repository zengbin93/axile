import { useState, type ReactNode } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import { Segmented } from '@/components/ui/Segmented'
import { InkRewrite } from '@/components/ui/InkRewrite'
import { Row, TEXT } from '@/features/account/editUi'
import { extractFeishuKey } from '@/features/account/feishuUpdate'
import { systemAlertKey, type SystemAlertDraft } from './systemAlertDraft'

function AlertRow({ compact, label, hint, children }: { compact: boolean; label: string; hint?: string; children: ReactNode }) {
  if (!compact) return <Row label={label} hint={hint} top span>{children}</Row>
  return <div><div className="mb-2 flex items-baseline gap-2 text-[13px] text-ink-2">{label}{hint && <span className="text-[12px] text-ink-3">{hint}</span>}</div>{children}</div>
}

/** 初始化与日常设置共用模式、凭据编辑；空输入保留，清除是明确操作。 */
export function SystemAlertFields({ draft, configured, onChange, disabled, custom, keyActions, compact = false, showModeSelector = true }: {
  draft: SystemAlertDraft
  configured: boolean
  onChange: (patch: Partial<SystemAlertDraft>) => void
  disabled?: boolean
  custom?: ReactNode
  keyActions?: ReactNode
  compact?: boolean
  showModeSelector?: boolean
}) {
  const [revealed, setRevealed] = useState(false)
  const key = systemAlertKey(draft)
  return (
    <div className="space-y-4">
      {showModeSelector && <AlertRow compact={compact} label="通知方式">
        <Segmented value={draft.mode} options={[{ value: 'default', label: '默认', disabled }, { value: 'function', label: '自定义', disabled }]} onChange={(mode) => onChange({ mode })} />
      </AlertRow>}
      <AlertRow compact={compact} label="Webhook" hint={draft.clearKey ? '保存后清除' : (key || configured ? '已配置' : '未配置')}>
        <div className="flex flex-wrap items-center gap-2">
          <div className={`relative min-w-0 flex-1 ${compact ? 'basis-full' : ''}`}>
            <input aria-label="系统飞书 Webhook" type={revealed ? 'text' : 'password'} className={`${TEXT} pr-10`} value={draft.keyInput} disabled={disabled} placeholder={configured ? '已配置 · 留空保持不变' : '可粘贴整条 webhook 链接'} spellCheck={false} autoComplete="off" onChange={(e) => onChange({ keyInput: e.target.value, clearKey: false })} onBlur={() => onChange({ keyInput: extractFeishuKey(draft.keyInput) })} />
            <button type="button" aria-label={revealed ? '隐藏机器人 Key' : '显示机器人 Key'} className="absolute right-1 top-1/2 flex h-8 w-8 -translate-y-1/2 cursor-pointer items-center justify-center rounded-md text-ink-3 hover:bg-fill" onClick={() => setRevealed((value) => !value)}>{revealed ? <EyeOff size={16} /> : <Eye size={16} />}</button>
          </div>
          <button type="button" className="cursor-pointer text-[13px] text-ink-2 disabled:opacity-45" disabled={disabled || (!configured && !draft.clearKey && !draft.keyInput)} onClick={() => onChange({ clearKey: !draft.clearKey, keyInput: '' })}><InkRewrite text={draft.clearKey ? '撤销清除' : '清除 Webhook'} tone="label" /></button>
          {keyActions}
        </div>
        <p className="mt-1 text-[12px] text-ink-3">{draft.mode === 'function' ? '函数可通过 AXILE_SYSTEM_FEISHU_KEY 使用此凭据，也可自行选择其他渠道。' : '未配置 Webhook 时不发送系统告警。'}</p>
      </AlertRow>
      <div inert={draft.mode !== 'function'} className={`grid transition-[grid-template-rows] duration-200 motion-reduce:transition-none ${draft.mode === 'function' ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}>
        <div className="min-h-0 overflow-hidden">{custom}</div>
      </div>
    </div>
  )
}
