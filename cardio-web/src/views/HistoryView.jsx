// 历史研判：记录列表 + 展开五段报告
import { useEffect, useState } from 'react'
import { Loader2, ChevronDown, History as HistoryIcon } from 'lucide-react'
import { getHistory, AuthError } from '../api.js'
import EmptyState from '../components/EmptyState.jsx'
import { STAGE_ORDER } from '../constants.js'

export default function HistoryView() {
  const [records, setRecords] = useState([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(null)

  useEffect(() => {
    ;(async () => {
      setLoading(true)
      try { setRecords(await getHistory()) } catch (e) {
        if (e instanceof AuthError) return
        setRecords([])
      } finally { setLoading(false) }
    })()
  }, [])

  return (
    <div className="h-full overflow-y-auto px-4 md:px-5 py-5">
      <div className="max-w-3xl mx-auto">
        <h2 className="font-serif text-xl font-bold text-ink mb-4">历史研判</h2>
        {loading ? (
          <div className="text-ink-soft/70 text-sm flex items-center gap-2 py-10 justify-center">
            <Loader2 size={16} className="animate-spin" /> 加载中…
          </div>
        ) : records.length === 0 ? (
          <EmptyState
            icon="history"
            title="暂无研判记录"
            desc="完成一次「数字商册分析」后，这里会留下完整的五段研判档案。"
          />
        ) : (
          <div className="space-y-3">
            {records.map((r) => {
              const doneStages = STAGE_ORDER.filter((st) => r.result?.agent_reports?.[st.key])
              const isOpen = open === r.id
              return (
                <div key={r.id} className="paper rounded-2xl border border-brass/20 bg-white/70 shadow-card overflow-hidden transition hover:border-brass/40">
                  <button
                    className="w-full text-left px-4 py-3 flex items-center gap-3"
                    onClick={() => setOpen(isOpen ? null : r.id)}
                  >
                    <div className="w-8 h-8 rounded-full bg-brass/15 flex items-center justify-center shrink-0">
                      <HistoryIcon size={14} className="text-brass" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm text-ink truncate">{(r.input_text || '').slice(0, 60) || '（名片图片分析）'}</div>
                      <div className="text-[11px] text-ink-soft/60 flex items-center gap-2">
                        <span>{new Date(r.created_at).toLocaleString()}</span>
                        <span className="text-jade">· {doneStages.length} 段报告</span>
                      </div>
                    </div>
                    <ChevronDown
                      size={16}
                      className={`text-ink-soft/50 shrink-0 transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`}
                    />
                  </button>
                  {isOpen && (
                    <div className="px-4 pb-4 space-y-2 animate-[fadeIn_.25s_ease]">
                      {doneStages.map((st) => {
                        const rep = r.result.agent_reports[st.key]
                        return (
                          <div key={st.key} className="rounded-lg border border-brass/15 bg-white/60 p-3">
                            <div className="text-sm font-medium text-ink">{st.icon} {rep.label || st.label}</div>
                            <div className="text-[13px] text-ink-soft mt-1 leading-relaxed">{rep.summary}</div>
                            {rep.confidence != null && (
                              <div className="mt-1.5 flex items-center gap-2">
                                <div className="flex-1 h-1.5 rounded-full bg-brass/15 overflow-hidden">
                                  <div className="h-full rounded-full bg-jade" style={{ width: `${Math.round(rep.confidence * 100)}%` }} />
                                </div>
                                <span className="text-[11px] text-jade">{Math.round(rep.confidence * 100)}%</span>
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
