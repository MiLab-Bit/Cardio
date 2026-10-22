// 商枢·AI 咨询（SSE 流式）
import { useEffect, useRef, useState } from 'react'
import { Send, Loader2, Trash2, Compass } from 'lucide-react'
import { chatStream, AuthError } from '../api.js'

const GREETING = {
  role: 'assistant',
  content: '我是商枢，你的 AI 咨询助手。把客户或会议信息告诉我，我帮你记下来，也能用「五段研判」做深度研判。',
}

export default function ChatView() {
  const [msgs, setMsgs] = useState([GREETING])
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
      if (e instanceof AuthError) return // 已触发登出，交给 App 处理
      setMsgs((m) => [...m, { role: 'assistant', content: '⚠️ ' + e.message }])
      setStreaming('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="h-full flex flex-col">
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 md:px-5 py-5 space-y-4">
        {msgs.map((m, i) => (
          <Bubble key={i} role={m.role} content={m.content} />
        ))}
        {streaming && <Bubble role="assistant" content={streaming} streaming />}
        {busy && !streaming && (
          <div className="flex justify-start">
            <div className="bg-white/80 px-4 py-3 rounded-2xl rounded-bl-sm shadow-card flex items-center gap-1.5">
              <span className="typing-dot" style={{ animationDelay: '0ms' }} />
              <span className="typing-dot" style={{ animationDelay: '200ms' }} />
              <span className="typing-dot" style={{ animationDelay: '400ms' }} />
              <span className="text-[12px] text-ink-soft/60 ml-1">商枢思考中</span>
            </div>
          </div>
        )}
      </div>

      {/* 输入区 */}
      <div className="p-4 border-t border-brass/20 bg-parchment/50">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
            rows={2}
            placeholder="和商枢说点什么…（Enter 发送，Shift+Enter 换行）"
            className="flex-1 resize-none rounded-xl border border-brass/30 bg-white/70 px-3 py-2 text-sm text-ink outline-none focus:border-brass focus:ring-2 focus:ring-brass/15 transition"
          />
          <div className="flex flex-col gap-1.5">
            <button
              onClick={send}
              disabled={busy || !input.trim()}
              className="h-10 px-4 rounded-xl bg-brass text-white font-medium flex items-center gap-1
                shadow-card hover:bg-brass-deep active:scale-95 transition disabled:opacity-50"
            >
              {busy ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
              发送
            </button>
            {msgs.length > 1 && (
              <button
                onClick={() => setMsgs([GREETING])}
                title="清空对话"
                className="h-7 px-2 rounded-lg border border-brass/25 text-ink-soft/70 text-[12px] flex items-center justify-center gap-1 hover:bg-brass/10 transition"
              >
                <Trash2 size={12} /> 清空
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function Bubble({ role, content, streaming }) {
  const isUser = role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} animate-[fadeIn_.25s_ease]`}>
      {!isUser && (
        <div className="w-8 h-8 rounded-full bg-brass/15 flex items-center justify-center mr-2 mt-0.5 shrink-0">
          <Compass size={15} className="text-brass" />
        </div>
      )}
      <div className={`max-w-[80%] px-4 py-2.5 rounded-2xl text-sm leading-relaxed shadow-card whitespace-pre-wrap break-words ${
        isUser ? 'bg-brass text-white rounded-br-sm' : 'bg-white/80 text-ink rounded-bl-sm'
      }`}>
        {content}
        {streaming && <span className="cursor-blink" />}
      </div>
    </div>
  )
}
