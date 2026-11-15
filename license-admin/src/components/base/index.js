/** 基础组件全局注册，页面里直接用 <PageHeader> <BaseTable> 等 */
import PageHeader from './PageHeader.vue'
import StatusTag from './StatusTag.vue'
import CopyButton from './CopyButton.vue'
import ConfirmDialog from './ConfirmDialog.vue'
import WarnBar from './WarnBar.vue'
import JsonFold from './JsonFold.vue'
import BaseTable from './BaseTable.vue'
import SimplePager from './SimplePager.vue'

const components = { PageHeader, StatusTag, CopyButton, ConfirmDialog, WarnBar, JsonFold, BaseTable, SimplePager }

export default {
  install(Vue) {
    Object.keys(components).forEach(name => Vue.component(name, components[name]))
  }
}
