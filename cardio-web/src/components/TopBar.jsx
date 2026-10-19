// 顶栏：当前视图标题 + 后端地址 + 移动端菜单按钮
import { Menu, Server } from 'lucide-react'
import { NAV } from '../constants.js'
import {
  Compass, ScanSearch, Users, History, Settings, Boxes,
} from 'lucide-react'

const ICONS = { Compass, ScanSearch, Users, History, Settings, Boxes }

export default function TopBar({ view, apiBase, onOpenMobile }) {
  const cur = NAV.find((n) => n.key === view)
  const Icon = cur ? (ICONS[cur.icon] || Compass) : Compass
  return (
    <header className="h-14 shrink-0 px-4 md:px-5 flex items-center justify-between border-b border-brass/20 bg-parchment/60 backdrop-blur paper">
      <div className="flex items-center gap-2 min-w-0">
        <button
          className="md:hidden mr-1 p-1.5 -ml-1 rounded-lg text-ink-soft hover:bg-brass/10 active:scale-95 transition"
          onClick={onOpenMobile}
          aria-label="打开菜单"
        >
          <Menu size={20} />
        </button>
        <span className="text-brass">{<Icon size={18} />}</span>
        <h1 className="font-serif text-lg font-bold text-ink truncate">{cur?.label || 'Card.io'}</h1>
        {cur?.desc && <span className="hidden lg:inline text-[12px] text-ink-soft/60 truncate">· {cur.desc}</span>}
      </div>
      <div className="flex items-center gap-2 text-[11px] text-ink-soft shrink-0">
        <Server size={13} />
        <span className="font-mono truncate max-w-[140px] md:max-w-[260px]">{apiBase || '同源 /api'}</span>
      </div>
    </header>
  )
}
