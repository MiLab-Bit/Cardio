import React from 'react'
import { useChatStore } from '../store'
import CRMSyncStatus from './CRMSyncStatus'

const STATUS_MAP = {
  done: { label: '完成', className: 'done' },
  active: { label: '生成中', className: 'active' },
  pending: { label: '待审中', className: 'pending' },
}

function RightDrawer({ onClose }) {
  const { state } = useChatStore()
  const { outputFiles } = state

  // 如果没有文件，显示默认占位
  const files = outputFiles.length > 0 ? outputFiles : [
    { name: '提取报告.md', meta: '12.4 KB · 刚刚', status: 'done' },
    { name: '研究报告.md', meta: '生成中...', status: 'active' },
    { name: '客户分层.md', meta: '待审中', status: 'pending' },
    { name: '跟进策略.md', meta: '待审中', status: 'pending' },
    { name: '风险审核.md', meta: '待审中', status: 'pending' },
  ]

  return (
    <aside className="right-drawer">
      <div className="drawer-header">
        产出文件
        <button
          onClick={onClose}
          style={{
            background: 'transparent',
            border: 'none',
            color: 'var(--text-muted)',
            cursor: 'pointer',
            fontSize: '16px',
            marginLeft: 'auto',
          }}
        >
          ✕
        </button>
      </div>
      <div className="drawer-body">
        {files.map((file) => {
          const statusInfo = STATUS_MAP[file.status] || STATUS_MAP.pending
          return (
            <div key={file.name} className="drawer-file">
              <div className="drawer-file-name">
                <span className={`file-dot ${statusInfo.className}`} />
                {file.name}
              </div>
              <div className="drawer-file-meta">{file.meta}</div>
            </div>
          )
        })}

        {/* CRM 同步状态 */}
        <CRMSyncStatus />
      </div>
      <div className="drawer-footer">
        <button className="drawer-btn">全部导出</button>
        <button className="drawer-btn primary">查看全部</button>
      </div>
    </aside>
  )
}

export default RightDrawer
