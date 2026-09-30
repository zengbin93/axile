export const SYSTEM_NOTIFICATION_FIELDS = [
  ['event_id', 'str', '系统事件标识。'],
  ['event_type', 'str', 'execution_error（执行异常）或 execution_timeout（总超时）。'],
  ['execution_id', 'str | None', '关联执行 ID；试跑时为 None。'],
  ['occurred_at', 'str', '服务本地时间的 ISO 字符串。'],
  ['account', 'dict | None', '关联账户的 id、name；没有账户时为 None。'],
  ['error.type', 'str', '异常类型。'],
  ['error.message', 'str', '异常消息。'],
  ['error.traceback', 'str', '来自异常对象的堆栈。'],
  ['is_test', 'bool', '草稿试跑为 True；真实告警为 False。'],
]
export const SYSTEM_NOTIFICATION_RULES = [
  '保留默认与自定义两种模式。默认模式使用内置飞书卡片；自定义模式运行保存的 notify(context)。切换并保存不会删除另一种模式的配置。',
  'notify 必须只接收一个 context 参数，支持同步或异步函数；自定义模式不允许保存空函数。',
  '系统飞书 Key 通过环境变量 AXILE_SYSTEM_FEISHU_KEY 提供，不在 context 中返回。账户 Key 不注入系统通知函数。',
  '函数在独立进程中运行，总时限为 15 秒；网络请求应设置更短的超时。失败只记录通知结果，不改变交易结论，不自动补发默认通知。',
  '试跑使用当前草稿与当前凭据选择，可选执行异常或超时样例。试跑可能真实发送消息，但不保存配置、不覆盖最近真实告警结果。',
  'Webhook 输入留空保留服务端已保存凭据；清除 Webhook 后保存才会删除。默认模式无 Webhook 时不发送。',
]
export const SYSTEM_NOTIFICATION_EXAMPLE = `import os
from axile.common.feishu import push_feishu_card
from axile.common.notification_context import SystemNotificationContext


def notify(context: SystemNotificationContext) -> None:
    key = os.environ.get("AXILE_SYSTEM_FEISHU_KEY", "")
    if not key:
        raise ValueError("请配置系统飞书 Webhook")
    title = "系统告警试跑" if context["is_test"] else "系统执行告警"
    push_feishu_card({
        "header": {"title": {"tag": "plain_text", "content": title}},
        "elements": [{"tag": "markdown", "content": context["error"]["message"]}],
    }, key, timeout=8)
`
export function buildSystemNotificationMarkdown() {
  return `# 系统告警函数\n\n## 函数契约\n\n${SYSTEM_NOTIFICATION_RULES.map((rule) => `- ${rule}`).join('\n')}\n\n## 可复制示例\n\n\`\`\`python\n${SYSTEM_NOTIFICATION_EXAMPLE}\`\`\`\n\n## 系统告警 context\n\n| 字段 | 类型 | 含义 |\n| --- | --- | --- |\n${SYSTEM_NOTIFICATION_FIELDS.map((row) => `| ${row.map((cell) => cell.replaceAll('|', '\\|')).join(' | ')} |`).join('\n')}`
}
