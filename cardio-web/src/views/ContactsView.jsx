// 商册名录：联系人网格 + 新增/编辑/删除
import { useCallback, useEffect, useState } from 'react'
import { Plus, Loader2, Search, Pencil, Trash2, X, Save, Users } from 'lucide-react'
import { getContacts, saveContact, updateContact, deleteContact, AuthError } from '../api.js'
import EmptyState from '../components/EmptyState.jsx'

const EMPTY_FORM = { name: '', title: '', company: '', phone: '', email: '', tags: '' }

export default function ContactsView({ onAnalyzeContact }) {
  const [contacts, setContacts] = useState([])
  const [loading, setLoading] = useState(true)
  const [q, setQ] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState(null) // 正在编辑的联系人 id
  const [form, setForm] = useState(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try { setContacts(await getContacts()) } catch (e) {
      if (e instanceof AuthError) return
      setContacts([])
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  function openAdd() {
    setEditing(null); setForm(EMPTY_FORM); setError(''); setShowForm(true)
  }

  function openEdit(c) {
    setEditing(c.id)
    setForm({
      name: c.name || '', title: c.title || '', company: c.company || '',
      phone: c.phone || '', email: c.email || '', tags: (c.tags || []).join(', '),
    })
    setError(''); setShowForm(true)
  }

  async function submit() {
    if (!form.name.trim()) { setError('请填写姓名'); return }
    setSaving(true); setError('')
    const payload = {
      ...form,
      tags: form.tags.split(/[,，\s]+/).filter(Boolean),
    }
    try {
      if (editing) await updateContact(editing, payload)
      else await saveContact(payload)
      setShowForm(false)
      await load()
    } catch (e) {
      if (e instanceof AuthError) return
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  async function remove(c) {
    if (!window.confirm(`确定删除「${c.name || '未命名'}」的名片吗？`)) return
    try {
      await deleteContact(c.id)
      await load()
    } catch (e) {
      if (e instanceof AuthError) return
      setError(e.message)
    }
  }

  const filtered = q.trim()
    ? contacts.filter((c) =>
        [c.name, c.company, c.title, c.email, c.phone, (c.tags || []).join(' ')]
          .filter(Boolean).some((v) => v.toLowerCase().includes(q.trim().toLowerCase())))
    : contacts

  return (
    <div className="h-full overflow-y-auto px-4 md:px-5 py-5">
      <div className="max-w-4xl mx-auto">
        {/* 头部工具栏 */}
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <h2 className="font-serif text-xl font-bold text-ink flex items-center gap-2">
            商册名录
            <span className="text-[12px] font-normal text-ink-soft/60">共 {contacts.length} 张</span>
          </h2>
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-brass/60" />
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="搜索姓名 / 公司 / 标签"
                className="w-44 rounded-lg border border-brass/30 bg-white/80 pl-8 pr-3 py-1.5 text-sm outline-none focus:border-brass focus:ring-2 focus:ring-brass/15 transition"
              />
            </div>
            <button
              onClick={openAdd}
              className="px-3 py-1.5 rounded-lg bg-brass text-white text-sm flex items-center gap-1 shadow-card hover:bg-brass-deep active:scale-95 transition"
            >
              <Plus size={14} /> 新增名片
            </button>
          </div>
        </div>

        {/* 新增/编辑表单 */}
        {showForm && (
          <div className="paper rounded-2xl border border-brass/25 bg-white/60 p-4 mb-4 shadow-card animate-[fadeIn_.25s_ease]">
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-serif font-bold text-ink">{editing ? '编辑名片' : '新增名片'}</h3>
              <button onClick={() => setShowForm(false)} className="text-ink-soft/60 hover:text-ink" aria-label="关闭">
                <X size={16} />
              </button>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {[['name', '姓名*'], ['title', '职位'], ['company', '公司'], ['phone', '电话'], ['email', '邮箱'], ['tags', '标签(逗号分隔)']].map(([k, label]) => (
                <input
                  key={k}
                  value={form[k]}
                  onChange={(e) => setForm((f) => ({ ...f, [k]: e.target.value }))}
                  placeholder={label}
                  className="rounded-lg border border-brass/30 bg-white/80 px-3 py-2 text-sm outline-none focus:border-brass focus:ring-2 focus:ring-brass/15 transition"
                />
              ))}
            </div>
            {error && <div className="mt-2 text-[12px] text-cinnabar">⚠️ {error}</div>}
            <div className="mt-3 flex justify-end gap-2">
              <button onClick={() => setShowForm(false)} className="px-3 py-1.5 rounded-lg border border-brass/30 text-sm hover:bg-brass/10 transition">取消</button>
              <button
                onClick={submit}
                disabled={saving}
                className="px-4 py-1.5 rounded-lg bg-brass text-white text-sm flex items-center gap-1 hover:bg-brass-deep active:scale-95 transition disabled:opacity-50"
              >
                {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />} 保存
              </button>
            </div>
          </div>
        )}

        {/* 列表 */}
        {loading ? (
          <div className="text-ink-soft/70 text-sm flex items-center gap-2 py-10 justify-center">
            <Loader2 size={16} className="animate-spin" /> 加载中…
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            icon="book"
            title={contacts.length === 0 ? '商册还是空的' : '没有匹配的名片'}
            desc={contacts.length === 0
              ? '去「数字商册分析」上传一张名片，或手动新增第一张名片吧。'
              : '换个关键词试试，或清空搜索框查看全部。'}
            action={contacts.length === 0 && (
              <button onClick={openAdd} className="px-4 py-2 rounded-xl bg-brass text-white text-sm flex items-center gap-1 shadow-card hover:bg-brass-deep active:scale-95 transition">
                <Plus size={14} /> 新增名片
              </button>
            )}
          />
        ) : (
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {filtered.map((c) => (
              <div
                key={c.id}
                className="paper rounded-2xl border border-brass/20 bg-white/70 p-4 shadow-card hover:shadow-lg hover:-translate-y-0.5 transition-all duration-200 group"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="w-9 h-9 rounded-full bg-brass/15 text-brass-deep flex items-center justify-center font-bold text-sm shrink-0">
                    {(c.name || '?').slice(0, 1).toUpperCase()}
                  </div>
                  <div className="flex gap-0.5 opacity-0 group-hover:opacity-100 transition">
                    <button onClick={() => openEdit(c)} className="p-1.5 rounded-lg text-ink-soft/60 hover:bg-brass/10 hover:text-ink transition" title="编辑">
                      <Pencil size={13} />
                    </button>
                    <button onClick={() => remove(c)} className="p-1.5 rounded-lg text-ink-soft/60 hover:bg-cinnabar/10 hover:text-cinnabar transition" title="删除">
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>
                <div className="mt-2.5 font-serif font-bold text-ink">{c.name || '未命名'}</div>
                <div className="text-sm text-ink-soft">{c.title}{c.company ? ` · ${c.company}` : ''}</div>
                {(c.phone || c.email) && (
                  <div className="text-[12px] text-ink-soft/70 mt-1 break-all">{c.phone}{c.email ? ` · ${c.email}` : ''}</div>
                )}
                {c.tags?.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {c.tags.map((t, i) => (
                      <span key={i} className="px-2 py-0.5 rounded-full bg-brass/15 text-brass-deep text-[11px]">{t}</span>
                    ))}
                  </div>
                )}
                {onAnalyzeContact && (
                  <button
                    onClick={() => onAnalyzeContact(c)}
                    className="mt-3 w-full py-1.5 rounded-lg border border-brass/25 text-[12px] text-brass-deep hover:bg-brass/10 active:scale-[0.98] transition"
                  >
                    <Users size={11} className="inline mr-1" />研判这位客户
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
