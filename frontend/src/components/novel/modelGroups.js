/**
 * 模型预设 → 按用途分开的下拉选项（纯函数，不发请求）。
 * 用途由后端算好：row.model_kinds = { 模型ID: 'chat' | 'image' }（预设上手动标了用途就整条按手动的，否则按模型名判断）。
 *   chat  对话：写小说、润色、转剧本、提取、拆分镜
 *   image 出图：资产参考图、四格分镜图
 * 默认也按用途各一个：row.is_default 且含这类模型的那条预设；没有设过默认就取第一条。
 */
const PROVIDER_LABELS = {
  zhipu: '智谱 GLM', deepseek: 'DeepSeek', openai: 'OpenAI', gemini: 'Google Gemini', volcengine: '火山方舟', other: '其他'
}

export function modelsOf(m) {
  return m.models || (m.model ? [m.model] : [])
}

function kindOf(m, mid) {
  if (m.model_kinds && m.model_kinds[mid]) return m.model_kinds[mid]
  return m.model_type === 'image' ? 'image' : 'chat' // 老后端没有 model_kinds
}

function groupsOf(list, kind) {
  return list.map(m => {
    // advice：后端 model_caps.LONG_OUTPUT_ADVICE 判定的“拆分镜等长输出不稳”提示（页面只显示，不写死模型名）
    const advice = m.long_output_advice || {}
    return {
      id: m._id,
      isDefault: !!m.is_default,
      provider: m.provider || 'other',
      label: m.name || PROVIDER_LABELS[m.provider] || m.provider || '未命名预设',
      items: modelsOf(m).filter(mid => kindOf(m, mid) === kind).map(mid => ({
        key: `${m._id}::${mid}`,
        label: mid,
        advice: (advice[mid] && advice[mid].message) || ''
      }))
    }
  }).filter(g => g.items.length)
}

function defaultOf(groups) {
  const g = groups.find(x => x.isDefault) || groups[0]
  return g ? { key: g.items[0].key, label: `${g.label} · ${g.items[0].label}`, explicit: g.isDefault } : { key: '', label: '', explicit: false }
}

export function buildModelOptions(list) {
  const chatGroups = groupsOf(list || [], 'chat')
  const imageGroups = groupsOf(list || [], 'image')
  const chat = defaultOf(chatGroups)
  const image = defaultOf(imageGroups)
  return {
    chatGroups,
    imageGroups,
    chatDefaultKey: chat.key,
    // 出图不选时由后端决定：设了默认出图预设就用它，否则用账号设置里的模型。这里只给页面显示用
    imageDefaultLabel: image.explicit ? image.label : ''
  }
}
