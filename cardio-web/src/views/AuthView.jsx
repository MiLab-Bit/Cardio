// 认证页：品牌扉页 + 登录/注册双面板
import { useState } from 'react'
import { Compass, Loader2, Mail, Lock, User as UserIcon, ArrowRight, Sparkles } from 'lucide-react'
import { register, login } from '../api.js'

export default function AuthView({ onAuthed }) {
  const [mode, setMode] = useState('login') // login | register
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  async function submit(e) {
    e.preventDefault()
    if (busy) return
    setError(''); setNotice('')
    if (!email.trim() || !password) { setError('请填写邮箱和密码'); return }
    setBusy(true)
    try {
      if (mode === 'register') {
        const j = await register(email.trim(), password, name.trim())
        if (j.token) {
          onAuthed(j.token, j.user) // auto-verify 模式：直接登录
        } else {
          setNotice(j.message || '注册成功，请查收验证邮件后登录。')
          setMode('login')
        }
      } else {
        const j = await login(email.trim(), password)
        onAuthed(j.token, j.user)
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="h-full flex flex-col md:flex-row animate-[fadeIn_.4s_ease]">
      {/* 左：品牌扉页 */}
      <div className="hidden md:flex flex-1 bg-ink text-parchment flex-col justify-between p-10 relative overflow-hidden">
        {/* 背景装饰光斑 */}
        <div className="absolute -top-24 -right-24 w-96 h-96 rounded-full bg-brass/10 blur-3xl" />
        <div className="absolute -bottom-32 -left-20 w-80 h-80 rounded-full bg-jade/10 blur-3xl" />

        <div className="relative flex items-center gap-3">
          <img src="/logo-cardio.jpg" alt="Card.io" className="w-12 h-12 rounded-xl object-cover shadow-lg" />
          <div>
            <div className="font-serif text-2xl font-bold tracking-wide">Card.io</div>
            <div className="text-[12px] text-brass/80">新时代的数字商册</div>
          </div>
        </div>

        <div className="relative max-w-md">
          <h2 className="font-serif text-3xl font-bold leading-snug mb-4">
            从丝路驼铃<br />到现代商途
          </h2>
          <p className="text-parchment/70 text-sm leading-relaxed mb-8">
            行商以名帖记人，以商路通天下。商枢为你记录每一次相遇，
            把一张名片、一次会面，沉淀成可研判的商册档案。
          </p>
          <div className="space-y-3">
            {[
              ['🪪', '名片一拍即识别', '多模态视觉模型，自动结构化姓名、职位、公司'],
              ['🔭', '五段式深度研判', '提取 → 调研 → 画像 → 策略 → 审核'],
              ['📖', '数字商册沉淀', '人脉库与历史研判，随时回看'],
            ].map(([icon, title, desc]) => (
              <div key={title} className="flex items-start gap-3">
                <span className="text-lg mt-0.5">{icon}</span>
                <div>
                  <div className="text-sm font-medium text-parchment">{title}</div>
                  <div className="text-[12px] text-parchment/50">{desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="relative text-[11px] text-parchment/40">
          Cardio · 连接天下商缘
        </div>
      </div>

      {/* 右：表单 */}
      <div className="flex-1 flex items-center justify-center p-6 overflow-y-auto">
        <div className="w-full max-w-sm">
          {/* 移动端品牌头 */}
          <div className="md:hidden flex items-center gap-2.5 mb-8">
            <img src="/logo-cardio.jpg" alt="Card.io" className="w-10 h-10 rounded-lg object-cover shadow" />
            <div>
              <div className="font-serif text-xl font-bold text-ink">Card.io</div>
              <div className="text-[11px] text-brass">新时代的数字商册</div>
            </div>
          </div>

          {/* 模式切换 */}
          <div className="flex bg-parchment-deep/60 rounded-xl p-1 mb-6">
            {[['login', '登录'], ['register', '注册']].map(([key, label]) => (
              <button
                key={key}
                onClick={() => { setMode(key); setError(''); setNotice('') }}
                className={`flex-1 py-2 rounded-lg text-sm font-medium transition-all duration-150 ${
                  mode === key ? 'bg-white text-ink shadow-card' : 'text-ink-soft/70 hover:text-ink'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          <form onSubmit={submit} className="space-y-3.5">
            {mode === 'register' && (
              <label className="block">
                <span className="text-[12px] text-ink-soft/80 mb-1 block">称呼（选填）</span>
                <div className="relative">
                  <UserIcon size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-brass/70" />
                  <input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="怎么称呼你"
                    className="w-full rounded-xl border border-brass/30 bg-white/80 pl-9 pr-3 py-2.5 text-sm text-ink outline-none focus:border-brass focus:ring-2 focus:ring-brass/15 transition"
                  />
                </div>
              </label>
            )}

            <label className="block">
              <span className="text-[12px] text-ink-soft/80 mb-1 block">邮箱</span>
              <div className="relative">
                <Mail size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-brass/70" />
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  autoComplete="email"
                  className="w-full rounded-xl border border-brass/30 bg-white/80 pl-9 pr-3 py-2.5 text-sm text-ink outline-none focus:border-brass focus:ring-2 focus:ring-brass/15 transition"
                />
              </div>
            </label>

            <label className="block">
              <span className="text-[12px] text-ink-soft/80 mb-1 block">
                密码{mode === 'register' && <span className="text-ink-soft/50">（至少 6 位）</span>}
              </span>
              <div className="relative">
                <Lock size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-brass/70" />
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••"
                  autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                  className="w-full rounded-xl border border-brass/30 bg-white/80 pl-9 pr-3 py-2.5 text-sm text-ink outline-none focus:border-brass focus:ring-2 focus:ring-brass/15 transition"
                />
              </div>
            </label>

            {error && (
              <div className="rounded-xl border border-cinnabar/40 bg-cinnabar/10 px-3.5 py-2.5 text-[13px] text-cinnabar animate-[fadeIn_.2s_ease]">
                ⚠️ {error}
              </div>
            )}
            {notice && (
              <div className="rounded-xl border border-jade/40 bg-jade/10 px-3.5 py-2.5 text-[13px] text-jade animate-[fadeIn_.2s_ease]">
                ✉️ {notice}
              </div>
            )}

            <button
              type="submit"
              disabled={busy}
              className="w-full py-2.5 rounded-xl bg-brass text-white font-medium flex items-center justify-center gap-1.5
                shadow-card hover:bg-brass-deep active:scale-[0.98] transition disabled:opacity-50"
            >
              {busy ? <Loader2 size={16} className="animate-spin" />
                : mode === 'login' ? <><Compass size={16} /> 进入商册</>
                  : <><Sparkles size={16} /> 创建账号</>}
              {!busy && <ArrowRight size={15} />}
            </button>
          </form>

          <p className="mt-6 text-center text-[12px] text-ink-soft/60 leading-relaxed">
            {mode === 'login' ? '还没有账号？' : '已有账号？'}
            <button
              className="text-brass-deep font-medium hover:underline ml-1"
              onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(''); setNotice('') }}
            >
              {mode === 'login' ? '注册一个' : '去登录'}
            </button>
          </p>
        </div>
      </div>
    </div>
  )
}
