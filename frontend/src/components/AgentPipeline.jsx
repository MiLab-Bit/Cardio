import React from 'react'
import { useChatStore } from '../store'

const AGENTS = [
  { key: 'extract', label: '提取' },
  { key: 'research', label: '研究' },
  { key: 'segment', label: '分层' },
  { key: 'strategy', label: '策略' },
  { key: 'critic', label: '审核' },
]

function AgentPipeline() {
  const { state } = useChatStore()
  const { agentProgress } = state

  return (
    <div className="agent-pipeline">
      {AGENTS.map((agent, idx) => {
        const status = agentProgress[agent.key] || 'pending'
        return (
          <React.Fragment key={agent.key}>
            <div className={`pipeline-stage ${status}`}>
              <div className="stage-dot" />
              <div className="stage-label">{agent.label}</div>
            </div>
            {idx < AGENTS.length - 1 && (
              <div className={`pipeline-connector ${status === 'completed' ? 'active' : ''}`} />
            )}
          </React.Fragment>
        )
      })}
    </div>
  )
}

export default AgentPipeline
