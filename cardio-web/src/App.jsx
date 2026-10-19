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
import { getApiBase, getToken, getCurrentUser, saveSession, clearSession, AUTH_EXPIRED_EVENT } from './api.js'

export default function App() {
  const [authed, setAuthed] = useState(() => !!getToken())
  const [user, setUser] = useState(getCurrentUser())
  const [view, setView] = useState('chat')
  const [apiBase, setApiBaseState] = useState(getApiBase())
  const [mobileOpen, setMobileOpen] = useState(false)

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
