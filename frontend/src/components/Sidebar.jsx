import React from 'react'

const navItems = [
  { section: 'Workspace', items: [
    { icon: '+', label: '新建任务', badge: null },
    { icon: '◎', label: '自动化', badge: null },
    { icon: '💬', label: '任务对话', badge: '12' },
    { icon: '◈', label: '工作空间', badge: null },
  ]},
  { section: 'Intelligence', items: [
    { icon: '🔍', label: '模型审计', badge: null },
    { icon: '👥', label: 'CRM 用户库', badge: '847' },
  ]},
]

function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <div className="sidebar-logo">
          <div className="logo-icon">B</div>
          <div>
            <div className="logo-text">Byou · 商务分身</div>
            <div className="logo-subtitle">BD Intelligence</div>
          </div>
        </div>
      </div>

      <nav className="sidebar-nav">
        {navItems.map((section) => (
          <React.Fragment key={section.section}>
            <div className="nav-section-label">{section.section}</div>
            {section.items.map((item) => (
              <div key={item.label} className="nav-item">
                <span className="nav-icon">{item.icon}</span>
                <span className="nav-label">{item.label}</span>
                {item.badge && <span className="nav-badge">{item.badge}</span>}
              </div>
            ))}
          </React.Fragment>
        ))}
      </nav>

      <div className="sidebar-footer">
        <div className="footer-avatar">咪</div>
        <div>
          <div className="footer-name">咪</div>
          <div className="footer-role">创业者</div>
        </div>
      </div>
    </aside>
  )
}

export default Sidebar
