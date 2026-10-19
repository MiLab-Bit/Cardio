// 全局常量：导航与五段管线定义

export const NAV = [
  { key: 'chat', label: '商枢对话', icon: 'Compass', desc: '随时问、随手记' },
  { key: 'analyze', label: '数字商册分析', icon: 'ScanSearch', desc: '名片/会议 → 五段研判' },
  { key: 'contacts', label: '商册名录', icon: 'Users', desc: '你的人脉库' },
  { key: 'history', label: '历史研判', icon: 'History', desc: '过往分析记录' },
  { key: 'providers', label: '模型配置', icon: 'Boxes', desc: '自带大模型 Key' },
  { key: 'settings', label: '设置', icon: 'Settings', desc: '后端地址等' },
]

export const STAGE_ORDER = [
  { key: 'extraction', label: '信息提取', agent: '提取官', icon: '🪪' },
  { key: 'research', label: '背景调研', agent: '调研员', icon: '🔭' },
  { key: 'synthesis', label: '画像合成', agent: '画像师', icon: '🧭' },
  { key: 'strategy', label: 'BD 策略', agent: '谋士', icon: '♟️' },
  { key: 'critique', label: '风险审核', agent: '审官', icon: '🛡️' },
]
