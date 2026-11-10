<template>
  <div class="view-tags" role="group" :aria-label="`${item.name} 的视角`">
    <p v-if="item.state_note" class="view-tags__state" :title="item.state_note">剧情状态：{{ item.state_note }}</p>
    <div class="chip-group view-tags__row" role="tablist">
      <button
        v-for="(v, i) in views"
        :key="i"
        type="button"
        role="tab"
        class="chip view-tags__chip"
        :class="{ 'is-missing': !hasImage(i) }"
        :aria-pressed="String(i === value)"
        :aria-selected="String(i === value)"
        :title="hasImage(i) ? v.camera || v.name : `${v.camera || v.name}（还没有场景图）`"
        @click="$emit('input', i)"
      >{{ v.name }}</button>
      <button type="button" class="view-tags__edit" :aria-label="`编辑${item.name}当前视角的名称和机位`" @click="startEdit">{{ editing ? '取消' : '改视角' }}</button>
    </div>
    <div v-if="editing" class="view-tags__editor">
      <el-input v-model.trim="draft.name" size="small" placeholder="视角名" maxlength="20" :aria-label="`${item.name} 视角名`" />
      <el-input v-model.trim="draft.camera" size="small" placeholder="机位朝向，30 字内" :maxlength="30" :aria-label="`${item.name} 机位朝向`" @keydown.enter.native="save" />
      <BaseButton variant="text" strong :loading="saving" @click="save">保存</BaseButton>
    </div>
    <p v-else-if="current.camera" class="view-tags__camera" :title="current.camera">机位：{{ current.camera }}</p>
  </div>
</template>

<script>
/**
 * 场景卡上的视角标签行：每个视角一个标签，点标签切换卡片上显示的那张场景图；
 * “改视角”把当前视角的名称和机位改成可编辑，保存 emit('save', views, done)（整份 views，由页面调接口）。
 * 有剧情状态（state_note）时在标签上方显示一行。
 */
import { sceneViews, viewImage, cleanViews } from './views'

export default {
  name: 'SceneViewTags',
  props: {
    item: { type: Object, required: true },
    /** 当前选中的视角下标 */
    value: { type: Number, default: 0 },
    saving: Boolean
  },
  data() {
    return { editing: false, draft: { name: '', camera: '' } }
  },
  computed: {
    views() { return sceneViews(this.item) },
    current() { return this.views[this.value] || this.views[0] }
  },
  watch: {
    value() { this.editing = false }
  },
  methods: {
    hasImage(i) { return !!viewImage(this.item, i) },
    startEdit() {
      if (this.editing) { this.editing = false; return }
      this.draft = { name: this.current.name || '', camera: this.current.camera || '' }
      this.editing = true
    },
    save() {
      const views = cleanViews(this.views.map((v, i) => (i === this.value ? { ...v, ...this.draft } : v)))
      this.$emit('save', views, () => { this.editing = false })
    }
  }
}
</script>

<style scoped>
.view-tags { display: flex; flex-direction: column; gap: 6px; }
.view-tags__row { align-items: center; }
.view-tags__chip { min-height: 28px; padding: 0 10px; font-size: var(--fs-caption); border: 1px solid var(--line); }
.view-tags__chip.is-missing { color: var(--ink-muted); border-style: dashed; }
.view-tags__chip[aria-pressed="true"] { border-color: var(--ink); }
.view-tags__edit { border: 0; background: transparent; color: var(--ink-muted); font-size: var(--fs-caption); cursor: pointer; padding: 0 4px; }
.view-tags__edit:hover { color: var(--ink); text-decoration: underline; }
.view-tags__editor { display: grid; grid-template-columns: 1fr 1.6fr auto; gap: 6px; align-items: center; }
.view-tags__state, .view-tags__camera { margin: 0; font-size: var(--fs-caption); color: var(--ink-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
