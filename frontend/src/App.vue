<template>
  <div id="app">
    <!-- 顶部提示条统一粘在一个容器里，授权条在上、更新条在下，互不遮挡 -->
    <div class="app-bars">
      <LicenseBanner />
      <UpdateBanner />
    </div>
    <router-view />
    <!-- 强制升级：全屏盖住整个应用（后端已拦截业务接口） -->
    <UpdateRequiredScreen v-if="updateRequired" />
  </div>
</template>

<script>
import LicenseBanner from '@/components/license/LicenseBanner.vue'
import UpdateBanner from '@/components/update/UpdateBanner.vue'
import UpdateRequiredScreen from '@/components/update/UpdateRequiredScreen.vue'
import { isUpdateRequiredStatus } from '@/components/update/update'
import { updateGate } from '@/router/updateGate'

export default {
  name: 'App',
  components: { LicenseBanner, UpdateBanner, UpdateRequiredScreen },
  data() {
    return { updateRequired: isUpdateRequiredStatus(updateGate.peek()), unsub: null }
  },
  created() {
    this.unsub = updateGate.subscribe(s => { this.updateRequired = isUpdateRequiredStatus(s) })
    updateGate.check()
  },
  beforeDestroy() {
    if (this.unsub) this.unsub()
  }
}
</script>

<style>
.app-bars { position: sticky; top: 0; z-index: 2000; }
</style>
