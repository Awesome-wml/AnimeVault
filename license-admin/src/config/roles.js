/** 管理员角色与权限（与服务端 deps.py 的 READ / WRITE / SUPER 一致）。 */
export const ROLES = [
  { value: 'super', label: '超级管理员' },
  { value: 'ops', label: '运营' },
  { value: 'readonly', label: '只读' }
]

export function roleLabel(role) {
  const r = ROLES.find(x => x.value === role)
  return r ? r.label : role || '-'
}

const PERMS = {
  'license.read': ['super', 'ops', 'readonly'],
  'license.write': ['super', 'ops'],
  'audit.read': ['super', 'ops'],
  'admin.manage': ['super']
}

export function can(role, perm) {
  return (PERMS[perm] || []).includes(role)
}

/** 侧边栏菜单，按角色过滤。 */
export const MENU = [
  { path: '/licenses', title: '授权管理', icon: 'el-icon-key', perm: 'license.read' },
  { path: '/audit', title: '审计日志', icon: 'el-icon-document', perm: 'audit.read' },
  { path: '/admins', title: '管理员管理', icon: 'el-icon-user', perm: 'admin.manage' }
]

export function menuFor(role) {
  return MENU.filter(m => can(role, m.perm))
}
