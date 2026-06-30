import React from 'react'

function TopBar({ onOpenDrawer }) {
  return (
    <header className="topbar">
      <div className="topbar-left">
        <span className="status-dot" />
        <span>分析名片 — 张总 · 腾讯科技</span>
      </div>
      <div className="topbar-right">
        <div className="model-selector">
          step256kv2 <span style={{ fontSize: '9px' }}>▾</span>
        </div>
        <button className="topbar-btn">⋯</button>
        <span className="topbar-label" onClick={onOpenDrawer}>产出文件</span>
      </div>
    </header>
  )
}

export default TopBar
