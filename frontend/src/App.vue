<template>
  <div id="app">
    <LicenseBanner />
    <router-view />
  </div>
</template>

<script>
import LicenseBanner from '@/components/license/LicenseBanner.vue'

export default {
  name: 'App',
  components: { LicenseBanner }
}
</script>
