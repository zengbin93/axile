import { CodeBlock, DeveloperDoc, DocTable, InlineCode, RuleList, SectionTitle } from './DeveloperDoc'
import { buildSystemNotificationMarkdown, SYSTEM_NOTIFICATION_EXAMPLE, SYSTEM_NOTIFICATION_FIELDS, SYSTEM_NOTIFICATION_RULES } from './systemNotificationMarkdown'

export function SystemNotificationDocPage() {
  return (
    <DeveloperDoc category="系统 / 告警" title="系统告警函数" intro={<>用同步或异步 <InlineCode>notify(context)</InlineCode> 接收执行异常或总超时事件，自行发送系统告警。</>} sections={[['contract', '函数契约'], ['example', '可复制示例'], ['context', '系统告警 context']]} markdown={buildSystemNotificationMarkdown}>
      <SectionTitle id="contract">函数契约</SectionTitle><RuleList items={SYSTEM_NOTIFICATION_RULES} />
      <SectionTitle id="example">可复制示例</SectionTitle><CodeBlock code={SYSTEM_NOTIFICATION_EXAMPLE} />
      <SectionTitle id="context">系统告警 context</SectionTitle><DocTable headers={['字段', '类型', '含义']} rows={SYSTEM_NOTIFICATION_FIELDS} minWidth={760} />
    </DeveloperDoc>
  )
}
