import React, { useState, useEffect } from 'react'
import { API_BASE } from '../services/api'

const STATUS_LABELS = {
  pending: '等待中',
  in_progress: '同步中',
  success: '成功',
  failed: '失败',
  conflict: '冲突',
  skipped: '已跳过',
}

const PROVIDER_LABELS = {
  generic: '通用 CRM',
  salesforce: 'Salesforce',
  hubspot: 'HubSpot',
}

function CRMSyncStatus() {
  const [config, setConfig] = useState(null)
  const [history, setHistory] = useState([])
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [error, setError] = useState('')

  // Load CRM config and sync history
  const loadData = async () => {
    setLoading(true)
    setError('')
    try {
      const [configResp, statusResp] = await Promise.all([
        fetch(`${API_BASE}/crm/config`, {
          headers: { 'X-Byou-Key': 'dev-key' },
        }).then(r => r.json()),
        fetch(`${API_BASE}/crm/sync/status?limit=10`, {
          headers: { 'X-Byou-Key': 'dev-key' },
        }).then(r => r.json()),
      ])
      setConfig(configResp.config || null)
      setHistory(statusResp.records || [])
    } catch (err) {
      setError('加载失败: ' + err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
    // Refresh every 30 seconds
    const interval = setInterval(loadData, 30000)
    return () => clearInterval(interval)
  }, [])

  const handleManualSync = async () => {
    setSyncing(true)
    setError('')
    try {
      const resp = await fetch(`${API_BASE}/crm/sync/push`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Byou-Key': 'dev-key',
        },
        body: JSON.stringify({ pipeline_result: null }),
      })
      const data = await resp.json()
      if (data.status === 'ok') {
        await loadData()
      } else {
        setError(data.message || '同步失败')
      }
    } catch (err) {
      setError('同步失败: ' + err.message)
    } finally {
      setSyncing(false)
    }
  }

  if (loading) {
    return (
      <div className="crm-sync-status">
        <div className="crm-loading">加载中...</div>
      </div>
    )
  }

  const isConnected = config && config.api_url

  return (
    <div className="crm-sync-status">
      <div className="crm-header">
        <div className="crm-title">
          <span className="crm-icon">🔄</span>
          CRM 同步
        </div>
        <div className={`crm-connection-status ${isConnected ? 'connected' : 'disconnected'}`}>
          {isConnected ? '● 已连接' : '○ 未连接'}
        </div>
      </div>

      {isConnected && (
        <div className="crm-config-info">
          <div className="crm-provider">
            提供商: {PROVIDER_LABELS[config.provider] || config.provider}
          </div>
          <div className="crm-auto-push">
            自动推送: {config.auto_push ? '开启' : '关闭'}
          </div>
        </div>
      )}

      {error && (
        <div className="crm-error">{error}</div>
      )}

      {isConnected && (
        <button
          className="crm-sync-btn"
          onClick={handleManualSync}
          disabled={syncing}
        >
          {syncing ? '同步中...' : '手动同步'}
        </button>
      )}

      {!isConnected && (
        <div className="crm-setup-hint">
          请在设置中配置 CRM 连接信息
        </div>
      )}

      {isConnected && history.length > 0 && (
        <div className="crm-history">
          <div className="crm-history-title">最近同步</div>
          <div className="crm-history-list">
            {history.slice(0, 5).map((record, idx) => (
              <div key={idx} className={`crm-history-item ${record.status}`}>
                <div className="crm-history-direction">
                  {record.direction === 'push' ? '↑ 推送' : '↓ 拉取'}
                </div>
                <div className="crm-history-status">
                  {STATUS_LABELS[record.status] || record.status}
                </div>
                <div className="crm-history-time">
                  {record.created_at ? new Date(record.created_at).toLocaleString('zh-CN', {
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                  }) : '--'}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default CRMSyncStatus
