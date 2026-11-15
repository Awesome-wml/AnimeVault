/**
 * 机器码格式初检。只做格式层面的提示（去空白、字符集、长度、分组），
 * 校验位和内容是否真实有效以后端为准（MACHINE_CODE_INVALID / MACHINE_CODE_TOO_FEW）。
 * 编码规则见 license/dongai_license/machine_code.py：Base32（A-Z、2-7）+ 2 位校验，每 5 位一组用短横线连接。
 */
const B32 = /^[A-Z2-7]+$/

/** 分量数 k（1..9）对应的合法字符总数：ceil((1 + 8k) * 8 / 5) + 2。 */
export const VALID_LENGTHS = (() => {
  const m = {}
  for (let k = 1; k <= 9; k++) m[Math.ceil(((1 + 8 * k) * 8) / 5) + 2] = k
  return m
})()

/** 去掉空白、短横线、下划线并转大写；与后端一致，0->O、1->I。 */
export function normalizeMachineCode(input) {
  return String(input || '').replace(/[\s\-_]+/g, '').toUpperCase().replace(/0/g, 'O').replace(/1/g, 'I')
}

export function groupMachineCode(s) {
  return (s.match(/.{1,5}/g) || []).join('-')
}

/**
 * @returns {{level:'empty'|'ok'|'warn'|'error', message:string, normalized:string, formatted:string, components:number}}
 */
export function precheckMachineCode(input) {
  const normalized = normalizeMachineCode(input)
  const base = { normalized, formatted: groupMachineCode(normalized), components: 0 }
  if (!normalized) return { ...base, level: 'empty', message: '' }
  const bad = [...new Set(normalized.split('').filter(c => !/[A-Z2-7]/.test(c)))]
  if (bad.length || !B32.test(normalized)) {
    return { ...base, level: 'error', message: `包含无效字符：${bad.join(' ')}（机器码只含字母 A-Z 和数字 2-7）` }
  }
  const k = VALID_LENGTHS[normalized.length]
  if (!k) {
    const lens = Object.keys(VALID_LENGTHS).map(Number)
    const min = lens[0]
    if (normalized.length < min) {
      return { ...base, level: 'error', message: `长度不够（已输入 ${normalized.length} 位），请检查是否复制完整` }
    }
    return { ...base, level: 'error', message: `长度不对（已输入 ${normalized.length} 位，正常为 ${lens.slice(0, 4).join('、')} 位等），请检查是否复制完整或多复制了内容` }
  }
  if (k < 2) {
    return { ...base, level: 'error', components: k, message: '机器码只含 1 个硬件分量，不足 2 个，不能签发' }
  }
  return { ...base, level: 'ok', components: k, message: `格式正常，约含 ${k} 个硬件分量（最终以服务端校验为准）` }
}
