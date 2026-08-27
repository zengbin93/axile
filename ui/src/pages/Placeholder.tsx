import { useParams } from 'react-router'
import { Link } from '@/components/ui/nav'

/** M0 通用占位页：标题 + 里程碑说明 + 返回仪表盘。 */
export function Placeholder({ title, milestone }: { title: string; milestone: string }) {
  const params = useParams()
  const id = params.id
  return (
    <section>
      <Link to="/" className="text-[13px] text-ink-2 hover:text-ink-1">
        ← 返回仪表盘
      </Link>
      <h1 className="mt-3 text-[18px] font-[640]">{title}</h1>
      <div className="mt-4 rounded-card border border-line bg-surface p-6 text-[14px] text-ink-2">
        {id != null && (
          <>
            ID：<b className="text-ink-1">{id}</b>
            <br />
          </>
        )}
        本页将在 <b className="text-ink-1">{milestone}</b> 实现。
      </div>
    </section>
  )
}
