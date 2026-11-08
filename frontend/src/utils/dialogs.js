/** 统一的确认/输入弹框（基于 Element MessageBox），页面不再各自拼参数。 */
import { MessageBox } from 'element-ui'

/** 删除类确认：确定返回 true，取消返回 false（不抛异常） */
export function confirmDelete(message, title = '确认删除', confirmText = '删除') {
  return MessageBox.confirm(message, title, {
    type: 'warning',
    confirmButtonText: confirmText,
    cancelButtonText: '取消'
  }).then(() => true, () => false)
}

/** 单行输入：确定返回去掉首尾空格的文字，取消或空值返回 null */
export function promptText(message, title, defaultValue = '') {
  return MessageBox.prompt(message, title, {
    inputValue: defaultValue,
    confirmButtonText: '确定',
    cancelButtonText: '取消',
    inputValidator: v => (v && v.trim() ? true : '不能为空')
  }).then(({ value }) => (value || '').trim() || null, () => null)
}
