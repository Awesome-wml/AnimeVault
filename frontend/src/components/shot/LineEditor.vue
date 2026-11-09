<template>
  <div class="line-editor">
    <div v-for="(ln, i) in draft" :key="i" class="line-editor__row">
      <div class="form-row">
        <FormField :label="`第 ${i + 1} 句说话人`">
          <el-select v-model="ln.speaker" filterable allow-create @change="onSpeaker(ln)">
            <el-option v-for="name in speakers" :key="name" :label="name" :value="name"></el-option>
          </el-select>
        </FormField>
        <FormField :label="`第 ${i + 1} 句类型`">
          <el-select v-model="ln.kind" @change="onKind(ln)">
            <el-option v-for="k in kinds" :key="k.value" :label="k.label" :value="k.value"></el-option>
          </el-select>
        </FormField>
      </div>
      <FormField :label="`第 ${i + 1} 句台词`" :hint="range(ln)">
        <el-input v-model="ln.text" type="textarea" :autosize="{ minRows: 1, maxRows: 4 }" @change="emit" />
      </FormField>
      <div class="inline-actions">
        <BaseButton variant="text" @click="remove(i)">删除这句</BaseButton>
      </div>
    </div>
    <div class="inline-actions">
      <BaseButton variant="text" @click="add">加一句</BaseButton>
    </div>
  </div>
</template>

<script>
/**
 * 逐句编辑视频段台词：说话人、类型（对白/旁白/心声/画外音）、台词。
 * 改完（失焦/选择）即 emit('change', lines)；起止秒由后端按朗读时长重新校正后回填。
 */
import { NARRATOR } from './status'
import { LINE_KINDS, timeRange } from './segment'

export default {
  name: 'LineEditor',
  props: {
    lines: { type: Array, default: () => [] },
    speakers: { type: Array, default: () => [] }
  },
  data() {
    return { draft: [], kinds: LINE_KINDS }
  },
  watch: {
    lines: { immediate: true, handler(v) { this.draft = (v || []).map(ln => ({ ...ln })) } }
  },
  methods: {
    range: timeRange,
    onSpeaker(ln) {
      if (ln.speaker === NARRATOR) ln.kind = 'narration'
      else if (ln.kind === 'narration') ln.kind = 'onscreen'
      this.emit()
    },
    onKind(ln) {
      if (ln.kind === 'narration') ln.speaker = NARRATOR
      this.emit()
    },
    add() {
      this.draft.push({ speaker: NARRATOR, kind: 'narration', text: '', start: null, end: null })
    },
    remove(i) {
      this.draft.splice(i, 1)
      this.emit()
    },
    emit() {
      this.$emit('change', this.draft.filter(ln => (ln.text || '').trim()).map(ln => ({ ...ln })))
    }
  }
}
</script>

<style scoped>
.line-editor { display: flex; flex-direction: column; gap: 14px; }
.line-editor__row { display: flex; flex-direction: column; gap: 8px; padding-bottom: 12px; border-bottom: 1px solid var(--line); }
</style>
