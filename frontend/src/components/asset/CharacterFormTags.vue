<template>
  <div class="form-tags" role="group" :aria-label="`${name} 的形态`">
    <template v-if="!single">
      <div class="chip-group form-tags__row" role="tablist">
        <button
          v-for="(f, i) in forms"
          :key="i"
          type="button"
          role="tab"
          class="chip form-tags__chip"
          :class="{ 'is-missing': !hasImage(i) }"
          :aria-pressed="String(i === value)"
          :aria-selected="String(i === value)"
          :title="hasImage(i) ? `${f.outfit || ''}` : `${f.outfit || ''}（还没有三视图）`"
          @click="$emit('input', i)"
        >{{ label(f) }}</button>
        <button type="button" class="form-tags__edit" :aria-label="`编辑${name}当前形态的名称和场次`" @click="startEdit">{{ editing ? '取消' : '改名/场次' }}</button>
      </div>
      <div v-if="editing" class="form-tags__editor">
        <el-input v-model.trim="draft.name" size="small" placeholder="形态名" maxlength="20" :aria-label="`${name} 形态名`" />
        <el-input v-model.trim="draft.scene_nos" size="small" placeholder="出现场次，如 1、3、5" :aria-label="`${name} 出现场次`" @keydown.enter.native="save" />
        <BaseButton variant="text" strong :loading="saving" @click="save">保存</BaseButton>
      </div>
      <span v-if="voice" class="form-tags__voice" :title="voice">{{ voice }}</span>
    </template>
  </div>
</template>

<script>
/**
 * 角色卡上的形态标签行：每个形态一个标签（形态名 · 出现场次），点标签切换卡片上显示的那张三视图；
 * “改名/场次”把当前形态的名称和场次改成可编辑，保存 emit('save', forms)（整份 forms，由页面调接口）。
 * 只有一个形态时显示“单形态”。音色描述（voice）放在标签行末尾。
 */
import { characterForms, formImage, formLabel, parseSceneNos, cleanForms } from './forms'

export default {
  name: 'CharacterFormTags',
  props: {
    item: { type: Object, required: true },
    /** 当前选中的形态下标 */
    value: { type: Number, default: 0 },
    saving: Boolean
  },
  data() {
    return { editing: false, draft: { name: '', scene_nos: '' } }
  },
  computed: {
    name() { return this.item.name },
    forms() { return characterForms(this.item) },
    single() { return this.forms.length <= 1 },
    voice() { return this.item.voice || '' }
  },
  watch: {
    value() { this.editing = false }
  },
  methods: {
    label: formLabel,
    hasImage(i) { return !!formImage(this.item, i) },
    startEdit() {
      if (this.editing) { this.editing = false; return }
      const f = this.forms[this.value] || this.forms[0]
      this.draft = { name: f.name || '', scene_nos: parseSceneNos(f.scene_nos).join('、') }
      this.editing = true
    },
    save() {
      const forms = cleanForms(this.forms.map((f, i) => (i === this.value ? { ...f, ...this.draft } : f)))
      this.$emit('save', forms, () => { this.editing = false })
    }
  }
}
</script>

<style scoped>
.form-tags { display: flex; flex-direction: column; gap: 6px; }
.form-tags__row { align-items: center; }
.form-tags__chip { min-height: 28px; padding: 0 10px; font-size: var(--fs-caption); border: 1px solid var(--line); }
.form-tags__chip.is-missing { color: var(--ink-muted); border-style: dashed; }
.form-tags__chip[aria-pressed="true"] { border-color: var(--ink); }
.form-tags__edit { border: 0; background: transparent; color: var(--ink-muted); font-size: var(--fs-caption); cursor: pointer; padding: 0 4px; }
.form-tags__edit:hover { color: var(--ink); text-decoration: underline; }
.form-tags__editor { display: grid; grid-template-columns: 1fr 1fr auto; gap: 6px; align-items: center; }
.form-tags__single, .form-tags__voice { font-size: var(--fs-caption); color: var(--ink-muted); }
.form-tags__voice { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
