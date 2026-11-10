/** 侧栏菜单配置（SideNav 的 groups）。菜单项只在这里增删。 */

export const GLOBAL_NAV = [
  {
    key: 'create',
    title: '创作',
    items: [
      { label: '首页', to: '/home' },
      { label: '全部作品', to: '/works' }
    ]
  },
  {
    key: 'settings',
    title: '设置',
    items: [
      { label: '模型', to: '/settings/models' },
      { label: '提示词', to: '/settings/prompts' },
      { label: '视频账号', to: '/settings/accounts' }
    ]
  }
]

/**
 * 作品内侧栏。
 * @param {string} pid 作品 id
 * @param {{characters:number, scenes:number, props:number, scripts:number}} counts
 * @param {string} ep 当前剧集 id（制作类页面带上 ?ep=）
 */
export function projectNav(pid, counts, ep) {
  const base = `/projects/${pid}`
  const withEp = path => (ep ? { path, query: { ep } } : path)
  return [
    {
      key: 'story',
      title: '故事',
      items: [
        { label: '小说', to: withEp(`${base}/novel`) },
        { label: '剧本', to: withEp(`${base}/script`), count: counts.scripts },
        { label: '风格', to: `${base}/style` }
      ]
    },
    {
      key: 'assets',
      title: '资产',
      items: [
        { label: '角色', to: `${base}/characters`, count: counts.characters },
        { label: '场景', to: `${base}/scenes`, count: counts.scenes },
        { label: '道具', to: `${base}/props`, count: counts.props }
      ]
    },
    {
      key: 'make',
      title: '制作',
      slot: 'episode',
      items: [
        // 失败数需要后端提供分镜生成状态，目前不显示 alert
        { label: '分镜', to: withEp(`${base}/shots`) },
        { label: '配音与字幕', to: withEp(`${base}/voice`) },
        { label: '成片', to: withEp(`${base}/final`) },
        { label: '管理剧集', to: `${base}/episodes` }
      ]
    }
  ]
}
