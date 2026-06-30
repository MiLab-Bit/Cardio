import React from 'react'
import { useChatStore, AGENT_NAMES } from '../store'

function ChatArea() {
  const { state, dispatch, ACTIONS } = useChatStore()
  const { messages, isTyping, activeAgentTabs } = state

  return (
    <div className="chat-messages">
      {messages.map((msg) => (
        <React.Fragment key={msg.id}>
          {msg.type === 'user' ? (
            <UserMessage msg={msg} />
          ) : (
            <AgentMessage
              msg={msg}
              activeTab={activeAgentTabs[msg.id] ?? 0}
              onTabChange={(idx) =>
                dispatch({
                  type: ACTIONS.SET_ACTIVE_AGENT_TAB,
                  payload: { msgId: msg.id, tabIdx: idx },
                })
              }
            />
          )}
        </React.Fragment>
      ))}

      {/* Typing 动画 */}
      {isTyping && (
        <div className="agent-message">
          <div className="agent-header">
            <div className="agent-avatar">B</div>
          </div>
          <div className="agent-card">
            <div className="typing-indicator">
              <span className="typing-dot" />
              <span className="typing-dot" />
              <span className="typing-dot" />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function UserMessage({ msg }) {
  return (
    <div className="user-message">
      <div>
        <div className="user-bubble">{msg.content}</div>
        {msg.files?.length > 0 && (
          <div className="user-files">
            {msg.files.map((f, i) => (
              <span key={i} className="user-file-tag">{f.name}</span>
            ))}
          </div>
        )}
        <div className="user-time">{msg.time}</div>
      </div>
    </div>
  )
}

function AgentMessage({ msg, activeTab, onTabChange }) {
  const agentTabs = msg.tabs || AGENT_NAMES
  const report = msg.reports?.[AGENT_NAMES[activeTab]] || msg.reports?.[agentTabs[activeTab]]

  return (
    <div className="agent-message">
      <div className="agent-header">
        <div className="agent-avatar">{msg.agentName?.[0] || 'B'}</div>
      </div>
      <div className="agent-card">
        {/* Tab 栏 */}
        <div className="agent-tabs">
          {agentTabs.map((tab, idx) => (
            <div
              key={tab}
              className={`agent-tab ${idx === activeTab ? 'active' : ''}`}
              onClick={() => onTabChange(idx)}
            >
              {tab}
            </div>
          ))}
        </div>

        {/* 报告内容 */}
        <div className="agent-content">
          {report ? (
            <>
              <div className="agent-content-title">
                <div className="agent-content-title-left">
                  <span style={{ color: 'var(--accent)', fontSize: '13px' }}>📄</span>
                  {report.title || `${agentTabs[activeTab]}报告`}
                </div>
                <div className="agent-status-badge">{report.status || '完成'}</div>
              </div>
              {report.fields?.map((f) => (
                <div key={f.label} className="agent-field">
                  <span className="agent-field-label">{f.label}</span>
                  <span className="agent-field-value">{f.value}</span>
                </div>
              ))}
              {report.content && (
                <div className="agent-report-content">{report.content}</div>
              )}
            </>
          ) : (
            <div className="agent-content-placeholder">
              {activeTab === 0 ? '等待信息提取...' : `等待${agentTabs[activeTab]}...`}
            </div>
          )}

          {/* 子报告列表 */}
          {msg.reports && Object.entries(msg.reports).length > 0 && (
            <div className="sub-reports-list">
              {Object.entries(msg.reports).map(([agent, data]) => (
                <div key={agent} className="sub-report">
                  <div className="sub-report-left">
                    <span style={{ color: 'var(--accent)', fontSize: '13px' }}>🔍</span>
                    {data.title || agent}
                  </div>
                  <div className="sub-report-right">{data.status || '完成'} ›</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      {msg.time && <div className="agent-time">{msg.time}</div>}
    </div>
  )
}

export default ChatArea
