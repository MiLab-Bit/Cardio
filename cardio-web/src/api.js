// Cardio 前端 API 客户端（含 SSE 流式解析）

export function getApiBase() {
  const override = localStorage.getItem('cardio_api_base')
  if (override && override.trim()) return override.trim().replace(/\/$/, '')
  return (import.meta.env.VITE_API_BASE || 'https://www.abc-ai.cn/cardio').replace(/\/$/, '')
}

export function setApiBase(url) {
  if (url && url.trim()) localStorage.setItem('cardio_api_base', url.trim().replace(/\/$/, ''))
  else localStorage.removeItem('cardio_api_base')
}

// 带超时的 fetch：后端长时间无响应时主动中断，避免 UI 无限转圈。
async function fetchWithTimeout(url, opts = {}, timeout = 120000) {
  const ctrl = new AbortController()
  const id = setTimeout(() => ctrl.abort(), timeout)
  try {
    return await fetch(url, { ...opts, signal: ctrl.signal })
  } finally {
    clearTimeout(id)
  }
}

async function parseSSE(resp, onEvent) {
  if (!resp.ok) {
    let msg = `HTTP ${resp.status}`
    try {
      const j = await resp.json()
      msg = j?.error?.message || msg
    } catch {}
    throw new Error(msg)
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx
    while ((idx = buf.indexOf('\n\n')) !== -1) {
      const raw = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      for (const line of raw.split('\n')) {
        const t = line.trim()
        if (!t.startsWith('data:')) continue
        const payload = t.slice(5).trim()
        if (!payload || payload === '[DONE]') continue
        try {
          onEvent(JSON.parse(payload))
        } catch {}
      }
    }
  }
}

// 商枢对话：流式返回文本片段，通过 onToken 回调
export async function chatStream(message, history, onToken, onDone) {
  const base = getApiBase()
  const resp = await fetchWithTimeout(`${base}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, history }),
  }, 120000)
  let full = ''
  await parseSSE(resp, (ev) => {
    if (ev.type === 'token') {
      full += ev.text
      onToken?.(ev.text, full)
    } else if (ev.type === 'done') {
      onDone?.(full)
    } else if (ev.type === 'error') {
      throw new Error(ev.error || '对话出错')
    }
  })
  return full
}

// 五段式分析：流式返回阶段事件，通过 onEvent 回调。
// opts.image 为名片图片（data URL 或裸 base64），可选。
export async function analyzeStream(text, onEvent, opts = {}) {
  const base = getApiBase()
  const body = { text: text || '' }
  if (opts.image) {
    body.image = opts.image
    if (opts.image_format) body.image_format = opts.image_format
  }
  const resp = await fetchWithTimeout(`${base}/api/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }, 300000)
  await parseSSE(resp, (ev) => onEvent?.(ev))
  return true
}

// 名片识别：传入图片，返回结构化名片 JSON
export async function scanCard(image, image_format = 'jpeg') {
  const base = getApiBase()
  const body = { image }
  if (image_format) body.image_format = image_format
  const r = await fetchWithTimeout(`${base}/api/card/scan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }, 60000)
  if (!r.ok) {
    let msg = `HTTP ${r.status}`
    try { const j = await r.json(); msg = j?.error?.message || j?.error || msg } catch {}
    throw new Error(msg)
  }
  const j = await r.json()
  return j.card || {}
}

export async function getContacts() {
  const base = getApiBase()
  const r = await fetchWithTimeout(`${base}/api/contacts`, {}, 30000)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  const j = await r.json()
  return j.contacts || []
}

export async function saveContact(c) {
  const base = getApiBase()
  const r = await fetchWithTimeout(`${base}/api/contacts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(c),
  }, 30000)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return (await r.json()).contact
}

export async function getHistory() {
  const base = getApiBase()
  const r = await fetchWithTimeout(`${base}/api/history`, {}, 30000)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  const j = await r.json()
  return j.records || []
}
