// 五段管线阶段卡：等待 / 进行中 / 完成 三态
import { CheckCircle2, Circle, Loader2, ChevronDown } from 'lucide-react'

export default function StageCard({ meta, state, index, total }) {
  const done = state?.status === 'done'
  const start = state?.status === 'start'
  const error = state?.status === 'error'
  return (
    <div
      className={`relative rounded-2xl border p-4 transition-all duration-300 ${
        done ? 'border-jade/40 bg-jade/5'
          : start ? 'border-brass/50 bg-brass/5 shadow-[0_0_0_3px_rgba(176,141,87,0.12)]'
            : error ? 'border-cinnabar/40 bg-cinnabar/5'
              : 'border-brass/15 bg-white/40'
      }`}
    >
      {/* 阶段序号徽标 */}
      <div className="flex items-center gap-3">
        <div className="relative">
          <div className={`w-9 h-9 rounded-full flex items-center justify-center text-lg ${
            done ? 'bg-jade/15' : start ? 'bg-brass/15' : 'bg-brass/8'
          }`}>
            {meta.icon}
          </div>
          <span className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-ink text-parchment text-[9px] font-bold flex items-center justify-center">
            {index + 1}
          </span>
        </div>
        <div className="flex-1 min-w-0">
          <div className="font-medium text-ink flex items-center gap-1.5">
            {meta.label}
            {done && <span className="text-[10px] text-jade font-normal">已完成</span>}
            {start && <span className="text-[10px] text-brass font-normal">进行中…</span>}
          </div>
          <div className="text-[11px] text-ink-soft/70">担当 · {meta.agent}</div>
        </div>
        {done ? (
          <CheckCircle2 size={20} className="text-jade shrink-0" />
        ) : start ? (
          <Loader2 size={18} className="text-brass animate-spin shrink-0" />
        ) : error ? (
          <span className="text-cinnabar text-lg shrink-0">⚠️</span>
        ) : (
          <Circle size={18} className="text-brass/30 shrink-0" />
        )}
      </div>

      {/* 完成后的报告 */}
      {done && state.report && (
        <div className="mt-3 text-sm text-ink-soft leading-relaxed animate-[fadeIn_.3s_ease]">
          <div className="text-ink">{state.report.summary}</div>
          {state.report.confidence != null && (
            <div className="mt-2 flex items-center gap-2">
              <span className="text-[11px] text-ink-soft/70 w-14 shrink-0">置信度</span>
              <div className="flex-1 h-1.5 rounded-full bg-brass/15 overflow-hidden">
                <div
                  className="h-full rounded-full bg-jade transition-all duration-700"
                  style={{ width: `${Math.round((state.report.confidence || 0) * 100)}%` }}
                />
              </div>
              <span className="text-[11px] text-jade font-medium w-9 text-right">
                {Math.round((state.report.confidence || 0) * 100)}%
              </span>
            </div>
          )}
          {state.report.details && (
            <details className="mt-2 group">
              <summary className="flex items-center gap-1 text-[12px] text-brass-deep cursor-pointer select-none hover:text-brass">
                <ChevronDown size={12} className="transition-transform group-open:rotate-180" />
                查看研判详情
              </summary>
              <pre className="mt-1.5 whitespace-pre-wrap text-[12px] text-ink-soft/80 leading-relaxed">
                {typeof state.report.details === 'string'
                  ? state.report.details
                  : JSON.stringify(state.report.details, null, 2)}
              </pre>
            </details>
          )}
        </div>
      )}

      {/* 阶段间连线 */}
      {index < total - 1 && (
        <div className={`absolute left-[26px] top-[52px] w-0.5 h-[14px] rounded ${done ? 'bg-jade/40' : 'bg-brass/15'}`} />
      )}
    </div>
  )
}
