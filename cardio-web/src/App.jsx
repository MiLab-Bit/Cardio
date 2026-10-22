// App 外壳：会话守卫 + 布局 + 路由（RRv7 BrowserRouter，nginx 已配 SPA fallback）
import { useCallback, useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'
import Sidebar from './components/Sidebar.jsx'
import TopBar from './components/TopBar.jsx'
import AuthView from './views/AuthView.jsx'
import ChatView from './views/ChatView.jsx'
import AnalyzeView from './views/AnalyzeView.jsx'
import ContactsView from './views/ContactsView.jsx'
import HistoryView from './views/HistoryView.jsx'
import ProvidersView from './views/ProvidersView.jsx'
import SettingsView from './views/SettingsView.jsx'
import { NAV } from './constants.js'
import { getApiBase, getToken, getCurrentUser, saveSession, clearSession, AUTH_EXPIRED_EVENT } from './api.js'

const NAV_KEYS = new Set(NAV.map((n) => n.key))

/** 从 pathname 派生当前视图：'/contacts' → 'contacts'；未知路径回退 chat */
function viewFromPath(pathname) {
  const key = pathname.replace(/^\/+/, '').split('/')[0]
  return NAV_KEYS.has(key) ? key : 'analyze'
}

export default function App() {
  const [authed, setAuthed] = useState(() => !!getToken())
  const [user, setUser] = useState(getCurrentUser())
  const [apiBase, setApiBaseState] = useState(getApiBase())
  const [mobileOpen, setMobileOpen] = useState(false)

  const location = useLocation()
  const navigate = useNavigate()
  const view = viewFromPath(location.pathname)

  // setView 兼容层：视图组件仍以 key 调用，内部转为导航
  const setView = useCallback((key) => navigate('/' + key), [navigate])

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
    navigate('/', { replace: true })
  }, [navigate])

  const handleLogout = useCallback(() => {
    clearSession()
    setAuthed(false)
    setUser(null)
    navigate('/', { replace: true })
  }, [navigate])

  // 未登录：品牌扉页认证页（登录后回落到首页）
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
        <div key={location.pathname} className="flex-1 min-h-0 overflow-hidden animate-view-in">
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
