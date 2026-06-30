import React, { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export const STAGE_META = {
  extraction:  { label: '信息提取',  icon: '📇', color: '#3b82f6' },
  research:    { label: '背景研究',  icon: '🔍', color: '#8b5cf6' },
  synthesis:   { label: '客户分层',  icon: '📊', color: '#06b6d4' },
  strategy:    { label: '跟进策略',  icon: '🎯', color: '#10b981' },
  critique:    { label: '风险审核',  icon: '🛡️', color: '#f59e0b' },
}

export default function ReportPanel({ stage, report, progress }) {
  const meta = STAGE_META[stage] || { label: stage, icon: '📄', color: '#64748b' }
  const [expanded, setExpanded] = useState(true)
  const pct = progress?.pct || 0
  const isRunning = pct > 0 && pct < 100
  const isDone = pct === 100

  return (
    <div className={`report-panel ${isDone ? 'done' : ''} ${isRunning ? 'running' : ''}`}>
      <div className="report-header" onClick={() => setExpanded(v => !v)}>
        <span className="report-icon">{meta.icon}</span>
        <span className="report-label">{meta.label}</span>
        <span className="report-status">
          {isDone ? '✅' : isRunning ? `${pct}%` : '⏳'}
        </span>
        <span className="report-toggle">{expanded ? '▾' : '▸'}</span>
      </div>
      {expanded && (
        <div className="report-body">
          {report ? (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {report.details || report.summary || JSON.stringify(report, null, 2)}
            </ReactMarkdown>
          ) : isRunning ? (
            <div className="report-loading">正在分析...</div>
          ) : (
            <div className="report-empty">等待上游完成...</div>
          )}
        </div>
      )}
    </div>
  )
}
