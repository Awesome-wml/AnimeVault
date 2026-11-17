/** 更新状态单例（纯逻辑见 utils/updateGate.js）。动态 import api，避免 router ↔ api 循环依赖。 */
import { createUpdateGate } from '../utils/updateGate'

export const updateGate = createUpdateGate({
  fetchStatus: () => import('../api').then(m => m.api.update.status())
})
