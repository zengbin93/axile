import { CodeBlock, DeveloperDoc, DocTable, InlineCode, RuleList, SectionTitle } from './DeveloperDoc'
import { buildNotificationMarkdown, CONTRACT_RULES, EXECUTION_FIELDS, FAILURE_RULES, NOTIFICATION_FIELDS, NOTIFY_CODE, TEST_RULES, type NotificationField } from './notificationMarkdown'

const SECTIONS = [['contract', '函数契约'], ['example', '可复制示例'], ['context', '账户执行 context'], ['test', '试跑与真实执行'], ['errors', '常见错误']] as const

function fieldRows(fields: NotificationField[]) {
  return fields.map(({ name, type, desc }) => [<code key="name" className="font-mono text-[13px] text-ink-1">{name}</code>, <code key="type" className="font-mono text-[13px] text-ink-3">{type}</code>, desc])
}

export function NotificationDocPage() {
  return (
    <DeveloperDoc
      category="账户 / 通知"
      title="账户执行通知函数"
      intro={<>用同步 <InlineCode>notify(context)</InlineCode> 接收执行结束时的脱敏快照，自行发送账户执行通知。</>}
      sections={SECTIONS}
      markdown={buildNotificationMarkdown}
    >
      <SectionTitle id="contract">函数契约</SectionTitle>
      <RuleList items={CONTRACT_RULES} />

      <SectionTitle id="example">可复制示例</SectionTitle>
      <p className="mt-2 text-[15px] leading-7 text-ink-2">示例从部署进程的环境变量读取通知地址。它会在试跑时跳过发送；要测试真实渠道，可按需调整此判断。</p>
      <div className="mt-4"><CodeBlock code={NOTIFY_CODE} /></div>

      <SectionTitle id="context">账户执行 context</SectionTitle>
      <p className="mt-2 text-[15px] leading-7 text-ink-2">这是执行结束时的 JSON 可序列化快照。字段来自本次执行及账户公开配置。</p>
      <DocTable headers={['字段', '类型', '含义']} rows={fieldRows(NOTIFICATION_FIELDS)} minWidth={760} />
      <h3 className="mt-7 text-[16px] font-[600]">常用嵌套字段</h3>
      <DocTable headers={['字段', '类型', '含义']} rows={fieldRows(EXECUTION_FIELDS)} minWidth={760} />
      <p className="mt-4 border-l-2 border-accent pl-4 text-[14.5px] leading-7 text-ink-2">资产不可用时相关值可能为 <InlineCode>None</InlineCode>，持仓可能为 <InlineCode>None</InlineCode>；订单、成交和品种列表也可能为空。</p>

      <SectionTitle id="test">试跑与真实执行</SectionTitle>
      <RuleList items={TEST_RULES} />

      <SectionTitle id="errors">常见错误</SectionTitle>
      <RuleList items={FAILURE_RULES} />
    </DeveloperDoc>
  )
}
