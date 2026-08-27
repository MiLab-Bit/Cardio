import React, { useEffect, useRef, useState } from 'react'
import {
  Compass, ScanSearch, Users, History, Settings, Send, Loader2, Sparkles,
  Save, Plus, Server, CheckCircle2, Circle, BookOpen, Globe, ImageUp,
} from 'lucide-react'
import {
  getApiBase, setApiBase as persistApiBase, chatStream, analyzeStream, scanCard, getContacts, saveContact, getHistory,
} from './api.js'

const NAV = [
  { key: 'chat', label: '商枢对话', icon: Compass, desc: '随时问、随手记' },
  { key: 'analyze', label: '数字商册分析', icon: ScanSearch, desc: '名片/会议 → 五段研判' },
  { key: 'contacts', label: '商册名录', icon: Users, desc: '你的人脉库' },
  { key: 'history', label: '历史研判', icon: History, desc: '过往分析记录' },
  { key: 'settings', label: '设置', icon: Settings, desc: '后端地址等' },
]

const STAGE_ORDER = [
  { key: 'extraction', label: '信息提取', agent: '提取官', icon: '🪪' },
  { key: 'research', label: '背景调研', agent: '调研员', icon: '🔭' },
  { key: 'synthesis', label: '画像合成', agent: '画像师', icon: '🧭' },
  { key: 'strategy', label: 'BD 策略', agent: '谋士', icon: '♟️' },
  { key: 'critique', label: '风险审核', agent: '审官', icon: '🛡️' },
]

export default function App() {
  const [view, setView] = useState('chat')
  const [apiBase, setApiBaseState] = useState(getApiBase())

  function handleSetBase(v) {
    persistApiBase(v)
    setApiBaseState(v)
  }

  return (
    <div className="flex h-full">
      <Sidebar view={view} setView={setView} />
      <main className="flex-1 min-w-0 flex flex-col">
        <TopBar view={view} apiBase={apiBase} />
        <div className="flex-1 min-h-0 overflow-hidden">
          {view === 'chat' && <ChatView apiBase={apiBase} />}
          {view === 'analyze' && <AnalyzeView apiBase={apiBase} />}
          {view === 'contacts' && <ContactsView apiBase={apiBase} />}
          {view === 'history' && <HistoryView apiBase={apiBase} />}
          {view === 'settings' && <SettingsView apiBase={apiBase} setApiBase={handleSetBase} />}
        </div>
      </main>
    </div>
  )
}

/* ── 侧边栏 ── */
function Sidebar({ view, setView }) {
  return (
    <aside className="w-60 shrink-0 bg-ink text-parchment flex flex-col">
      <div className="p-5 flex items-center gap-3 border-b border-white/10">
        <img src="/logo-cardio.jpg" alt="Card.io" className="w-10 h-10 rounded-lg object-cover shadow" />
        <div>
          <div className="font-serif text-xl font-bold tracking-wide">Card.io</div>
          <div className="text-[11px] text-brass/80">新时代的数字商册</div>
        </div>
      </div>
      <nav className="flex-1 p-3 space-y-1">
        {NAV.map((n) => {
          const Icon = n.icon
          const active = view === n.key
          return (
            <button
              key={n.key}
              onClick={() => setView(n.key)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-left transition ${
                active ? 'bg-brass/20 text-parchment' : 'text-parchment/70 hover:bg-white/5'
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
      <div className="p-4 text-[11px] text-parchment/40 border-t border-white/10">
        商枢为你记录每一次相遇，连接天下商缘。
      </div>
    </aside>
  )
}

/* ── 顶栏 ── */
function TopBar({ view, apiBase }) {
  const cur = NAV.find((n) => n.key === view)
  return (
    <header className="h-14 shrink-0 px-5 flex items-center justify-between border-b border-brass/20 bg-parchment/60 backdrop-blur paper">
      <div className="flex items-center gap-2">
        <span className="text-brass">{cur?.icon && React.createElement(cur.icon, { size: 18 })}</span>
        <h1 className="font-serif text-lg font-bold text-ink">{cur?.label}</h1>
      </div>
      <div className="flex items-center gap-2 text-[11px] text-ink-soft">
        <Server size={13} />
        <span className="font-mono truncate max-w-[260px]">{apiBase}</span>
      </div>
    </header>
  )
}

/* ── 商枢对话 ── */
function ChatView() {
  const [msgs, setMsgs] = useState([
    { role: 'assistant', content: '我是商枢，你的数字商册助手。把客户或会议信息告诉我，我帮你记下来，也能用「数字商册分析」做深度研判。' },
  ])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState('')
  const [busy, setBusy] = useState(false)
  const scrollRef = useRef(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [msgs, streaming])

  async function send() {
    const text = input.trim()
    if (!text || busy) return
    setInput('')
    setBusy(true)
    const history = msgs.map((m) => ({ role: m.role, content: m.content }))
    setMsgs((m) => [...m, { role: 'user', content: text }])
    setStreaming('')
    try {
      await chatStream(
        text,
        history,
        (tok) => setStreaming((s) => s + tok),
        (full) => {
          setMsgs((m) => [...m, { role: 'assistant', content: full }])
          setStreaming('')
        },
      )
    } catch (e) {
      setMsgs((m) => [...m, { role: 'assistant', content: '⚠️ ' + e.message }])
      setStreaming('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="h-full flex flex-col">
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-5 py-5 space-y-4">
        {msgs.map((m, i) => (
          <Bubble key={i} role={m.role} content={m.content} />
        ))}
        {streaming && <Bubble role="assistant" content={streaming} streaming />}
      </div>
      <div className="p-4 border-t border-brass/20 bg-parchment/50">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
            rows={2}
            placeholder="和商枢说点什么…（Enter 发送，Shift+Enter 换行）"
            className="flex-1 resize-none rounded-xl border border-brass/30 bg-white/70 px-3 py-2 text-sm text-ink outline-none focus:border-brass"
          />
          <button
            onClick={send}
            disabled={busy}
            className="h-10 px-4 rounded-xl bg-brass text-white font-medium flex items-center gap-1 disabled:opacity-50"
          >
            {busy ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
            发送
          </button>
        </div>
      </div>
    </div>
  )
}

function Bubble({ role, content, streaming }) {
  const isUser = role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[80%] px-4 py-2.5 rounded-2xl text-sm leading-relaxed shadow-card ${
        isUser ? 'bg-brass text-white rounded-br-sm' : 'bg-white/80 text-ink rounded-bl-sm'
      }`}>
        {content}
        {streaming && <span className="cursor-blink" />}
      </div>
    </div>
  )
}

/* ── 数字商册分析 ── */
function AnalyzeView() {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [stages, setStages] = useState({})
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)

  // 名片图片相关
  const [image, setImage] = useState('')
  const [imageName, setImageName] = useState('')
  const [scanning, setScanning] = useState(false)
  const [card, setCard] = useState(null)
  const [cardError, setCardError] = useState('')
  const [cardSaved, setCardSaved] = useState(false)
  const fileRef = useRef(null)

  function onPickImage(e) {
    const f = e.target.files?.[0]
    if (!f) return
    const reader = new FileReader()
    reader.onload = () => {
      setImage(reader.result)
      setImageName(f.name)
      setCard(null); setCardError(''); setCardSaved(false)
    }
    reader.readAsDataURL(f)
  }

  async function doScan() {
    if (!image || scanning) return
    setScanning(true); setCardError(''); setCard(null); setCardSaved(false)
    try {
      const c = await scanCard(image, imageName.endsWith('.png') ? 'png' : 'jpeg')
      setCard(c)
    } catch (e) {
      setCardError(e.message)
    } finally {
      setScanning(false)
    }
  }

  async function saveScanned() {
    if (!card) return
    try {
      await saveContact({
        name: card.name, title: card.title, company: card.company,
        phone: card.mobile || card.phone, email: card.email,
        tags: card.tags || [],
      })
      setCardSaved(true)
    } catch (e) {
      setCardError('保存失败：' + e.message)
    }
  }

  async function run() {
    if (busy) return
    if (!text.trim() && !image) { setError('请填写文字或上传名片图片'); return }
    setBusy(true); setStages({}); setResult(null); setError(''); setSaved(false)
    try {
      await analyzeStream(text.trim(), (ev) => {
        if (ev.type === 'vision_start') {
          setStages((s) => ({ ...s, _vision: { status: 'start' } }))
        } else if (ev.type === 'vision_done') {
          setStages((s) => ({ ...s, _vision: { status: 'done', card: ev.card } }))
          setCard(ev.card)
        } else if (ev.type === 'vision_error') {
          setStages((s) => ({ ...s, _vision: { status: 'error', error: ev.error } }))
        } else if (ev.type === 'stage_start') {
          setStages((s) => ({ ...s, [ev.stage]: { status: 'start' } }))
        } else if (ev.type === 'stage_done') {
          setStages((s) => ({ ...s, [ev.stage]: { status: 'done', report: ev.report } }))
        } else if (ev.type === 'complete') {
          setResult(ev.result)
        } else if (ev.type === 'error') {
          setError(ev.error || '分析出错')
        }
      }, { image: image || undefined, image_format: imageName.endsWith('.png') ? 'png' : 'jpeg' })
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function saveToBook() {
    if (!result?.profile) return
    try {
      await saveContact(result.profile)
      setSaved(true)
    } catch (e) {
      setError('保存失败：' + e.message)
    }
  }

  return (
    <div className="h-full overflow-y-auto px-5 py-5">
      <div className="max-w-3xl mx-auto space-y-5">
        <div className="paper rounded-2xl border border-brass/25 bg-white/60 p-4 shadow-card">
          <label className="text-sm font-medium text-ink-soft">输入客户 / 会议信息，或上传名片照片</label>

          {/* 名片图片上传 */}
          <div className="mt-2 flex items-center gap-3">
            <div
              onClick={() => fileRef.current?.click()}
              className="relative w-28 h-20 rounded-xl border-2 border-dashed border-brass/40 bg-white/60 flex flex-col items-center justify-center cursor-pointer hover:border-brass text-brass/70"
            >
              {image ? (
                <img src={image} alt="名片" className="w-full h-full object-cover rounded-xl" />
              ) : (
                <>
                  <ImageUp size={20} />
                  <span className="text-[11px] mt-1">上传名片</span>
                </>
              )}
            </div>
            <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={onPickImage} />
            <div className="flex-1 min-w-0">
              <div className="text-[12px] text-ink-soft/70 leading-relaxed">
                拍一张名片，商枢用多模态视觉模型自动识别姓名、职位、公司、电话、邮箱等，
                可「仅识别」存入商册，或「带图分析」做五段研判。
              </div>
              <div className="mt-2 flex gap-2">
                <button
                  onClick={doScan}
                  disabled={!image || scanning}
                  className="px-3 py-1.5 rounded-lg bg-ink text-parchment text-sm flex items-center gap-1 disabled:opacity-50"
                >
                  {scanning ? <Loader2 size={14} className="animate-spin" /> : <ScanSearch size={14} />}
                  {scanning ? '识别中…' : '仅识别'}
                </button>
                {image && (
                  <button onClick={() => { setImage(''); setImageName(''); setCard(null); setCardError('') }}
                    className="px-3 py-1.5 rounded-lg border border-brass/30 text-sm">清除</button>
                )}
              </div>
            </div>
          </div>

          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={4}
            placeholder="也可在此粘贴名片文字或会议记录…（例如：客户王明，环球科技 CEO，想找跨境供应链方案，关注成本和交期。）"
            className="mt-3 w-full resize-y rounded-xl border border-brass/30 bg-white/80 px-3 py-2 text-sm text-ink outline-none focus:border-brass"
          />
          <div className="mt-3 flex items-center justify-between">
            <span className="text-[11px] text-ink-soft/70">五段式研判：提取 → 调研 → 画像 → 策略 → 审核</span>
            <button
              onClick={run}
              disabled={busy || (!text.trim() && !image)}
              className="px-5 py-2 rounded-xl bg-brass text-white font-medium flex items-center gap-1.5 disabled:opacity-50"
            >
              {busy ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
              {busy ? '研判中…' : '开始分析'}
            </button>
          </div>
        </div>

        {cardError && (
          <div className="rounded-xl border border-cinnabar/40 bg-cinnabar/10 px-4 py-3 text-sm text-cinnabar">
            ⚠️ {cardError}
          </div>
        )}

        {/* 仅识别结果 */}
        {card && !scanning && (
          <div className="paper rounded-2xl border border-brass/30 bg-white/70 p-4 shadow-card">
            <div className="flex items-center justify-between mb-3">
              <div className="font-serif text-lg font-bold text-ink flex items-center gap-2">
                <ScanSearch size={18} className="text-brass" /> 名片识别结果
              </div>
              <button
                onClick={saveScanned}
                disabled={cardSaved}
                className="px-3 py-1.5 rounded-lg text-sm bg-brass text-white flex items-center gap-1 disabled:opacity-60"
              >
                <Save size={14} /> {cardSaved ? '已存入商册' : '存入商册'}
              </button>
            </div>
            <ProfileCard profile={card} />
          </div>
        )}

        {error && (
          <div className="rounded-xl border border-cinnabar/40 bg-cinnabar/10 px-4 py-3 text-sm text-cinnabar">
            ⚠️ {error}
          </div>
        )}

        {/* 名片识别阶段（带图分析时） */}
        {stages._vision && stages._vision.status !== 'done' && (
          <div className={`rounded-2xl border p-4 ${
            stages._vision.status === 'error' ? 'border-cinnabar/40 bg-cinnabar/5' : 'border-brass/40 bg-brass/5'
          }`}>
            <div className="flex items-center gap-3">
              <div className="text-2xl">📷</div>
              <div className="flex-1">
                <div className="font-medium text-ink">名片识别</div>
                <div className="text-[11px] text-ink-soft/70">视觉模型 · {stages._vision.status === 'start' ? '识别中…' : '识别失败'}</div>
              </div>
              {stages._vision.status === 'start' ? (
                <Loader2 size={18} className="text-brass animate-spin" />
              ) : stages._vision.status === 'error' ? (
                <span className="text-[12px] text-cinnabar">{stages._vision.error}</span>
              ) : null}
            </div>
          </div>
        )}

        {STAGE_ORDER.map((st) => (
          <StageCard key={st.key} meta={st} state={stages[st.key]} />
        ))}

        {result && (
          <div className="paper rounded-2xl border border-jade/30 bg-white/70 p-4 shadow-card">
            <div className="flex items-center justify-between mb-3">
              <div className="font-serif text-lg font-bold text-ink flex items-center gap-2">
                <BookOpen size={18} className="text-jade" /> 商册档案
              </div>
              <button
                onClick={saveToBook}
                disabled={saved}
                className="px-3 py-1.5 rounded-lg text-sm bg-jade text-white flex items-center gap-1 disabled:opacity-60"
              >
                <Save size={14} /> {saved ? '已存入商册' : '存入商册'}
              </button>
            </div>
            <ProfileCard profile={result.profile} />
          </div>
        )}
      </div>
    </div>
  )
}

function StageCard({ meta, state }) {
  const done = state?.status === 'done'
  const start = state?.status === 'start'
  return (
    <div className={`rounded-2xl border p-4 transition ${
      done ? 'border-jade/40 bg-jade/5' : start ? 'border-brass/40 bg-brass/5' : 'border-brass/15 bg-white/40'
    }`}>
      <div className="flex items-center gap-3">
        <div className="text-2xl">{meta.icon}</div>
        <div className="flex-1">
          <div className="font-medium text-ink">{meta.label}</div>
          <div className="text-[11px] text-ink-soft/70">{meta.agent}</div>
        </div>
        {done ? (
          <CheckCircle2 size={20} className="text-jade" />
        ) : start ? (
          <Loader2 size={18} className="text-brass animate-spin" />
        ) : (
          <Circle size={18} className="text-brass/30" />
        )}
      </div>
      {done && state.report && (
        <div className="mt-3 text-sm text-ink-soft leading-relaxed">
          <div className="text-ink">{state.report.summary}</div>
          <div className="mt-2 text-[12px] text-ink-soft/70">
            置信度：{Math.round((state.report.confidence || 0) * 100)}%
          </div>
        </div>
      )}
    </div>
  )
}

function ProfileCard({ profile }) {
  if (!profile) return null
  const rows = [
    ['姓名', profile.name], ['职位', profile.title], ['公司', profile.company],
    ['行业', profile.industry], ['电话', profile.phone], ['邮箱', profile.email],
  ]
  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="flex gap-2">
          <span className="text-ink-soft/70 w-10 shrink-0">{k}</span>
          <span className="text-ink font-medium break-all">{v || '—'}</span>
        </div>
      ))}
      {profile.needs?.length > 0 && (
        <div className="col-span-2 flex gap-2">
          <span className="text-ink-soft/70 w-10 shrink-0">需求</span>
          <span className="flex flex-wrap gap-1">
            {profile.needs.map((n, i) => (
              <span key={i} className="px-2 py-0.5 rounded-full bg-brass/15 text-brass-deep text-[12px]">{n}</span>
            ))}
          </span>
        </div>
      )}
    </div>
  )
}

/* ── 商册名录 ── */
function ContactsView() {
  const [contacts, setContacts] = useState([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ name: '', title: '', company: '', phone: '', email: '', tags: '' })

  async function load() {
    setLoading(true)
    try { setContacts(await getContacts()) } catch (e) { setContacts([]) } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  async function add() {
    if (!form.name.trim()) return
    const c = { ...form, tags: form.tags.split(/[,，\s]+/).filter(Boolean) }
    try { await saveContact(c); setForm({ name: '', title: '', company: '', phone: '', email: '', tags: '' }); setShowForm(false); await load() } catch (e) { alert('保存失败：' + e.message) }
  }

  return (
    <div className="h-full overflow-y-auto px-5 py-5">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-serif text-xl font-bold text-ink">商册名录</h2>
          <button onClick={() => setShowForm((s) => !s)} className="px-3 py-1.5 rounded-lg bg-brass text-white text-sm flex items-center gap-1">
            <Plus size={14} /> 新增名片
          </button>
        </div>
        {showForm && (
          <div className="paper rounded-2xl border border-brass/25 bg-white/60 p-4 mb-4 shadow-card grid grid-cols-2 gap-3">
            {[['name', '姓名*'], ['title', '职位'], ['company', '公司'], ['phone', '电话'], ['email', '邮箱'], ['tags', '标签(逗号分隔)']].map(([k, label]) => (
              <input
                key={k}
                value={form[k]}
                onChange={(e) => setForm((f) => ({ ...f, [k]: e.target.value }))}
                placeholder={label}
                className="rounded-lg border border-brass/30 bg-white/80 px-3 py-2 text-sm outline-none focus:border-brass"
              />
            ))}
            <div className="col-span-2 flex justify-end gap-2">
              <button onClick={() => setShowForm(false)} className="px-3 py-1.5 rounded-lg border border-brass/30 text-sm">取消</button>
              <button onClick={add} className="px-3 py-1.5 rounded-lg bg-brass text-white text-sm">保存</button>
            </div>
          </div>
        )}
        {loading ? (
          <div className="text-ink-soft/70 text-sm flex items-center gap-2"><Loader2 size={16} className="animate-spin" /> 加载中…</div>
        ) : contacts.length === 0 ? (
          <div className="text-ink-soft/70 text-sm">还没有名片，去「数字商册分析」或上方新增一张吧。</div>
        ) : (
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {contacts.map((c) => (
              <div key={c.id} className="paper rounded-2xl border border-brass/20 bg-white/70 p-4 shadow-card">
                <div className="font-serif font-bold text-ink">{c.name || '未命名'}</div>
                <div className="text-sm text-ink-soft">{c.title}{c.company ? ` · ${c.company}` : ''}</div>
                <div className="text-[12px] text-ink-soft/70 mt-1">{c.phone}{c.email ? ` · ${c.email}` : ''}</div>
                <div className="mt-2 flex flex-wrap gap-1">
                  {(c.tags || []).map((t, i) => (
                    <span key={i} className="px-2 py-0.5 rounded-full bg-brass/15 text-brass-deep text-[11px]">{t}</span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

/* ── 历史研判 ── */
function HistoryView() {
  const [records, setRecords] = useState([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(null)

  async function load() {
    setLoading(true)
    try { setRecords(await getHistory()) } catch { setRecords([]) } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  return (
    <div className="h-full overflow-y-auto px-5 py-5">
      <div className="max-w-3xl mx-auto">
        <h2 className="font-serif text-xl font-bold text-ink mb-4">历史研判</h2>
        {loading ? (
          <div className="text-ink-soft/70 text-sm flex items-center gap-2"><Loader2 size={16} className="animate-spin" /> 加载中…</div>
        ) : records.length === 0 ? (
          <div className="text-ink-soft/70 text-sm">暂无记录。</div>
        ) : (
          <div className="space-y-3">
            {records.map((r) => (
              <div key={r.id} className="paper rounded-2xl border border-brass/20 bg-white/70 p-4 shadow-card">
                <button className="w-full text-left" onClick={() => setOpen(open === r.id ? null : r.id)}>
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-ink line-clamp-1">{r.input_text}</span>
                    <span className="text-[11px] text-ink-soft/60">{new Date(r.created_at).toLocaleString()}</span>
                  </div>
                </button>
                {open === r.id && (
                  <div className="mt-3 space-y-2">
                    {STAGE_ORDER.map((st) => {
                      const rep = r.result?.agent_reports?.[st.key]
                      if (!rep) return null
                      return (
                        <div key={st.key} className="rounded-lg border border-brass/15 bg-white/60 p-3">
                          <div className="text-sm font-medium text-ink">{st.icon} {rep.label}</div>
                          <div className="text-[13px] text-ink-soft mt-1">{rep.summary}</div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

/* ── 设置 ── */
function SettingsView({ apiBase, setApiBase }) {
  const [val, setVal] = useState(apiBase)
  const [ok, setOk] = useState(false)
  function save() {
    setApiBase(val)
    setOk(true)
    setTimeout(() => setOk(false), 1500)
  }
  return (
    <div className="h-full overflow-y-auto px-5 py-5">
      <div className="max-w-2xl mx-auto space-y-5">
        <div className="paper rounded-2xl border border-brass/25 bg-white/60 p-5 shadow-card">
          <div className="flex items-center gap-2 text-ink mb-1">
            <Globe size={18} className="text-brass" />
            <h3 className="font-serif text-lg font-bold">后端服务地址</h3>
          </div>
          <p className="text-[12px] text-ink-soft/70 mb-3">
            前端通过此地址调用 Cardio 后端（部署在服务器上）。后端上线后填入，例如 https://www.abc-ai.cn/cardio
          </p>
          <div className="flex gap-2">
            <input
              value={val}
              onChange={(e) => setVal(e.target.value)}
              className="flex-1 rounded-lg border border-brass/30 bg-white/80 px-3 py-2 text-sm font-mono outline-none focus:border-brass"
            />
            <button onClick={save} className="px-4 py-2 rounded-lg bg-brass text-white text-sm">保存</button>
          </div>
          {ok && <div className="mt-2 text-[12px] text-jade">已保存，将在下次请求时生效。</div>}
        </div>
        <div className="text-[12px] text-ink-soft/70 leading-relaxed">
          Card.io · 新时代的数字商册。从丝路驼铃到现代商途，行商以名帖记人，以商路通天下。商枢为你记录每一次相遇，连接天下商缘。
        </div>
      </div>
    </div>
  )
}
