import { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { PythonFunctionEditor, type PythonProblem, type PythonValidationState } from '../src/components/ui/PythonFunctionEditor'
import '../src/styles/theme.css'

export function Fixture() {
  const [code, setCode] = useState('from axile.server.context import Context\n\ndef calculate_portfolio(context: Context) -> dict[str, float]:\n    price = context.get_price("rb2610")\n    return {"rb2610": price}\n')
  const [problems, setProblems] = useState<PythonProblem[]>([])
  const [result, setResult] = useState<PythonValidationState | null>(null)
  const [ranCode, setRanCode] = useState('')
  return <main style={{ height: '90vh', display: 'flex', flexDirection: 'column' }}>
    <PythonFunctionEditor code={code} onChange={setCode} running={false} result={result} stale={ranCode !== code} onRun={() => { setRanCode(code); setResult({ valid: false, errorLine: 1, errorMessage: '模拟试跑错误' }) }} layout="workbench" fill onProblems={setProblems} />
    <output data-testid="code" hidden>{code}</output>
    <output data-testid="problems">{JSON.stringify(problems)}</output>
  </main>
}
createRoot(document.getElementById('root')!).render(<Fixture />)
