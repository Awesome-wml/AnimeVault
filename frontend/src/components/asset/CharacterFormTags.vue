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
          :title="tip(f, i)"
          @click="$emit('input', i)"
        >{{ hasScript ? label(f) : (f.name || '默认') }}</button>
        <button type="button" class="form-tags__edit" :aria-label="`编辑${name}当前形态的名称和场次`" @click="startEdit">{{ editing ? '取消' : (hasScript ? '改名/场次' : '改名') }}</button>
      </div>
      <p v-if="!hasScript" class="form-tags__hint">每段用哪个形态，拆分镜时会按剧情自动定，在分镜详情的“这一段的造型”里可以改。</p>
      <div v-if="editing" class="form-tags__editor">
        <el-input v-model.trim="draft.name" size="small" placeholder="形态名" maxlength="20" :aria-label="`${name} 形态名`" />
        <el-input v-if="hasScript" v-model.trim="draft.scene_nos" size="small" placeholder="用在剧本第几场，如 1、3、10-20" :aria-label="`${name} 出现场次`" @keydown.enter.native="save" />
        <BaseButton variant="text" strong :loading="saving" @click="save">保存</BaseButton>
      </div>
    </template>
  </div>
</template>

<script>
/**
 * 角色卡上的形态标签行：每个形态一个标签：有剧本时是“形态名 · 第几场”（场次 = 剧本的场次号，连续的并成区间），没有剧本只显示形态名，点标签切换卡片上显示的那张三视图；
 * “改名/场次”把当前形态的名称和场次改成可编辑，保存 emit('save', forms)（整份 forms，由页面调接口）。
 * 只有一个形态时不显示。
 */
import { characterForms, formImage, formLabel, sceneNosText, sceneNosInput, cleanForms } from './forms'

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
    /** 形态按“剧本第几场”切换；没有剧本时场次号对不上任何东西，不显示也不让填 */
    hasScript() {
      const st = this.$store && this.$store.state.project
      return !!(st && st.counts && st.counts.scripts)
    }
  },
  watch: {
    value() { this.editing = false }
  },
  methods: {
    label: formLabel,
    hasImage(i) { return !!formImage(this.item, i) },
    /** 悬停提示：完整场次 + 穿搭（标签上场次太多时只显示前几组） */
    tip(f, i) {
      return [this.hasScript ? `用在剧本${sceneNosText(f.scene_nos, 0)}` : '', f.outfit || '', this.hasImage(i) ? '' : '（还没有三视图）'].filter(Boolean).join('\n')
    },
    startEdit() {
      if (this.editing) { this.editing = false; return }
      const f = this.forms[this.value] || this.forms[0]
      this.draft = { name: f.name || '', scene_nos: sceneNosInput(f.scene_nos) }
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
.form-tags__chip { min-height: 28px; max-width: 100%; padding: 2px 10px; text-align: left; line-height: 1.4; font-size: var(--fs-caption); border: 1px solid var(--line); }
.form-tags__chip.is-missing { color: var(--ink-muted); border-style: dashed; }
.form-tags__chip[aria-pressed="true"] { border-color: var(--ink); }
.form-tags__edit { border: 0; background: transparent; color: var(--ink-muted); font-size: var(--fs-caption); cursor: pointer; padding: 0 4px; }
.form-tags__edit:hover { color: var(--ink); text-decoration: underline; }
.form-tags__hint { margin: 0; font-size: var(--fs-caption); color: var(--ink-muted); line-height: 1.5; }
.form-tags__editor { display: grid; grid-template-columns: repeat(auto-fit, minmax(90px, 1fr)); gap: 6px; align-items: center; }
</style>
