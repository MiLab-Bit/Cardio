// 侧边栏：桌面常驻 / 移动端抽屉
import {
  Compass, ScanSearch, Users, History, Settings, Boxes, LogOut, X, ShieldCheck,
} from 'lucide-react'
import { NAV } from '../constants.js'

const ICONS = { Compass, ScanSearch, Users, History, Settings, Boxes }

export default function Sidebar({ view, setView, user, onLogout, mobileOpen, onCloseMobile }) {
  return (
    <>
      {/* 移动端遮罩 */}
      {mobileOpen && (
        <div
          className="fixed inset-0 bg-ink/40 z-30 md:hidden animate-[fadeIn_.15s_ease]"
          onClick={onCloseMobile}
        />
      )}
      <aside
        className={`fixed md:static z-40 md:z-auto inset-y-0 left-0 w-64 shrink-0 bg-ink text-parchment flex flex-col
          transform transition-transform duration-200 md:transform-none
          ${mobileOpen ? 'translate-x-0' : '-translate-x-full'}`}
      >
        {/* 品牌区 */}
        <div className="p-5 flex items-center gap-3 border-b border-white/10">
          <img src="/logo-cardio.jpg" alt="Card.io" className="w-10 h-10 rounded-lg object-cover shadow" />
          <div className="min-w-0 flex-1">
            <div className="font-serif text-xl font-bold tracking-wide">Card.io</div>
            <div className="text-[11px] text-brass/80">新时代的数字商册</div>
          </div>
          <button className="md:hidden text-parchment/60 hover:text-parchment" onClick={onCloseMobile} aria-label="关闭菜单">
            <X size={18} />
          </button>
        </div>

        {/* 导航 */}
        <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
          {NAV.map((n) => {
            const Icon = ICONS[n.icon] || Compass
            const active = view === n.key
            return (
              <button
                key={n.key}
                onClick={() => { setView(n.key); onCloseMobile?.() }}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-left transition-all duration-150
                  active:scale-[0.98] ${
                  active
                    ? 'bg-brass/20 text-parchment shadow-[inset_2px_0_0_0_#b08d57]'
                    : 'text-parchment/70 hover:bg-white/5 hover:text-parchment'
                }`}
              >
                <Icon size={18} className={active ? 'text-brass' : ''} />
                <div className="min-w-0">
                  <div className="text-sm font-medium leading-tight">{n.label}</div>
                  <div className="text-[11px] text-parchment/40 truncate">{n.desc}</div>
                </div>
              </button>
            )
          })}
        </nav>

        {/* 用户区 */}
        <div className="p-3 border-t border-white/10 space-y-2">
          {user && (
            <div className="flex items-center gap-2 px-2 py-1.5">
              <div className="w-8 h-8 rounded-full bg-brass/25 text-brass flex items-center justify-center text-sm font-bold shrink-0">
                {(user.name || user.email || '?').slice(0, 1).toUpperCase()}
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-[13px] text-parchment truncate">{user.name || '未命名'}</div>
                <div className="text-[11px] text-parchment/40 truncate">{user.email}</div>
              </div>
            </div>
          )}
          <div className="flex items-center gap-1.5 px-2 text-[10px] text-jade/80">
            <ShieldCheck size={12} />
            <span>端到端 JWT 鉴权已启用</span>
          </div>
          <button
            onClick={onLogout}
            className="w-full flex items-center gap-2 px-3 py-2 rounded-xl text-[13px] text-parchment/70
              hover:bg-cinnabar/20 hover:text-parchment transition active:scale-[0.98]"
          >
            <LogOut size={15} /> 退出登录
          </button>
        </div>

        <div className="px-4 pb-3 text-[11px] text-parchment/40 leading-relaxed">
          商枢为你记录每一次相遇，连接天下商缘。
        </div>
      </aside>
    </>
  )
}
