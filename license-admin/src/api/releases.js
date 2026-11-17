import http from './http'

export const releases = {
  /** params: {channel?, platform?, status?, page, page_size} */
  list: (params) => http.get('/releases', { params }),
  get: (id) => http.get(`/releases/${id}`),
  /** payload: {version, channel, platform, notes, url, sha256, size, min_supported|null} */
  create: (payload) => http.post('/releases', payload),
  /** 仅草稿可改；payload 只传要改的字段 */
  update: (id, payload) => http.put(`/releases/${id}`, payload),
  /** 返回 {release, warnings[], force_line:{before, after}} */
  publish: (id) => http.post(`/releases/${id}/publish`),
  /** 返回同上；撤回的是强制升级线的唯一来源时 warnings 非空 */
  withdraw: (id) => http.post(`/releases/${id}/withdraw`)
}
