import React from 'react'
import './SessionTree.css'

export default function SessionTree({ sessions, activeId, onSelect, onNewSession }) {
  return (
    <div className="session-tree">
      <div className="tree-header">
        <h2>会话记录</h2>
        <button className="btn-new-session" onClick={onNewSession} title="新建会话">＋</button>
      </div>
      <div className="tree-list">
        {sessions.length === 0 && (
          <div className="tree-empty">暂无会话<br/>上传文件开始分析</div>
        )}
        {sessions.map(s => (
          <div
            key={s.id}
            className={`tree-item ${s.id === activeId ? 'active' : ''}`}
            onClick={() => onSelect(s.id)}
          >
            <span className="tree-item-icon">📄</span>
            <div className="tree-item-info">
              <span className="tree-item-name">{s.file || s.id.slice(0,8)}</span>
              <span className="tree-item-time">
                {s.created_at ? new Date(s.created_at).toLocaleString('zh-CN', { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'}) : ''}
              </span>
            </div>
          </div>
        ))}
      </div>
      <div className="tree-footer">
        <div className="system-status">
          <span className="status-dot online" />
          <span>后端已连接</span>
        </div>
      </div>
    </div>
  )
}
