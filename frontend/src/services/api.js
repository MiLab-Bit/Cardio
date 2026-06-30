/**
 * SSE 聊天服务
 * 对接后端 /tool/invoke SSE 接口
 * 支持文件上传（转 base64）
 *
 * API 基础路径：
 *  - 开发模式（Vite proxy）：/tool/invoke
 *  - 生产模式（Electron 本地加载）：http://localhost:8000/tool/invoke
 */

// 智能判断 API 基础路径
// - Vite dev server 有 proxy → 用相对路径 ''
// - 静态服务器 / Electron / 生产构建 → 直接指向后端
function getApiBase() {
  // 开发模式：Vite dev server（端口 3000）有 proxy
  if (window.location.port === '3000') return ''
  // 其他情况：直连后端
  return 'http://127.0.0.1:8000'
}
const API_BASE = getApiBase()

let currentController = null

/**
 * 将 File 对象转成 base64 字符串（去掉 data:...;base64, 前缀）
 */
function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const dataUrl = reader.result          // "data:image/png;base64,iVBOR..."
      const base64 = dataUrl.split(',')[1]   // 只要纯 base64 部分
      resolve(base64)
    }
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

/**
 * 发送聊天请求（SSE 流式，支持文件）
 *
 * @param {string}   message  - 用户输入文本
 * @param {File[]}   files    - 选中的文件列表
 * @param {Function} dispatch - React dispatch
 * @param {object}   ACTIONS  - action types
 */
export async function sendMessage(message, files, dispatch, ACTIONS) {
  // 取消上一次请求
  if (currentController) {
    currentController.abort()
  }
  currentController = new AbortController()

  // ── 1. 处理文件：转 base64 ─────────────────────────────
  let cardImageBase64 = null
  let audioBase64 = null

  for (const file of files) {
    const base64 = await fileToBase64(file)
    if (file.type.startsWith('image/') && !cardImageBase64) {
      cardImageBase64 = base64
    } else if (file.type.startsWith('audio/') && !audioBase64) {
      audioBase64 = base64
    }
    // PDF / 视频等：后端暂不支持，跳过（可扩展）
  }

  // ── 2. 添加用户消息到 UI ─────────────────────────────
  const userMsg = {
    id: Date.now(),
    type: 'user',
    content: message,
    time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
    files: files.map(f => ({ name: f.name, size: f.size, type: f.type })),
  }
  dispatch({ type: ACTIONS.ADD_USER_MESSAGE, payload: userMsg })

  // ── 3. 添加 Agent 占位消息 ──────────────────────────
  const agentMsgId = Date.now() + 1
  dispatch({
    type: ACTIONS.ADD_AGENT_MESSAGE,
    payload: {
      id: agentMsgId,
      type: 'agent',
      agentName: 'Byou',
      tabs: ['提取', '研究', '分层', '策略', '审核'],
      activeTab: 0,
      reports: {},
      time: '',
    },
  })

  // ── 4. 设置加载状态 ─────────────────────────────────
  dispatch({ type: ACTIONS.SET_INPUT_DISABLED, payload: true })
  dispatch({ type: ACTIONS.SET_TYPING, payload: true })
  dispatch({
    type: ACTIONS.SET_AGENT_PROGRESS,
    payload: { agent: 'extract', status: 'active' },
  })

  // ── 5. 发起 SSE 请求 ───────────────────────────────
  try {
    const body = {
      function: 'analyze_customer',
      parameters: {
        input_text: message,
        pipeline: 'default',
      },
      stream: true,
      async_run: false,
    }

    if (cardImageBase64) body.parameters.card_image_base64 = cardImageBase64
    if (audioBase64)     body.parameters.audio_base64     = audioBase64

    const resp = await fetch(`${API_BASE}/tool/invoke`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Byou-Key': 'dev-key',
      },
      body: JSON.stringify(body),
      signal: currentController.signal,
    })

    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`)
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop()

      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed.startsWith('data:')) continue

        const dataStr = trimmed.slice(5).trim()
        if (dataStr === '[DONE]' || dataStr === '') continue

        try {
          const data = JSON.parse(dataStr)
          handleSSEEvent(data, agentMsgId, dispatch, ACTIONS)
        } catch {
          // 非 JSON，忽略
        }
      }
    }
  } catch (err) {
    if (err.name !== 'AbortError') {
      console.error('SSE error:', err)
    }
  } finally {
    dispatch({ type: ACTIONS.SET_INPUT_DISABLED, payload: false })
    dispatch({ type: ACTIONS.SET_TYPING, payload: false })
  }
}

/**
 * 处理后端 SSE 事件
 */
function handleSSEEvent(data, agentMsgId, dispatch, ACTIONS) {
  const { stage, result, error } = data

  if (error) {
    console.error('Pipeline error:', error)
    return
  }

  // 流水线完成
  if (stage === 'complete' && result) {
    dispatch({
      type: ACTIONS.SET_AGENT_MESSAGE_TIME,
      payload: {
        msgId: agentMsgId,
        time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
      },
    })

    if (result.agent_reports) {
      for (const [agent, reportData] of Object.entries(result.agent_reports)) {
        dispatch({
          type: ACTIONS.UPDATE_AGENT_REPORT,
          payload: { msgId: agentMsgId, agent, reportData },
        })
      }
    }

    for (const agent of ['extract', 'research', 'segment', 'strategy', 'critic']) {
      dispatch({
        type: ACTIONS.SET_AGENT_PROGRESS,
        payload: { agent, status: 'completed' },
      })
    }
    return
  }

  // 解析 stage 名称 — 映射后端实际发送的事件名到前端 agent key
  const stageMap = {
    extracting:       'extract',     // extractor_start
    extraction_done: 'extract',     // extractor_done
    researching:     'research',    // researcher_start
    research_done:   'research',    // researcher_done
    synthesizing:    'segment',     // synthesizer_start
    synthesis_done:  'segment',     // synthesizer_done
    strategizing:    'strategy',    // strategist_start
    strategy_done:   'strategy',    // strategist_done
    critiquing:      'critic',      // critic_start
    critique_done:   'critic',      // critic_done
  }

  const mapped = stageMap[stage]
  if (mapped) {
    const isDone = stage.endsWith('_done') || stage.endsWith('_complete')
    dispatch({
      type: ACTIONS.SET_AGENT_PROGRESS,
      payload: { agent: mapped, status: isDone ? 'completed' : 'active' },
    })

    if (isDone && data.data) {
      const reportData = formatAgentReport(mapped, data.data)
      dispatch({
        type: ACTIONS.UPDATE_AGENT_REPORT,
        payload: { msgId: agentMsgId, agent: mapped, reportData },
      })
    }
  }
}

/**
 * 格式化 Agent 报告
 */
function formatAgentReport(agentKey, data) {
  const titleMap = {
    extract: '信息提取报告',
    research: '背景研究报告',
    segment: '客户分层报告',
    strategy: '跟进策略报告',
    critic: '风险审核报告',
  }

  const fields = Object.entries(data).slice(0, 8).map(([k, v]) => ({
    label: k,
    value: String(v || '').slice(0, 100),
  }))

  return {
    title: titleMap[agentKey] || agentKey,
    fields,
    status: '完成',
    content: typeof data === 'string' ? data : null,
  }
}
