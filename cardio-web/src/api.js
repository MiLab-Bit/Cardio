// Cardio 前端 API 客户端：token 管理 + 全量端点 + SSE 流式解析

const TOKEN_KEY = 'cardio_token'
const USER_KEY = 'cardio_user'

/* ── 后端地址：默认同源相对路径（nginx 已将 /api/ 反代至 :8010） ── */
export function getApiBase() {
  const override = localStorage.getItem('cardio_api_base')
  if (override && override.trim()) return override.trim().replace(/\/$/, '')
  return '' // 同源：https://cardio.sy-realm.ltd
}

export function setApiBase(url) {
  if (url && url.trim()) localStorage.setItem('cardio_api_base', url.trim().replace(/\/$/, ''))
  else localStorage.removeItem('cardio_api_base')
}

/* ── 会话：JWT token + 当前用户 ── */
export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function getCurrentUser() {
  try { return JSON.parse(localStorage.getItem(USER_KEY) || 'null') } catch { return null }
}

export function saveSession(token, user) {
  localStorage.setItem(TOKEN_KEY, token)
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

// 401 时跨组件通知登出（App 层监听）
export const AUTH_EXPIRED_EVENT = 'cardio:auth-expired'
function notifyExpired() {
  window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT))
}

/* ── 带超时 + 自动带 Authorization 的 fetch ── */
async function fetchWithTimeout(url, opts = {}, timeout = 120000) {
  const token = getToken()
  const headers = { ...(opts.headers || {}) }
  if (token) headers['Authorization'] = `Bearer ${token}`
  const ctrl = new AbortController()
  const id = setTimeout(() => ctrl.abort(), timeout)
  try {
    const resp = await fetch(url, { ...opts, headers, signal: ctrl.signal })
    if (resp.status === 401) {
      // token 失效/过期：清理会话并通知上层跳登录页
      const clone = resp.clone()
      let payload = null
      try { payload = await clone.json() } catch { /* ignore */ }
      // 登录/注册接口自身的 401（密码错误）不触发登出
      if (!url.includes('/api/auth/')) {
        clearSession()
        notifyExpired()
      }
      if (payload) {
        const msg = payload?.error?.message || payload?.detail?.message || '未授权'
        throw new AuthError(msg, 401)
      }
      throw new AuthError('未授权', 401)
    }
    return resp
  } finally {
    clearTimeout(id)
  }
}

export class AuthError extends Error {
  constructor(message, status = 401) {
    super(message)
    this.name = 'AuthError'
    this.status = status
  }
}

/* ── 错误信息提取（后端 error 结构不统一，尽量取到人话） ── */
async function errorMessage(resp, fallback) {
  try {
    const j = await resp.json()
    return j?.error?.message || j?.detail?.message || j?.message || j?.error || fallback
  } catch {
    return fallback || `HTTP ${resp.status}`
  }
}

/* ── SSE 解析 ── */
async function parseSSE(resp, onEvent) {
  if (!resp.ok) throw new Error(await errorMessage(resp))
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
        try { onEvent(JSON.parse(payload)) } catch { /* ignore */ }
      }
    }
  }
}

/* ── 认证 ── */
export async function register(email, password, name) {
  const base = getApiBase()
  const r = await fetchWithTimeout(`${base}/api/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password, name }),
  }, 30000)
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(j?.error?.message || j?.detail?.message || '注册失败')
  return j // { status, token?, user?, auto_verified?, requires_verification? }
}

export async function login(email, password) {
  const base = getApiBase()
  const r = await fetchWithTimeout(`${base}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  }, 30000)
  const j = await r.json().catch(() => ({}))
  if (!r.ok) {
    const err = new Error(j?.error?.message || j?.detail?.message || '登录失败')
    err.status = r.status
    err.requiresVerification = !!(j?.detail?.requires_verification || j?.requires_verification)
    throw err
  }
  return j // { status, token, user }
}

export async function resendVerification(email) {
  const base = getApiBase()
  const r = await fetchWithTimeout(`${base}/api/auth/resend-verification`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  }, 30000)
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(j?.error?.message || '发送失败')
  return j
}

export async function verifyEmail(token) {
  const base = getApiBase()
  const r = await fetchWithTimeout(`${base}/api/auth/verify-email?token=${encodeURIComponent(token)}`, {}, 30000)
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(j?.error?.message || j?.detail?.message || '验证失败')
  return j // { status, token, user }
}

/* ── 商枢对话（SSE） ── */
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

/* ── 五段式分析（SSE，支持名片图片） ── */
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
  }, 900000) // 五段管线最耗时可到数分钟，放宽至 15 分钟
  await parseSSE(resp, (ev) => onEvent?.(ev))
  return true
}

/* ── 名片识别 ── */
export async function scanCard(image, image_format = 'jpeg') {
  const base = getApiBase()
  const r = await fetchWithTimeout(`${base}/api/card/scan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ image, image_format }),
  }, 120000)
  if (!r.ok) throw new Error(await errorMessage(r))
  const j = await r.json()
  return j.card || {}
}

/* ── 数字商册（联系人） ── */
export async function getContacts() {
  const base = getApiBase()
  const r = await fetchWithTimeout(`${base}/api/contacts`, {}, 30000)
  if (!r.ok) throw new Error(await errorMessage(r))
  return (await r.json()).contacts || []
}

export async function saveContact(c) {
  const base = getApiBase()
  const r = await fetchWithTimeout(`${base}/api/contacts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(c),
  }, 30000)
  if (!r.ok) throw new Error(await errorMessage(r))
  return (await r.json()).contact
}

export async function updateContact(id, c) {
  const base = getApiBase()
  const r = await fetchWithTimeout(`${base}/api/contacts/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(c),
  }, 30000)
  if (!r.ok) throw new Error(await errorMessage(r))
  return (await r.json()).contact
}

export async function deleteContact(id) {
  const base = getApiBase()
  const r = await fetchWithTimeout(`${base}/api/contacts/${id}`, { method: 'DELETE' }, 30000)
  if (!r.ok) throw new Error(await errorMessage(r))
  return true
}

/* ── 历史分析 ── */
export async function getHistory(contactId) {
  const base = getApiBase()
  const q = contactId ? `?contact_id=${encodeURIComponent(contactId)}` : ''
  const r = await fetchWithTimeout(`${base}/api/history${q}`, {}, 30000)
  if (!r.ok) throw new Error(await errorMessage(r))
  return (await r.json()).records || []
}

/* ── 模型 Provider（用户自带大模型，双槽位） ── */
export async function getProviderPresets() {
  const base = getApiBase()
  const r = await fetchWithTimeout(`${base}/api/model-providers/presets`, {}, 30000)
  if (!r.ok) throw new Error(await errorMessage(r))
  return (await r.json()).providers || []
}

export async function listProviders() {
  const base = getApiBase()
  const r = await fetchWithTimeout(`${base}/api/model-providers`, {}, 30000)
  if (!r.ok) throw new Error(await errorMessage(r))
  return (await r.json()).providers || []
}

export async function createProvider({ name, provider, apiKey, baseUrl, model, slot }) {
  const base = getApiBase()
  const r = await fetchWithTimeout(`${base}/api/model-providers`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, provider, apiKey, baseUrl, model, slot }),
  }, 30000)
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(j?.error?.message || j?.detail?.message || '保存失败')
  return j
}

export async function testProvider({ provider, apiKey, baseUrl, model }) {
  const base = getApiBase()
  const r = await fetchWithTimeout(`${base}/api/model-providers/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider, apiKey, baseUrl, model }),
  }, 60000)
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(j?.error?.message || j?.detail?.message || '测试失败')
  return j
}

export async function deleteProvider(id) {
  const base = getApiBase()
  const r = await fetchWithTimeout(`${base}/api/model-providers/${id}`, { method: 'DELETE' }, 30000)
  if (!r.ok) throw new Error(await errorMessage(r))
  return true
}

/* ── Agent API Key ── */
export async function listApiKeys() {
  const base = getApiBase()
  const r = await fetchWithTimeout(`${base}/api/apikeys`, {}, 30000)
  if (!r.ok) throw new Error(await errorMessage(r))
  return (await r.json()).keys || []
}

export async function createApiKey(name, scopes) {
  const base = getApiBase()
  const r = await fetchWithTimeout(`${base}/api/apikeys`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, scopes }),
  }, 30000)
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(j?.error?.message || '创建失败')
  return j
}

export async function revokeApiKey(id) {
  const base = getApiBase()
  const r = await fetchWithTimeout(`${base}/api/apikeys/revoke`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key_id: id }),
  }, 30000)
  if (!r.ok) throw new Error(await errorMessage(r))
  return true
}
