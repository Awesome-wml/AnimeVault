/** 风格库（媒介 + 题材）：全站只请求一次（风格页、小说页 AI 写作、资产页提取与出图共用）。纯函数在 styleLibrary.js。 */
import { api } from '@/api'
import { EMPTY_LIBRARY } from './styleLibrary'

let cache = null

export function loadStyleLibrary() {
  if (!cache) {
    cache = api.config.styleLibrary()
      .then(res => ({ ...EMPTY_LIBRARY, ...((res && res.data) || {}) }))
      .catch(e => { cache = null; throw e })
  }
  return cache
}
