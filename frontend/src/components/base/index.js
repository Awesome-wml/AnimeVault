/** 基础组件全局注册，页面里直接用 <PageHeader> <BaseButton> 等，无需逐个 import。 */
import PageHeader from './PageHeader.vue'
import BaseButton from './BaseButton.vue'
import StatusText from './StatusText.vue'
import MediaFrame from './MediaFrame.vue'
import AssetCard from './AssetCard.vue'
import EmptyState from './EmptyState.vue'
import Seal from './Seal.vue'
import FormField from './FormField.vue'
import MoreMenu from './MoreMenu.vue'
import FilePicker from './FilePicker.vue'
import BatchProgress from './BatchProgress.vue'

const components = { PageHeader, BaseButton, StatusText, MediaFrame, AssetCard, EmptyState, Seal, FormField, MoreMenu, FilePicker, BatchProgress }

export default {
  install(Vue) {
    Object.keys(components).forEach(name => Vue.component(name, components[name]))
  }
}
