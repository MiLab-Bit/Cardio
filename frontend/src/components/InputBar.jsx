import React, { useState, useRef, useEffect, useCallback } from 'react'
import { useChatStore } from '../store'
import { sendMessage } from '../services/api'

const MODELS = ['step256kv2', 'step-asr', 'step-1']
const ACCEPTED_TYPES = {
  'image/*': ['.png', '.jpg', '.jpeg', '.webp', '.tiff', '.tif'],
  'audio/*': ['.mp3', '.wav', '.ogg', '.m4a'],
  'video/*': ['.mp4'],
  'application/pdf': ['.pdf'],
}

function InputBar() {
  const [input, setInput] = useState('')
  const [modelOpen, setModelOpen] = useState(false)
  const [selectedModel, setSelectedModel] = useState(MODELS[0])
  const [files, setFiles] = useState([])       // 已选文件列表
  const [dragOver, setDragOver] = useState(false) // 拖拽悬停状态
  const textareaRef = useRef(null)
  const fileInputRef = useRef(null)
  const dropZoneRef = useRef(null)

  const { state, dispatch, ACTIONS } = useChatStore()
  const { inputDisabled } = state

  // 自适应文本框高度
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 100) + 'px'
    }
  }, [input])

  // 拖拽事件处理
  const handleDragOver = useCallback((e) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(true)
  }, [])

  const handleDragLeave = useCallback((e) => {
    e.preventDefault()
    e.stopPropagation()
    // 只有离开整个 drop zone 才取消高亮
    if (dropZoneRef.current && !dropZoneRef.current.contains(e.relatedTarget)) {
      setDragOver(false)
    }
  }, [])

  const handleDrop = useCallback((e) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(false)

    const droppedFiles = Array.from(e.dataTransfer.files)
    if (droppedFiles.length > 0) {
      addFiles(droppedFiles)
    }
  }, [])

  // 绑定拖拽事件到整个输入区域
  useEffect(() => {
    const el = dropZoneRef.current
    if (!el) return

    el.addEventListener('dragover', handleDragOver)
    el.addEventListener('dragleave', handleDragLeave)
    el.addEventListener('drop', handleDrop)

    return () => {
      el.removeEventListener('dragover', handleDragOver)
      el.removeEventListener('dragleave', handleDragLeave)
      el.removeEventListener('drop', handleDrop)
    }
  }, [handleDragOver, handleDragLeave, handleDrop])

  // 添加文件（去重 + 限制大小 20MB）
  const addFiles = (newFiles) => {
    setFiles((prev) => {
      const merged = [...prev]
      for (const f of newFiles) {
        if (f.size > 20 * 1024 * 1024) {
          alert(`文件 "${f.name}" 超过 20MB 限制，已跳过`)
          continue
        }
        if (prev.some((p) => p.name === f.name && p.size === f.size)) continue
        merged.push(f)
      }
      return merged.slice(0, 10) // 最多 10 个文件
    })
  }

  // 点击"添加文件"按钮
  const handleFileClick = () => {
    fileInputRef.current?.click()
  }

  // 文件选择回调
  const handleFileChange = (e) => {
    const selected = Array.from(e.target.files || [])
    if (selected.length > 0) {
      addFiles(selected)
    }
    e.target.value = '' // 允许重复选择同一文件
  }

  // 移除某个文件
  const removeFile = (idx) => {
    setFiles((prev) => prev.filter((_, i) => i !== idx))
  }

  // 发送消息
  const handleSend = () => {
    if ((!input.trim() && files.length === 0) || inputDisabled) return
    sendMessage(input.trim(), files, dispatch, ACTIONS)
    setInput('')
    setFiles([])
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div
      ref={dropZoneRef}
      className={`input-bar ${dragOver ? 'drag-over' : ''}`}
    >
      {/* 拖拽覆盖层 */}
      {dragOver && (
        <div className="drop-overlay">
          <div className="drop-overlay-inner">
            <div className="drop-icon">⬆️</div>
            <div className="drop-text">释放文件到此处</div>
            <div className="drop-hint">支持图片 / 音频 / PDF</div>
          </div>
        </div>
      )}

      {/* 已选文件预览 */}
      {files.length > 0 && (
        <div className="file-preview-area">
          {files.map((file, idx) => (
            <FileTag key={`${file.name}-${idx}`} file={file} onRemove={() => removeFile(idx)} />
          ))}
        </div>
      )}

      <div className="input-row">
        {/* 模型选择器 */}
        <div className="input-model-selector" onClick={() => setModelOpen(!modelOpen)}>
          {selectedModel} <span style={{ fontSize: '9px' }}>▾</span>
          {modelOpen && (
            <div className="model-dropdown">
              {MODELS.map((m) => (
                <div
                  key={m}
                  className="model-option"
                  onClick={(e) => {
                    e.stopPropagation()
                    setSelectedModel(m)
                    setModelOpen(false)
                  }}
                >
                  {m}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 添加文件按钮 */}
        <button className="file-add-btn" onClick={handleFileClick} title="添加文件">
          ＋
        </button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".png,.jpg,.jpeg,.webp,.tiff,.tif,.mp3,.wav,.ogg,.m4a,.mp4,.pdf,image/*,audio/*,video/*,application/pdf"
          style={{ display: 'none' }}
          onChange={handleFileChange}
        />

        <textarea
          ref={textareaRef}
          className="input-field"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="输入消息，或拖拽文件到此处..."
          rows={1}
          disabled={inputDisabled}
        />

        <button
          className="send-btn"
          onClick={handleSend}
          disabled={(!input.trim() && files.length === 0) || inputDisabled}
        >
          ↗
        </button>
      </div>

      {/* 样式 */}
      <style>{`
        .input-bar {
          position: relative;
          padding: 12px 16px 16px;
          background: var(--surface-1);
          border-top: 1px solid var(--border);
        }
        .input-bar.drag-over {
          background: rgba(99, 102, 241, 0.04);
          border-top-color: var(--accent);
        }

        /* 拖拽覆盖层 */
        .drop-overlay {
          position: absolute;
          inset: 0;
          z-index: 100;
          background: rgba(6, 6, 16, 0.85);
          backdrop-filter: blur(8px);
          display: flex;
          align-items: center;
          justify-content: center;
          border: 2px dashed var(--accent);
          border-radius: 12px;
          margin: 8px;
          animation: fadeIn 0.15s ease;
        }
        @keyframes fadeIn {
          from { opacity: 0; }
          to   { opacity: 1; }
        }
        .drop-overlay-inner {
          text-align: center;
        }
        .drop-icon {
          font-size: 36px;
          margin-bottom: 8px;
          animation: bounceUp 1s ease infinite;
        }
        @keyframes bounceUp {
          0%, 100% { transform: translateY(0); }
          50%      { transform: translateY(-8px); }
        }
        .drop-text {
          font-size: 16px;
          font-weight: 600;
          color: var(--text-primary);
          margin-bottom: 4px;
        }
        .drop-hint {
          font-size: 12px;
          color: var(--text-muted);
        }

        /* 文件预览区 */
        .file-preview-area {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
          padding: 8px 0;
          max-height: 120px;
          overflow-y: auto;
        }

        /* 模型选择器 */
        .input-model-selector {
          position: relative;
          cursor: pointer;
          font-size: 11px;
          color: var(--text-muted);
          padding: 4px 8px;
          border-radius: 6px;
          background: rgba(255,255,255,0.04);
          user-select: none;
          white-space: nowrap;
          flex-shrink: 0;
        }
        .model-dropdown {
          position: absolute;
          bottom: 100%;
          left: 0;
          margin-bottom: 4px;
          background: var(--surface-2);
          border: 1px solid var(--border);
          border-radius: 8px;
          padding: 4px;
          min-width: 140px;
          z-index: 100;
        }
        .model-option {
          padding: 6px 10px;
          font-size: 11px;
          color: var(--text-secondary);
          border-radius: 6px;
          cursor: pointer;
        }
        .model-option:hover {
          background: var(--surface-hover);
          color: var(--text-primary);
        }

        /* 添加文件按钮 */
        .file-add-btn {
          background: transparent;
          border: 1px dashed var(--border);
          color: var(--text-muted);
          font-size: 18px;
          width: 32px;
          height: 32px;
          border-radius: 8px;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
          transition: all 0.15s ease;
        }
        .file-add-btn:hover {
          border-color: var(--accent);
          color: var(--accent);
          background: rgba(99, 102, 241, 0.08);
        }

        /* 输入框 */
        .input-field {
          flex: 1;
          background: transparent;
          border: none;
          outline: none;
          color: var(--text-primary);
          font-size: 13px;
          font-family: inherit;
          line-height: 1.5;
          resize: none;
          padding: 6px 4px;
          min-width: 0;
        }
        .input-field::placeholder {
          color: var(--text-muted);
        }
        .input-field:disabled {
          opacity: 0.5;
        }

        /* 发送按钮 */
        .send-btn {
          background: var(--accent);
          color: white;
          border: none;
          width: 32px;
          height: 32px;
          border-radius: 8px;
          font-size: 16px;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
          transition: all 0.15s ease;
        }
        .send-btn:hover:not(:disabled) {
          background: var(--accent-hover);
          transform: scale(1.05);
        }
        .send-btn:disabled {
          opacity: 0.3;
          cursor: not-allowed;
          transform: none;
        }

        .input-row {
          display: flex;
          align-items: flex-end;
          gap: 8px;
        }
      `}</style>
    </div>
  )
}

/* 单个文件标签组件 */
function FileTag({ file, onRemove }) {
  const [preview, setPreview] = useState(null)

  // 图片类型显示缩略图
  useEffect(() => {
    if (file.type.startsWith('image/')) {
      const url = URL.createObjectURL(file)
      setPreview(url)
      return () => URL.revokeObjectURL(url)
    }
  }, [file])

  const ext = file.name.includes('.') ? file.name.split('.').pop().toLowerCase() : ''
  const isImage = file.type.startsWith('image/')
  const isAudio = file.type.startsWith('audio/')
  const isPDF = file.type === 'application/pdf'

  const icon = isImage ? '🖼️' : isAudio ? '🎵' : isPDF ? '📄' : '📎'

  return (
    <div className="file-tag">
      {/* 图片缩略图预览 */}
      {preview ? (
        <img src={preview} alt="" className="file-thumb" />
      ) : (
        <span className="file-icon">{icon}</span>
      )}
      <span className="file-name" title={file.name}>
        {file.name.length > 18 ? file.name.slice(0, 18) + '...' : file.name}
      </span>
      <span className="file-size">{formatSize(file.size)}</span>
      <button className="file-remove" onClick={onRemove} title="移除">✕</button>

      <style>{`
        .file-tag {
          display: flex;
          align-items: center;
          gap: 6px;
          background: var(--surface-2);
          border: 1px solid var(--border);
          border-radius: 8px;
          padding: 4px 8px 4px 6px;
          font-size: 11px;
          max-width: 200px;
          animation: tagIn 0.2s ease;
        }
        @keyframes tagIn {
          from { opacity: 0; transform: scale(0.9); }
          to   { opacity: 1; transform: scale(1); }
        }
        .file-thumb {
          width: 28px;
          height: 28px;
          object-fit: cover;
          border-radius: 4px;
          flex-shrink: 0;
        }
        .file-icon {
          font-size: 16px;
          flex-shrink: 0;
        }
        .file-name {
          color: var(--text-secondary);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .file-size {
          color: var(--text-muted);
          font-size: 10px;
          flex-shrink: 0;
        }
        .file-remove {
          background: transparent;
          border: none;
          color: var(--text-muted);
          cursor: pointer;
          font-size: 12px;
          padding: 0 2px;
          flex-shrink: 0;
          line-height: 1;
        }
        .file-remove:hover {
          color: #ef4444;
        }
      `}</style>
    </div>
  )
}

function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

export default InputBar
