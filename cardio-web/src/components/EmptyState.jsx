// 空状态：SVG 小插画 + 文案 + 行动按钮
export default function EmptyState({ icon = 'book', title, desc, action }) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-16 px-6 animate-[fadeIn_.3s_ease]">
      <div className="w-32 h-32 mb-5 opacity-90">
        {icon === 'book' && (
          <svg viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect x="25" y="20" width="70" height="85" rx="6" fill="#f4ecd8" stroke="#b08d57" strokeWidth="2.5" />
            <path d="M60 26v73" stroke="#b08d57" strokeWidth="2" strokeDasharray="4 4" />
            <path d="M35 40h16M35 52h16M35 64h16M69 40h16M69 52h16M69 64h16" stroke="#8a6d3f" strokeWidth="2.5" strokeLinecap="round" opacity="0.5" />
            <circle cx="60" cy="86" r="7" fill="#b08d57" opacity="0.25" />
          </svg>
        )}
        {icon === 'history' && (
          <svg viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg">
            <circle cx="60" cy="60" r="38" fill="#f4ecd8" stroke="#b08d57" strokeWidth="2.5" />
            <path d="M60 42v20l14 8" stroke="#8a6d3f" strokeWidth="3" strokeLinecap="round" />
            <path d="M60 26v-6M60 100v-6M26 60h-6M100 60h-6" stroke="#b08d57" strokeWidth="2.5" strokeLinecap="round" />
          </svg>
        )}
        {icon === 'key' && (
          <svg viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg">
            <circle cx="45" cy="45" r="20" fill="#f4ecd8" stroke="#b08d57" strokeWidth="2.5" />
            <path d="M59 59l30 30M78 78l-8 8M86 86l-8 8" stroke="#8a6d3f" strokeWidth="3.5" strokeLinecap="round" />
          </svg>
        )}
        {icon === 'chat' && (
          <svg viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M22 34h76v46H62L40 96V80H22V34z" fill="#f4ecd8" stroke="#b08d57" strokeWidth="2.5" strokeLinejoin="round" />
            <path d="M38 50h44M38 62h28" stroke="#8a6d3f" strokeWidth="2.5" strokeLinecap="round" opacity="0.5" />
          </svg>
        )}
      </div>
      <h3 className="font-serif text-lg font-bold text-ink mb-1.5">{title}</h3>
      <p className="text-[13px] text-ink-soft/70 max-w-xs leading-relaxed">{desc}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}
