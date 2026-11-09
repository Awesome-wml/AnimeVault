<template>
  <article class="scene-card" :aria-label="title">
    <header class="scene-card__head">
      <h2 class="scene-card__title">{{ title }}</h2>
      <div v-if="!editing" class="inline-actions">
        <BaseButton variant="text" strong @click="startEdit">编辑</BaseButton>
        <MoreMenu :items="menu" :label="`${title} 的更多操作`" @command="onCommand" />
      </div>
    </header>

    <template v-if="!editing">
      <p v-if="scene.characters && scene.characters.length" class="scene-card__meta">出场：{{ scene.characters.join('、') }}</p>
      <p v-if="scene.action" class="scene-card__action">{{ scene.action }}</p>
      <ol v-if="scene.dialogues && scene.dialogues.length" class="scene-card__lines">
        <li v-for="(d, i) in scene.dialogues" :key="i" :class="{ 'is-narration': kindOf(d) === 'narration' }">
          <span class="scene-card__speaker">{{ d.speaker }}</span>
          <span v-if="kindOf(d) !== 'narration'" class="scene-card__kind" :class="`is-${kindOf(d)}`">{{ kindText(d) }}</span>{{ d.line }}
        </li>
      </ol>
      <p v-else class="note">这一场没有台词或旁白。</p>
      <p v-if="scene.beat" class="scene-card__beat">节拍：{{ scene.beat }}</p>
    </template>

    <div v-else class="form-stack">
      <div class="form-row">
        <FormField label="地点" required>
          <el-input v-model="draft.location" placeholder="如：林家演武场" />
        </FormField>
        <FormField label="时间 / 内外景">
          <el-input v-model="draft.time" placeholder="如：夜内" />
        </FormField>
      </div>
      <FormField label="出场角色" hint="可直接输入新名字后回车">
        <el-select v-model="draft.characters" multiple filterable allow-create default-first-option placeholder="选择或输入角色">
          <el-option v-for="name in characterOptions" :key="name" :label="name" :value="name"></el-option>
        </el-select>
      </FormField>
      <FormField label="动作 / 环境" hint="镜头看得见的动作、神态、环境与关键道具">
        <el-input v-model="draft.action" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" />
      </FormField>
      <div class="field-group">
        <span class="field-label">台词与旁白</span>
        <DialogueEditor v-model="draft.dialogues" :speakers="draft.characters" />
      </div>
      <div class="form-row">
        <FormField label="节拍 / 情绪">
          <el-input v-model="draft.beat" />
        </FormField>
        <FormField label="一句话概括">
          <el-input v-model="draft.summary" />
        </FormField>
      </div>
      <div class="inline-actions">
        <BaseButton :loading="saving" @click="save">保存这一场</BaseButton>
        <BaseButton variant="text" :disabled="saving" @click="editing = false">取消</BaseButton>
      </div>
    </div>
  </article>
</template>

<script>
/**
 * 一场剧本：查看（地点/时间、出场、动作、逐条台词及类型标签、节拍）与就地编辑。
 * 保存 emit('save', scene, fields) 由页面调接口；删除 emit('delete', scene)。
 * saving 由页面控制，保存成功后页面把 editing 关掉（ref.close()）。
 */
import DialogueEditor from './DialogueEditor.vue'
import { NARRATOR, sceneTitle, sceneDraft, cleanDraft, lineKind, kindLabel } from './scene'
import { toastWarning } from '@/utils/notify'

export default {
  name: 'SceneCard',
  components: { DialogueEditor },
  props: {
    scene: { type: Object, required: true },
    characters: { type: Array, default: () => [] },
    saving: Boolean
  },
  data() {
    return { NARRATOR, editing: false, draft: null }
  },
  computed: {
    title() { return sceneTitle(this.scene) },
    menu() { return [{ command: 'delete', label: '删除这一场', danger: true }] },
    characterOptions() { return [...new Set([...this.characters, ...(this.draft ? this.draft.characters : [])])] }
  },
  methods: {
    startEdit() {
      this.draft = sceneDraft(this.scene)
      this.editing = true
    },
    close() { this.editing = false },
    kindOf(d) { return lineKind(d) },
    kindText(d) { return kindLabel(lineKind(d)) },
    save() {
      const fields = cleanDraft(this.draft)
      if (!fields.location) { toastWarning('请填写地点'); return }
      this.$emit('save', this.scene, fields)
    },
    onCommand(cmd) { if (cmd === 'delete') this.$emit('delete', this.scene) }
  }
}
</script>

<style scoped>
.scene-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 18px 0 20px;
  border-bottom: 1px solid var(--line);
}
.scene-card__head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.scene-card__title { margin: 0; font-family: var(--font-serif); font-size: 18px; font-weight: 600; }
.scene-card__meta, .scene-card__beat { margin: 0; font-size: var(--fs-small); color: var(--ink-muted); }
.scene-card__action { margin: 0; line-height: 1.7; }
.scene-card__lines { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 4px; line-height: 1.7; }
.scene-card__lines .is-narration { color: var(--ink-muted); }
.scene-card__speaker { display: inline-block; min-width: 4em; margin-right: 8px; font-weight: 600; color: var(--ink); }
.scene-card__kind {
  display: inline-block;
  margin-right: 8px;
  padding: 0 6px;
  border: 1px solid var(--line);
  border-radius: 4px;
  font-size: var(--fs-small);
  line-height: 1.6;
  color: var(--ink-muted);
}
.scene-card__kind.is-inner, .scene-card__kind.is-offscreen { font-style: italic; }
</style>
