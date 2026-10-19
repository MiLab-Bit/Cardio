// App 外壳：会话守卫 + 布局 + 视图路由
import { useCallback, useEffect, useState } from 'react'
import Sidebar from './components/Sidebar.jsx'
import TopBar from './components/TopBar.jsx'
import AuthView from './views/AuthView.jsx'
import ChatView from './views/ChatView.jsx'
import AnalyzeView from './views/AnalyzeView.jsx'
import ContactsView from './views/ContactsView.jsx'
import HistoryView from './views/HistoryView.jsx'
import ProvidersView from './views/ProvidersView.jsx'
import SettingsView from './views/SettingsView.jsx'
import { getApiBase, getToken, getCurrentUser, saveSession, clearSession, AUTH_EXPIRED_EVENT, verifyEmail } from './api.js'

export default function App() {
  const [authed, setAuthed] = useState(() => !!getToken())
  const [user, setUser] = useState(getCurrentUser())
  const [view, setView] = useState('chat')
  const [apiBase, setApiBaseState] = useState(getApiBase())
  const [mobileOpen, setMobileOpen] = useState(false)

  // 邮箱验证链接落地页：/verify-email?token=...
  const [verifyLink] = useState(() => {
    if (typeof window === 'undefined' || window.location.pathname !== '/verify-email') return null
    const t = new URLSearchParams(window.location.search).get('token') || ''
    if (t) window.history.replaceState({}, '', '/')
    return { token: t }
  })
  const [verifyState, setVerifyState] = useState({ status: 'idle', message: '' })

  // token 失效（401）时自动登出
  useEffect(() => {
    function onExpired() {
      setAuthed(false)
      setUser(null)
    }
    window.addEventListener(AUTH_EXPIRED_EVENT, onExpired)
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, onExpired)
  }, [])

  const handleAuthed = useCallback((token, u) => {
    saveSession(token, u)
    setAuthed(true)
    setUser(u)
  }, [])

  const handleLogout = useCallback(() => {
    clearSession()
    setAuthed(false)
    setUser(null)
    setView('chat')
  }, [])

  // 验证链接：进入即尝试验证，成功直接登录
  useEffect(() => {
    if (!verifyLink) return
    if (!verifyLink.token) {
      setVerifyState({ status: 'error', message: '链接缺少验证参数，请重新发送验证邮件' })
      return
    }
    let cancelled = false
    setVerifyState({ status: 'verifying', message: '' })
    verifyEmail(verifyLink.token)
      .then((j) => {
        if (cancelled) return
        if (j.token) { handleAuthed(j.token, j.user); setVerifyState({ status: 'ok', message: '' }) }
        else setVerifyState({ status: 'error', message: j.message || '验证失败，请重新发送' })
      })
      .catch((e) => { if (!cancelled) setVerifyState({ status: 'error', message: e.message }) })
    return () => { cancelled = true }
  }, [verifyLink, handleAuthed])

  // 验证链接处理中 / 失败时全屏展示
  if (verifyLink && verifyState.status !== 'ok' && !authed) {
    return (
      <div className="h-full flex items-center justify-center p-6">
        <div className="w-full max-w-sm text-center">
          <img src="/logo-cardio.jpg" alt="Card.io" className="w-14 h-14 rounded-xl mx-auto mb-5 shadow-lg" />
          {verifyState.status === 'verifying' && (
            <p className="text-sm text-ink-soft">正在验证邮箱…</p>
          )}
          {verifyState.status === 'error' && (
            <>
              <p className="text-sm text-cinnabar mb-4">⚠️ {verifyState.message || '验证失败'}</p>
              <button
                onClick={() => window.location.replace('/')}
                className="px-4 py-2 rounded-xl bg-brass text-white text-sm font-medium hover:bg-brass-deep transition"
              >
                返回登录
              </button>
            </>
          )}
        </div>
      </div>
    )
  }

  // 未登录：品牌扉页认证页
  if (!authed) {
    return (
      <div className="h-full">
        <AuthView onAuthed={handleAuthed} />
      </div>
    )
  }

  return (
    <div className="flex h-full">
      <Sidebar
        view={view}
        setView={setView}
        user={user}
        onLogout={handleLogout}
        mobileOpen={mobileOpen}
        onCloseMobile={() => setMobileOpen(false)}
      />
      <main className="flex-1 min-w-0 flex flex-col">
        <TopBar view={view} apiBase={apiBase} onOpenMobile={() => setMobileOpen(true)} />
        <div key={view} className="flex-1 min-h-0 overflow-hidden animate-[viewIn_.25s_ease]">
          {view === 'chat' && <ChatView />}
          {view === 'analyze' && <AnalyzeView onGoContacts={() => setView('contacts')} />}
          {view === 'contacts' && (
            <ContactsView onAnalyzeContact={() => setView('analyze')} />
          )}
          {view === 'history' && <HistoryView />}
          {view === 'providers' && <ProvidersView />}
          {view === 'settings' && <SettingsView user={user} onLogout={handleLogout} />}
        </div>
      </main>
    </div>
  )
}
