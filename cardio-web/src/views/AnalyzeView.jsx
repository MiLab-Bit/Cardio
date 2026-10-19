// 数字商册分析：名片上传 + 五段研判（SSE 进度可视化）
import { useState, useRef } from 'react'
import { ScanSearch, Loader2, Sparkles, Save, ImageUp, BookOpen, X } from 'lucide-react'
import { analyzeStream, scanCard, saveContact, AuthError } from '../api.js'
import StageCard from '../components/StageCard.jsx'
import ProfileCard from '../components/ProfileCard.jsx'
import { STAGE_ORDER } from '../constants.js'

export default function AnalyzeView({ onGoContacts }) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [stages, setStages] = useState({})
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)

  // 名片图片
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

  function clearImage() {
    setImage(''); setImageName(''); setCard(null); setCardError(''); setCardSaved(false)
    if (fileRef.current) fileRef.current.value = ''
  }

  async function doScan() {
    if (!image || scanning) return
    setScanning(true); setCardError(''); setCard(null); setCardSaved(false)
    try {
      setCard(await scanCard(image, imageName.endsWith('.png') ? 'png' : 'jpeg'))
    } catch (e) {
      if (e instanceof AuthError) return
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
      if (e instanceof AuthError) return
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
        } else if (ev.type === 'contact_saved') {
          setStages((s) => ({ ...s, _contact: { status: 'done', contact: ev.contact } }))
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
      if (e instanceof AuthError) return
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
      if (e instanceof AuthError) return
      setError('保存失败：' + e.message)
    }
  }

  const doneCount = STAGE_ORDER.filter((st) => stages[st.key]?.status === 'done').length
  const progressPct = busy || doneCount ? Math.round((doneCount / STAGE_ORDER.length) * 100) : 0

  return (
    <div className="h-full overflow-y-auto px-4 md:px-5 py-5">
      <div className="max-w-3xl mx-auto space-y-5">
        {/* 输入区 */}
        <div className="paper rounded-2xl border border-brass/25 bg-white/60 p-4 shadow-card">
          <label className="text-sm font-medium text-ink-soft">输入客户 / 会议信息，或上传名片照片</label>

          {/* 名片上传 */}
          <div className="mt-2 flex items-center gap-3">
            <div
              onClick={() => !image && fileRef.current?.click()}
              className={`relative w-28 h-20 rounded-xl border-2 border-dashed border-brass/40 bg-white/60 flex flex-col items-center justify-center transition ${
                image ? '' : 'cursor-pointer hover:border-brass hover:bg-brass/5'
              } text-brass/70`}
            >
              {image ? (
                <>
                  <img src={image} alt="名片" className="w-full h-full object-cover rounded-xl" />
                  <button
                    onClick={(e) => { e.stopPropagation(); clearImage() }}
                    className="absolute -top-2 -right-2 w-6 h-6 rounded-full bg-ink text-parchment flex items-center justify-center shadow hover:bg-cinnabar transition"
                    aria-label="清除图片"
                  >
                    <X size={12} />
                  </button>
                </>
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
                  className="px-3 py-1.5 rounded-lg bg-ink text-parchment text-sm flex items-center gap-1 hover:bg-ink/90 active:scale-95 transition disabled:opacity-50"
                >
                  {scanning ? <Loader2 size={14} className="animate-spin" /> : <ScanSearch size={14} />}
                  {scanning ? '识别中…' : '仅识别'}
                </button>
              </div>
            </div>
          </div>

          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={4}
            placeholder="也可在此粘贴名片文字或会议记录…（例如：客户王明，环球科技 CEO，想找跨境供应链方案，关注成本和交期。）"
            className="mt-3 w-full resize-y rounded-xl border border-brass/30 bg-white/80 px-3 py-2 text-sm text-ink outline-none focus:border-brass focus:ring-2 focus:ring-brass/15 transition"
          />
          <div className="mt-3 flex items-center justify-between gap-3">
            <span className="text-[11px] text-ink-soft/70">五段式研判：提取 → 调研 → 画像 → 策略 → 审核</span>
            <button
              onClick={run}
              disabled={busy || (!text.trim() && !image)}
              className="px-5 py-2 rounded-xl bg-brass text-white font-medium flex items-center gap-1.5 shadow-card hover:bg-brass-deep active:scale-95 transition disabled:opacity-50"
            >
              {busy ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
              {busy ? '研判中…' : '开始分析'}
            </button>
          </div>
        </div>

        {/* 进度条 */}
        {(busy || doneCount > 0) && (
          <div className="paper rounded-2xl border border-brass/25 bg-white/60 p-4 shadow-card animate-[fadeIn_.3s_ease]">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[13px] font-medium text-ink">研判进度</span>
              <span className="text-[12px] text-brass-deep font-medium">
                {doneCount} / {STAGE_ORDER.length} 段{progressPct === 100 ? ' · 完成' : ''}
              </span>
            </div>
            <div className="h-2 rounded-full bg-brass/15 overflow-hidden">
              <div
                className="h-full rounded-full bg-gradient-to-r from-brass to-jade transition-all duration-700 ease-out"
                style={{ width: `${Math.max(progressPct, 4)}%` }}
              />
            </div>
          </div>
        )}

        {cardError && <ErrorBox msg={cardError} />}

        {/* 仅识别结果 */}
        {card && !scanning && (
          <div className="paper rounded-2xl border border-brass/30 bg-white/70 p-4 shadow-card animate-[fadeIn_.3s_ease]">
            <div className="flex items-center justify-between mb-3">
              <div className="font-serif text-lg font-bold text-ink flex items-center gap-2">
                <ScanSearch size={18} className="text-brass" /> 名片识别结果
              </div>
              <button
                onClick={saveScanned}
                disabled={cardSaved}
                className="px-3 py-1.5 rounded-lg text-sm bg-brass text-white flex items-center gap-1 hover:bg-brass-deep active:scale-95 transition disabled:opacity-60"
              >
                <Save size={14} /> {cardSaved ? '已存入商册' : '存入商册'}
              </button>
            </div>
            <ProfileCard profile={card} />
          </div>
        )}

        {error && <ErrorBox msg={error} />}

        {/* 带图分析时的名片识别阶段 */}
        {stages._vision && stages._vision.status !== 'done' && (
          <div className={`rounded-2xl border p-4 ${
            stages._vision.status === 'error' ? 'border-cinnabar/40 bg-cinnabar/5' : 'border-brass/40 bg-brass/5'
          }`}>
            <div className="flex items-center gap-3">
              <div className="text-2xl">📷</div>
              <div className="flex-1">
                <div className="font-medium text-ink">名片识别</div>
                <div className="text-[11px] text-ink-soft/70">
                  视觉模型 · {stages._vision.status === 'start' ? '识别中…' : '识别失败'}
                </div>
              </div>
              {stages._vision.status === 'start' ? (
                <Loader2 size={18} className="text-brass animate-spin" />
              ) : (
                <span className="text-[12px] text-cinnabar">{stages._vision.error}</span>
              )}
            </div>
          </div>
        )}

        {/* 名片自动落库提示 */}
        {stages._contact?.status === 'done' && (
          <div className="rounded-xl border border-jade/40 bg-jade/10 px-4 py-2.5 text-[13px] text-jade animate-[fadeIn_.3s_ease]">
            📇 名片已自动存入商册：{stages._contact.contact?.name || '新联系人'}
          </div>
        )}

        {/* 五段管线 */}
        {STAGE_ORDER.map((st, i) => (
          <StageCard key={st.key} meta={st} state={stages[st.key]} index={i} total={STAGE_ORDER.length} />
        ))}

        {/* 最终档案 */}
        {result && (
          <div className="paper rounded-2xl border border-jade/30 bg-white/70 p-4 shadow-card animate-[fadeIn_.4s_ease]">
            <div className="flex items-center justify-between mb-3 gap-2">
              <div className="font-serif text-lg font-bold text-ink flex items-center gap-2">
                <BookOpen size={18} className="text-jade" /> 商册档案
              </div>
              <div className="flex gap-2">
                {onGoContacts && (
                  <button
                    onClick={onGoContacts}
                    className="px-3 py-1.5 rounded-lg border border-jade/40 text-jade text-sm hover:bg-jade/10 active:scale-95 transition"
                  >
                    去商册查看
                  </button>
                )}
                <button
                  onClick={saveToBook}
                  disabled={saved}
                  className="px-3 py-1.5 rounded-lg text-sm bg-jade text-white flex items-center gap-1 hover:bg-jade/90 active:scale-95 transition disabled:opacity-60"
                >
                  <Save size={14} /> {saved ? '已存入商册' : '存入商册'}
                </button>
              </div>
            </div>
            <ProfileCard profile={result.profile} />
          </div>
        )}
      </div>
    </div>
  )
}

function ErrorBox({ msg }) {
  return (
    <div className="rounded-xl border border-cinnabar/40 bg-cinnabar/10 px-4 py-3 text-sm text-cinnabar animate-[fadeIn_.2s_ease]">
      ⚠️ {msg}
    </div>
  )
}
