/**
 * 角色 / 场景 / 道具三类资产的差异只写在这里，页面和组件按 kind 取配置。
 */
import { api } from '@/api'

export const ASSET_KINDS = {
  character: {
    label: '角色',
    unit: '个',
    api: api.character,
    typeField: '',
    ratio: '3 / 4',
    fit: 'contain',
    gridClass: 'card-grid--asset-portrait',
    generateText: '生成三视图',
    uploadText: '上传三视图',
    imageName: '三视图',
    descLabel: '外貌人设',
    descPlaceholder: '外貌特征、服饰、性格等',
    extractHint: 'AI 会按项目风格提取 3–10 个主要角色：固定面部特征、按换装拆分的形态（含出现场次）和音色描述；每个形态可生成一张三视图。',
    hasVoice: true
  },
  scene: {
    label: '场景',
    unit: '个',
    api: api.scene,
    typeField: 'scene_type',
    typePlaceholder: '如：室内、室外、宫殿',
    ratio: '16 / 9',
    fit: 'cover',
    gridClass: 'card-grid--asset-wide',
    generateText: '生成参考图',
    uploadText: '上传参考图',
    imageName: '参考图',
    descLabel: '环境描述',
    descPlaceholder: '地点、布局、天气、光影',
    extractHint: 'AI 会按项目风格提取重要场景 / 地点及环境氛围，同时给出剧情发生时的关键物件状态和同一空间的多个视角；每个视角可生成一张场景图。',
    hasVoice: false
  },
  prop: {
    label: '道具',
    unit: '件',
    api: api.prop,
    typeField: 'prop_type',
    typePlaceholder: '如：武器、法宝、信物',
    ratio: '1 / 1',
    fit: 'cover',
    gridClass: 'card-grid--asset-square',
    generateText: '生成参考图',
    uploadText: '上传参考图',
    imageName: '参考图',
    descLabel: '描述',
    descPlaceholder: '材质、外观、来历',
    extractHint: 'AI 会按项目风格提取重要道具 / 物品及外观特征。',
    hasVoice: false
  }
}

export function assetKind(kind) {
  return ASSET_KINDS[kind] || ASSET_KINDS.character
}

// 角色重要度（后端提取时给出）
const IMPORTANCE = { main: '主要角色', support: '配角', extra: '路人' }

/** 卡片名称右侧的小字：角色取重要度，场景/道具取类型 */
export function assetBadge(kind, item) {
  if (kind === 'character') return IMPORTANCE[item.importance] || item.importance || ''
  const field = assetKind(kind).typeField
  return (field && item[field]) || ''
}
