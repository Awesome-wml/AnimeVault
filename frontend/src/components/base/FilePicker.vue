<template>
  <input ref="input" type="file" class="sr-only" tabindex="-1" aria-hidden="true" :accept="accept" @change="onChange" />
</template>

<script>
/**
 * 隐藏的文件选择框。父组件 this.$refs.picker.open(context) 打开，
 * 选好后 emit('select', file, context)；context 原样带回（如要上传到哪个资产）。
 */
export default {
  name: 'FilePicker',
  props: { accept: { type: String, default: '' } },
  data() {
    return { context: null }
  },
  methods: {
    open(context = null) {
      this.context = context
      this.$refs.input.value = ''
      this.$refs.input.click()
    },
    onChange(e) {
      const file = e.target.files && e.target.files[0]
      if (file) this.$emit('select', file, this.context)
      this.context = null
    }
  }
}
</script>
