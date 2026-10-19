// 设置：后端地址 + 账号信息 + 退出
import { useState } from 'react'
import { Globe, CheckCircle2, LogOut, Info, KeyRound, Copy } from 'lucide-react'
import { getApiBase, setApiBase, listApiKeys, createApiKey, revokeApiKey, AuthError } from '../api.js'

export default function SettingsView({ user, onLogout }) {
  const [val, setVal] = useState(getApiBase())
  const [ok, setOk] = useState(false)

  // Agent API Key
  const [keys, setKeys] = useState([])
  const [newKey, setNewKey] = useState(null) // 创建后仅展示一次
  const [keyBusy, setKeyBusy] = useState(false)

  function save() {
    setApiBase(val)
    setOk(true)
    setTimeout(() => setOk(false), 1500)
  }

  async function loadKeys() {
    try { setKeys(await listApiKeys()) } catch (e) {
      if (e instanceof AuthError) return
    }
  }

  async function addKey() {
    setKeyBusy(true)
    try {
      const j = await createApiKey('web-' + new Date().toISOString().slice(0, 10), ['*'])
      setNewKey(j.key)
      await loadKeys()
    } catch (e) {
      if (e instanceof AuthError) return
      alert('创建失败：' + e.message)
    } finally {
      setKeyBusy(false)
    }
  }

  return (
    <div className="h-full overflow-y-auto px-4 md:px-5 py-5">
      <div className="max-w-2xl mx-auto space-y-5">
        {/* 账号 */}
        <div className="paper rounded-2xl border border-brass/25 bg-white/60 p-5 shadow-card">
          <h3 className="font-serif text-lg font-bold text-ink mb-3">当前账号</h3>
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-full bg-brass/25 text-brass-deep flex items-center justify-center text-lg font-bold">
              {(user?.name || user?.email || '?').slice(0, 1).toUpperCase()}
            </div>
            <div className="min-w-0">
              <div className="font-medium text-ink">{user?.name || '未命名'}</div>
              <div className="text-[12px] text-ink-soft/70 truncate">{user?.email}</div>
            </div>
          </div>
          <button
            onClick={onLogout}
            className="mt-4 px-3 py-1.5 rounded-lg border border-cinnabar/30 text-cinnabar text-sm flex items-center gap-1 hover:bg-cinnabar/10 active:scale-95 transition"
          >
            <LogOut size={14} /> 退出登录
          </button>
        </div>

        {/* 后端地址 */}
        <div className="paper rounded-2xl border border-brass/25 bg-white/60 p-5 shadow-card">
          <div className="flex items-center gap-2 text-ink mb-1">
            <Globe size={18} className="text-brass" />
            <h3 className="font-serif text-lg font-bold">后端服务地址</h3>
          </div>
          <p className="text-[12px] text-ink-soft/70 mb-3 leading-relaxed">
            默认走同源相对路径（<span className="font-mono">https://cardio.sy-realm.ltd</span> 的 <span className="font-mono">/api/</span>）。
            仅在本地开发或后端迁移时需要填写完整地址，例如 <span className="font-mono">http://127.0.0.1:8010</span>；留空恢复默认。
          </p>
          <div className="flex gap-2">
            <input
              value={val}
              onChange={(e) => setVal(e.target.value)}
              placeholder="留空 = 同源 /api"
              className="flex-1 rounded-lg border border-brass/30 bg-white/80 px-3 py-2 text-sm font-mono outline-none focus:border-brass focus:ring-2 focus:ring-brass/15 transition"
            />
            <button onClick={save} className="px-4 py-2 rounded-lg bg-brass text-white text-sm hover:bg-brass-deep active:scale-95 transition">保存</button>
          </div>
          {ok && (
            <div className="mt-2 text-[12px] text-jade flex items-center gap-1 animate-[fadeIn_.2s_ease]">
              <CheckCircle2 size={12} /> 已保存，将在下次请求时生效。
            </div>
          )}
        </div>

        {/* Agent API Key */}
        <div className="paper rounded-2xl border border-brass/25 bg-white/60 p-5 shadow-card">
          <div className="flex items-center gap-2 text-ink mb-1">
            <KeyRound size={18} className="text-brass" />
            <h3 className="font-serif text-lg font-bold">Agent API Key</h3>
          </div>
          <p className="text-[12px] text-ink-soft/70 mb-3 leading-relaxed">
            供外部 Agent / 脚本以 <span className="font-mono">Authorization: Bearer cd_…</span> 调用 Cardio API。
            明文仅创建时显示一次。
          </p>
          {newKey && (
            <div className="mb-3 rounded-xl border border-jade/40 bg-jade/10 p-3 text-[13px] animate-[fadeIn_.25s_ease]">
              <div className="text-jade font-medium mb-1">新 Key 已创建，请立即保存：</div>
              <div className="flex items-center gap-2">
                <code className="flex-1 font-mono text-ink bg-white/70 rounded-lg px-2 py-1 break-all">{newKey}</code>
                <button
                  onClick={() => navigator.clipboard?.writeText(newKey)}
                  className="p-1.5 rounded-lg text-jade hover:bg-jade/10 transition"
                  title="复制"
                >
                  <Copy size={14} />
                </button>
              </div>
            </div>
          )}
          <button
            onClick={keys.length ? loadKeys : addKey}
            className="px-3 py-1.5 rounded-lg border border-brass/30 text-sm hover:bg-brass/10 active:scale-95 transition disabled:opacity-50"
            disabled={keyBusy}
          >
            {keyBusy ? '创建中…' : '创建 API Key'}
          </button>
          {keys.length > 0 && (
            <div className="mt-3 space-y-2">
              {keys.map((k) => (
                <div key={k.id} className="flex items-center gap-2 rounded-xl border border-brass/15 bg-white/60 px-3 py-2">
                  <div className="flex-1 min-w-0">
                    <div className="text-[13px] text-ink">{k.name}</div>
                    <div className="text-[11px] text-ink-soft/60 font-mono">
                      {k.key_preview || k.prefix + '****'} · {k.status}
                      {k.last_used_at ? ` · 最近使用 ${new Date(k.last_used_at).toLocaleDateString()}` : ''}
                    </div>
                  </div>
                  {k.status === 'active' && (
                    <button
                      onClick={async () => { await revokeApiKey(k.id); loadKeys() }}
                      className="text-[12px] text-cinnabar hover:underline"
                    >
                      吊销
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 关于 */}
        <div className="text-[12px] text-ink-soft/70 leading-relaxed flex items-start gap-2 px-1">
          <Info size={13} className="mt-0.5 shrink-0" />
          <span>
            Card.io · 新时代的数字商册。从丝路驼铃到现代商途，行商以名帖记人，以商路通天下。
            商枢为你记录每一次相遇，连接天下商缘。
          </span>
        </div>
      </div>
    </div>
  )
}
