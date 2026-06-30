import React, { useState, useRef, useCallback } from 'react'
import ReportPanel, { STAGE_META } from '../components/ReportPanel'
import useSSE from '../hooks/useSSE'
import './MainWorkspace.css'

const STAGES = ['extraction', 'research', 'synthesis', 'strategy', 'critique']

export default function MainWorkspace({ session, onSessionUpdate, onToggleSidebar, sidebarOpen }) {
  const [file, setFile] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [reports, setReports] = useState({})
  const [progress, setProgress] = useState({})
  const [sessionId, setSessionId] = useState(null)
  const fileInputRef = useRef(null)

  const { data: sseData, done, error, connect } = useSSE(
    sessionId ? `/api/pipeline/stream/${sessionId}` : null
  )

  // SSE 数据到达时更新 progress 和 reports
  React.useEffect(() => {
    if (!sseData) return
    if (sseData.stage && sseData.pct !== undefined) {
      setProgress(prev => ({ ...prev, [sseData.stage]: sseData }))
    }
    if (sseData.agent_reports) {
      setReports(sseData.agent_reports)
    }
    if (sseData.ctx) {
      // 完整上下文返回，提取所有报告
      const ctx = sseData.ctx
      const extracted = {}
      for (const stage of STAGES) {
        if (ctx[`${stage}_report`] || (ctx.agent_reports && ctx.agent_reports[stage])) {
          extracted[stage] = ctx.agent_reports?.[stage] || ctx[`${stage}_report`] || null
        }
      }
      setReports(extracted)
    }
  }, [sseData])

  const handleFileSelect = (e) => {
    const f = e.target.files?.[0]
    if (f) setFile(f)
  }

  const handleUpload = useCallback(async () => {
    if (!file) return
    setUploading(true)
    setReports({})
    setProgress({})

    const formData = new FormData()
    formData.append('file', file)

    try {
      const res = await fetch('/api/pipeline/upload', {
        method: 'POST',
        body: formData,
      })
      const { session_id } = await res.json()
      setSessionId(session_id)
      onSessionUpdate?.({ id: session_id, file: file.name, created_at: new Date().toISOString() })
      // 开始 SSE 监听
      connect()
    } catch (err) {
      alert(`上传失败: ${err.message}`)
    } finally {
      setUploading(false)
    }
  }, [file, connect, onSessionUpdate])

  const allDone = STAGES.every(s => progress[s]?.pct === 100)

  return (
    <div className="workspace">
      {/* 顶部工具栏 */}
      <header className="workspace-header">
        <button className="btn-icon" onClick={onToggleSidebar} title={sidebarOpen ? '收起侧栏' : '展开侧栏'}>
          ☰
        </button>
        <h1 className="workspace-title">Byou · AI 商务分身</h1>
        <div className="header-actions">
          <input ref={fileInputRef} type="file" accept="image/*,.pdf,.txt,.wav,.mp3,.m4a" onChange={handleFileSelect} />
          {!file && (
            <button className="btn-secondary" onClick={() => fileInputRef.current?.click()}>
              📎 选择文件
            </button>
          )}
          {file && (
            <>
              <span className="file-name">{file.name}</span>
              <button className="btn-primary" onClick={handleUpload} disabled={uploading}>
                {uploading ? '上传中...' : '🚀 开始分析'}
              </button>
            </>
          )}
        </div>
      </header>

      {/* 流式进度条 */}
      {sessionId && (
        <div className="progress-track">
          {STAGES.map(stage => {
            const p = progress[stage]
            const meta = ReportPanel.STAGE_META?.[stage] || {}
            return (
              <div key={stage} className={`progress-step ${p?.pct === 100 ? 'done' : p?.pct > 0 ? 'active' : ''}`}>
                <div className="step-dot" style={{ background: p?.pct === 100 ? 'var(--success)' : p?.pct > 0 ? 'var(--accent)' : 'var(--text-muted)' }} />
                <span className="step-label">{meta.label || stage}</span>
                {p?.pct > 0 && p?.pct < 100 && <span className="step-pct">{p.pct}%</span>}
              </div>
            )
          })}
        </div>
      )}

      {/* 5 份报告面板 */}
      <div className="reports-grid">
        {STAGES.map(stage => (
          <ReportPanel
            key={stage}
            stage={stage}
            report={reports[stage]}
            progress={progress[stage]}
          />
        ))}
      </div>

      {error && <div className="error-banner">⚠️ 连接错误: {error}</div>}
      {allDone && <div className="done-banner">✅ 全部分析完成！</div>}
    </div>
  )
}
