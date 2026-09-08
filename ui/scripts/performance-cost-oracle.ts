import { costExecutions, dailyCosts, summarizeCosts } from '../src/features/history/costs'
import { selectedExecutions } from '../src/features/history/chartModel'

const input = await Bun.stdin.json()
const executions = costExecutions(input.records.map((record: { created_at: string }) => ({ kind: 'execution', occurred_at: record.created_at, record })))
const selected = selectedExecutions(executions, input.selection ?? null)
process.stdout.write(JSON.stringify({ executions: selected, daily: Object.fromEntries(dailyCosts(selected)), summary: summarizeCosts(selected.flatMap(execution => execution.trades)) }))
