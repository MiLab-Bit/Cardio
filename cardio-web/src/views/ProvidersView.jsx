// 模型配置：用户自带大模型 Provider（text / multimodal 双槽位）
import { useCallback, useEffect, useState } from 'react'
import {
  Loader2, Plus, Trash2, CheckCircle2, XCircle, KeyRound, Boxes, Zap, Eye,
} from 'lucide-react'
import {
  getProviderPresets, listProviders, createProvider, testProvider, deleteProvider, AuthError,
} from '../api.js'
import EmptyState from '../components/EmptyState.jsx'

const SLOTS = [
  { key: 'text', label: '文本模型', desc: '商枢对话与五段研判使用', icon: Zap },
  { key: 'multimodal', label: '多模态模型', desc: '名片图片识别使用', icon: Eye },
]

export default function ProvidersView() {
  const [presets, setPresets] = useState([])
  const [providers, setProviders] = useState([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ name: '', provider: 'deepseek', apiKey: '', baseUrl: '', model: '', slot: 'text' })
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [p, list] = await Promise.all([getProviderPresets(), listProviders()])
      setPresets(p)
      setProviders(list)
    } catch (e) {
      if (e instanceof AuthError) return
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  function pickPreset(provider) {
    const p = presets.find((x) => x.provider === provider)
    setForm((f) => ({
      ...f,
      provider,
      baseUrl: p?.baseUrl || '',
      model: p?.defaultModel || '',
      name: f.name || (p?.label || provider),
    }))
  }

  async function doTest() {
    if (!form.apiKey) { setTestResult({ ok: false, message: '请先填写 API Key' }); return }
    setTesting(true); setTestResult(null)
    try {
      const j = await testProvider(form)
      setTestResult({ ok: j.ok !== false && j.status !== 'error', message: j.message || j.reply || '连接正常' })
    } catch (e) {
      setTestResult({ ok: false, message: e.message })
    } finally {
      setTesting(false)
    }
  }

  async function submit() {
    if (!form.name.trim()) { setError('请填写配置名称'); return }
    if (!form.apiKey) { setError('请填写 API Key'); return }
    setSaving(true); setError('')
    try {
      await createProvider(form)
      setShowForm(false)
      setForm({ name: '', provider: 'deepseek', apiKey: '', baseUrl: '', model: '', slot: 'text' })
      setTestResult(null)
      await load()
    } catch (e) {
      if (e instanceof AuthError) return
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  async function remove(id) {
    if (!window.confirm('确定删除这条模型配置吗？')) return
    try {
      await deleteProvider(id)
      await load()
    } catch (e) {
      if (e instanceof AuthError) return
      setError(e.message)
    }
  }

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center text-ink-soft/70 text-sm gap-2">
        <Loader2 size={16} className="animate-spin" /> 加载中…
      </div>
    )
  }

  return (
    <div className="h-full overflow-y-auto px-4 md:px-5 py-5">
      <div className="max-w-3xl mx-auto space-y-5">
        {/* 说明 */}
        <div className="paper rounded-2xl border border-brass/25 bg-white/60 p-4 shadow-card">
          <div className="flex items-start gap-3">
            <div className="w-9 h-9 rounded-xl bg-brass/15 flex items-center justify-center shrink-0">
              <Boxes size={17} className="text-brass" />
            </div>
            <div className="text-[13px] text-ink-soft leading-relaxed">
              你可以自带大模型 Key：对话与分析会优先使用你配置的模型，未配置时回退平台默认网关。
              分两个槽位——<b className="text-ink">文本模型</b>用于对话与研判，<b className="text-ink">多模态模型</b>用于名片识别。
              Key 加密存储，仅显示后 4 位。
            </div>
          </div>
        </div>

        {/* 双槽位状态 */}
        {SLOTS.map((slot) => {
          const active = providers.filter((p) => p.slot === slot.key && p.status === 'active')
          const Icon = slot.icon
          return (
            <div key={slot.key} className="paper rounded-2xl border border-brass/25 bg-white/60 p-4 shadow-card">
              <div className="flex items-center gap-2.5 mb-3">
                <Icon size={16} className="text-brass" />
                <div className="flex-1">
                  <div className="font-serif font-bold text-ink text-[15px]">{slot.label}</div>
                  <div className="text-[11px] text-ink-soft/60">{slot.desc}</div>
                </div>
                <span className={`text-[11px] px-2 py-0.5 rounded-full ${active.length ? 'bg-jade/15 text-jade' : 'bg-ink-soft/10 text-ink-soft/60'}`}>
                  {active.length ? `${active.length} 条已配置` : '未配置（用平台默认）'}
                </span>
              </div>
              {active.length === 0 ? (
                <div className="text-[12px] text-ink-soft/50">暂无配置</div>
              ) : (
                <div className="space-y-2">
                  {active.map((p) => (
                    <ProviderRow key={p.id} p={p} onDelete={() => remove(p.id)} />
                  ))}
                </div>
              )}
            </div>
          )
        })}

        {/* 新增表单 */}
        {showForm ? (
          <div className="paper rounded-2xl border border-brass/30 bg-white/70 p-4 shadow-card space-y-3 animate-[fadeIn_.25s_ease]">
            <div className="flex items-center justify-between">
              <h3 className="font-serif font-bold text-ink">新增模型配置</h3>
              <button onClick={() => { setShowForm(false); setError(''); setTestResult(null) }} className="text-ink-soft/60 hover:text-ink" aria-label="关闭">
                <XCircle size={16} />
              </button>
            </div>

            {/* 槽位选择 */}
            <div className="flex gap-2">
              {SLOTS.map((s) => (
                <button
                  key={s.key}
                  onClick={() => setForm((f) => ({ ...f, slot: s.key }))}
                  className={`flex-1 py-2 rounded-xl border text-sm transition ${
                    form.slot === s.key ? 'border-brass bg-brass/10 text-ink font-medium' : 'border-brass/20 text-ink-soft/70 hover:border-brass/40'
                  }`}
                >
                  {s.label}
                </button>
              ))}
            </div>

            {/* 供应商预设 */}
            <div>
              <span className="text-[12px] text-ink-soft/80 mb-1.5 block">供应商</span>
              <div className="flex flex-wrap gap-1.5">
                {presets.map((p) => (
                  <button
                    key={p.provider}
                    onClick={() => pickPreset(p.provider)}
                    className={`px-2.5 py-1 rounded-full border text-[12px] transition ${
                      form.provider === p.provider
                        ? 'border-brass bg-brass/15 text-brass-deep font-medium'
                        : 'border-brass/25 text-ink-soft/70 hover:border-brass/50'
                    }`}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <label className="block">
                <span className="text-[12px] text-ink-soft/80 mb-1 block">配置名称</span>
                <input
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  placeholder="例如：我的 DeepSeek"
                  className="w-full rounded-lg border border-brass/30 bg-white/80 px-3 py-2 text-sm outline-none focus:border-brass focus:ring-2 focus:ring-brass/15 transition"
                />
              </label>
              <label className="block">
                <span className="text-[12px] text-ink-soft/80 mb-1 block">API Key</span>
                <div className="relative">
                  <KeyRound size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-brass/60" />
                  <input
                    value={form.apiKey}
                    onChange={(e) => setForm((f) => ({ ...f, apiKey: e.target.value }))}
                    placeholder="sk-…"
                    className="w-full rounded-lg border border-brass/30 bg-white/80 pl-8 pr-3 py-2 text-sm font-mono outline-none focus:border-brass focus:ring-2 focus:ring-brass/15 transition"
                  />
                </div>
              </label>
              <label className="block">
                <span className="text-[12px] text-ink-soft/80 mb-1 block">接口地址（Base URL）</span>
                <input
                  value={form.baseUrl}
                  onChange={(e) => setForm((f) => ({ ...f, baseUrl: e.target.value }))}
                  placeholder="https://…"
                  className="w-full rounded-lg border border-brass/30 bg-white/80 px-3 py-2 text-sm font-mono outline-none focus:border-brass focus:ring-2 focus:ring-brass/15 transition"
                />
              </label>
              <label className="block">
                <span className="text-[12px] text-ink-soft/80 mb-1 block">模型名</span>
                <input
                  value={form.model}
                  onChange={(e) => setForm((f) => ({ ...f, model: e.target.value }))}
                  placeholder="例如 deepseek-chat"
                  className="w-full rounded-lg border border-brass/30 bg-white/80 px-3 py-2 text-sm font-mono outline-none focus:border-brass focus:ring-2 focus:ring-brass/15 transition"
                />
              </label>
            </div>

            {error && <div className="text-[12px] text-cinnabar">⚠️ {error}</div>}
            {testResult && (
              <div className={`text-[12px] px-3 py-2 rounded-lg flex items-center gap-1.5 ${
                testResult.ok ? 'bg-jade/10 text-jade' : 'bg-cinnabar/10 text-cinnabar'
              }`}>
                {testResult.ok ? <CheckCircle2 size={13} /> : <XCircle size={13} />} {testResult.message}
              </div>
            )}

            <div className="flex justify-end gap-2">
              <button
                onClick={doTest}
                disabled={testing}
                className="px-3 py-1.5 rounded-lg border border-brass/30 text-sm flex items-center gap-1 hover:bg-brass/10 active:scale-95 transition disabled:opacity-50"
              >
                {testing ? <Loader2 size={13} className="animate-spin" /> : <Zap size={13} />} 测试连接
              </button>
              <button
                onClick={submit}
                disabled={saving}
                className="px-4 py-1.5 rounded-lg bg-brass text-white text-sm flex items-center gap-1 hover:bg-brass-deep active:scale-95 transition disabled:opacity-50"
              >
                {saving ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />} 保存配置
              </button>
            </div>
          </div>
        ) : (
          <button
            onClick={() => setShowForm(true)}
            className="w-full py-2.5 rounded-2xl border-2 border-dashed border-brass/35 text-brass-deep text-sm
              flex items-center justify-center gap-1.5 hover:border-brass hover:bg-brass/5 active:scale-[0.99] transition"
          >
            <Plus size={15} /> 新增模型配置
          </button>
        )}

        {providers.length === 0 && !showForm && (
          <EmptyState
            icon="key"
            title="还没有配置模型"
            desc="不配置也能用平台默认网关；配置后即可切换到自己的 Key 与模型。"
          />
        )}
      </div>
    </div>
  )
}

function ProviderRow({ p, onDelete }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-brass/15 bg-white/60 px-3 py-2.5 group">
      <div className="w-8 h-8 rounded-lg bg-jade/12 flex items-center justify-center shrink-0">
        <KeyRound size={14} className="text-jade" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-ink truncate">{p.name}</div>
        <div className="text-[11px] text-ink-soft/60 font-mono truncate">
          {p.provider} · {p.model || '默认模型'} · {p.base_url ? new URL(p.base_url).host : '—'}
        </div>
      </div>
      <button
        onClick={onDelete}
        className="p-1.5 rounded-lg text-ink-soft/50 hover:bg-cinnabar/10 hover:text-cinnabar transition opacity-0 group-hover:opacity-100"
        title="删除"
      >
        <Trash2 size={14} />
      </button>
    </div>
  )
}
