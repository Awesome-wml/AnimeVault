<template>
  <div class="dialogue-editor">
    <div v-for="(d, i) in value" :key="i" class="dialogue-editor__row">
      <FormField :label="`第 ${i + 1} 句说话人`" class="dialogue-editor__speaker">
        <el-select :value="d.speaker" filterable allow-create default-first-option @change="v => set(i, 'speaker', v)">
          <el-option v-for="name in speakerOptions" :key="name" :label="name" :value="name"></el-option>
        </el-select>
      </FormField>
      <FormField :label="`第 ${i + 1} 句${d.speaker === NARRATOR ? '旁白' : '台词'}`" class="dialogue-editor__line">
        <el-input :value="d.line" type="textarea" :autosize="{ minRows: 1, maxRows: 4 }" @input="v => set(i, 'line', v)" />
      </FormField>
      <div class="inline-actions dialogue-editor__ops">
        <BaseButton variant="text" :disabled="i === 0" :aria-label="`第 ${i + 1} 句上移`" @click="move(i, -1)">上移</BaseButton>
        <BaseButton variant="text" :disabled="i === value.length - 1" :aria-label="`第 ${i + 1} 句下移`" @click="move(i, 1)">下移</BaseButton>
        <BaseButton variant="text" :aria-label="`删除第 ${i + 1} 句`" @click="remove(i)">删除</BaseButton>
      </div>
    </div>
    <p v-if="!value.length" class="note">这一场还没有台词或旁白。</p>
    <div class="inline-actions">
      <BaseButton variant="text" strong @click="add">加一句</BaseButton>
    </div>
  </div>
</template>

<script>
/**
 * 场次台词 / 旁白逐条编辑：说话人（角色名或“旁白”，可输入新名字）+ 台词；可增删、上下移。
 * v-model 为 [{ speaker, line }]；空台词由后端保存时丢弃。
 */
import { NARRATOR } from './scene'

export default {
  name: 'DialogueEditor',
  props: {
    value: { type: Array, default: () => [] },
    speakers: { type: Array, default: () => [] }
  },
  data() {
    return { NARRATOR }
  },
  computed: {
    speakerOptions() {
      const names = [NARRATOR, ...this.speakers, ...this.value.map(d => d.speaker)]
      return [...new Set(names.filter(Boolean))]
    }
  },
  methods: {
    emit(list) { this.$emit('input', list) },
    set(i, key, v) { this.emit(this.value.map((d, j) => (j === i ? { ...d, [key]: v } : d))) },
    add() {
      const last = this.value[this.value.length - 1]
      this.emit([...this.value, { speaker: last ? last.speaker : NARRATOR, line: '' }])
    },
    remove(i) { this.emit(this.value.filter((_, j) => j !== i)) },
    move(i, step) {
      const list = this.value.slice()
      const [d] = list.splice(i, 1)
      list.splice(i + step, 0, d)
      this.emit(list)
    }
  }
}
</script>

<style scoped>
.dialogue-editor { display: flex; flex-direction: column; gap: 12px; }
.dialogue-editor__row {
  display: grid;
  grid-template-columns: minmax(120px, 160px) 1fr;
  gap: 4px 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--line);
}
.dialogue-editor__ops { grid-column: 2; }
@media (max-width: 640px) {
  .dialogue-editor__row { grid-template-columns: 1fr; }
  .dialogue-editor__ops { grid-column: 1; }
}
</style>
