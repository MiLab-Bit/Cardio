// 名片/客户档案卡：字段网格 + 需求标签
export default function ProfileCard({ profile }) {
  if (!profile) return null
  const rows = [
    ['姓名', profile.name], ['职位', profile.title], ['公司', profile.company],
    ['行业', profile.industry], ['电话', profile.phone || profile.mobile], ['邮箱', profile.email],
  ].filter(([, v]) => v)
  const hasRows = rows.length > 0
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2 text-sm">
      {hasRows ? rows.map(([k, v]) => (
        <div key={k} className="flex gap-2">
          <span className="text-ink-soft/70 w-10 shrink-0">{k}</span>
          <span className="text-ink font-medium break-all">{v}</span>
        </div>
      )) : (
        <div className="col-span-2 text-ink-soft/60 text-[13px]">暂无结构化字段</div>
      )}
      {profile.needs?.length > 0 && (
        <div className="col-span-1 sm:col-span-2 flex gap-2">
          <span className="text-ink-soft/70 w-10 shrink-0">需求</span>
          <span className="flex flex-wrap gap-1">
            {profile.needs.map((n, i) => (
              <span key={i} className="px-2 py-0.5 rounded-full bg-brass/15 text-brass-deep text-[12px]">{n}</span>
            ))}
          </span>
        </div>
      )}
      {profile.notes && (
        <div className="col-span-1 sm:col-span-2 flex gap-2">
          <span className="text-ink-soft/70 w-10 shrink-0">备注</span>
          <span className="text-ink-soft text-[13px] leading-relaxed">{profile.notes}</span>
        </div>
      )}
    </div>
  )
}
