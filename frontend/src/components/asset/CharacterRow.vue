<template>
  <article class="char-row" :class="{ 'is-busy': busy }">
    <div class="char-row__thumb" role="button" :aria-label="`编辑${item.name}`" @click="$emit('edit', item)">
      <MediaFrame :src="src" ratio="3 / 4" fit="contain" :tone="item.id" :glyph="glyph" :alt="item.name" />
    </div>

    <div class="char-row__main">
      <div class="char-row__head">
        <span class="char-row__name" :title="item.name">{{ item.name }}</span>
        <span v-if="badge" class="char-row__badge">{{ badge }}</span>
        <el-select
          v-if="conf.hasVoice"
          :value="item.voice_name"
          size="small"
          class="char-row__voice"
          placeholder="音色"
          filterable
          @change="v => $emit('voice', item, v)"
        >
          <el-option v-for="o in voiceOptions(voices, item.voice_name)" :key="o.value" :label="o.label" :value="o.value" :disabled="o.disabled" />
        </el-select>
      </div>

      <CharacterFormTags
        v-model="form"
        :item="item"
        :saving="savingForms"
        @save="(forms, done) => $emit('save-forms', item, forms, done)"
      />

      <p v-if="currentOutfit" class="char-row__outfit" :title="currentOutfit">{{ currentOutfit }}</p>
    </div>

    <div class="char-row__actions">
      <BaseButton variant="text" strong :loading="busy" @click="$emit('generate', item, form)">{{ busy ? '生成中' : '生成三视图' }}</BaseButton>
      <BaseButton variant="text" @click="$emit('upload', item, form)">上传</BaseButton>
      <BaseButton variant="text" @click="$emit(hasRef ? 'clear-ref' : 'pick-ref', item, form)">{{ hasRef ? '清除参考图' : '参考图' }}</BaseButton>
      <BaseButton variant="text" @click="$emit('change-outfit', item, form)">变装</BaseButton>
      <BaseButton variant="text" @click="$emit('edit', item)">编辑</BaseButton>
      <BaseButton variant="text" class="char-row__danger" @click="$emit('delete', item)">删除</BaseButton>
    </div>
  </article>
</template>

<script>
/**
 * 角色一行式：左侧三视图缩略图，中间名字 / 重要度 / 音色 / 形态标签 / 当前穿搭，右侧操作平铺。
 * 操作不再收进“更多”：生成三视图、上传、参考图、变装、编辑、删除。
 * 变装 = 给该角色新增一套穿搭形态（forms 追加一项），由页面层提交整份 forms。
 */
import { assetKind, assetBadge } from './kinds'
import { characterForms, formImage } from './forms'
import { voiceOptions } from '@/components/voice/voices'
import CharacterFormTags from './CharacterFormTags.vue'

export default {
  name: 'CharacterRow',
  components: { CharacterFormTags },
  props: {
    item: { type: Object, required: true },
    voices: { type: Array, default: () => [] },
    busy: Boolean,
    savingForms: Boolean,
    hasRef: Boolean
  },
  data() {
    return { form: 0 }
  },
  computed: {
    conf() { return assetKind('character') },
    badge() { return assetBadge('character', this.item) },
    glyph() { return (this.item.name || '').slice(0, 1) },
    forms() { return characterForms(this.item) },
    currentForm() { return this.forms[this.form] || this.forms[0] || {} },
    currentOutfit() { return this.currentForm.outfit || '' },
    src() { return formImage(this.item, this.form) }
  },
  watch: {
    'item.forms'(forms) {
      if (Array.isArray(forms) && this.form >= forms.length) this.form = 0
    }
  },
  methods: {
    voiceOptions
  }
}
</script>

<style scoped>
.char-row {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr) auto;
  gap: 16px;
  align-items: center;
  padding: 14px 16px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
}
.char-row:hover { background: var(--hover-soft); }
.char-row.is-busy { opacity: .7; }

.char-row__thumb { width: 92px; cursor: pointer; }
.char-row__thumb :deep(.media-frame) { aspect-ratio: 3 / 4; }

.char-row__main { min-width: 0; display: flex; flex-direction: column; gap: 8px; }
.char-row__head { display: flex; align-items: center; gap: 10px; min-width: 0; }
.char-row__name {
  min-width: 0;
  font-family: var(--font-serif);
  font-size: 16px;
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.char-row__badge { flex: none; font-size: var(--fs-caption); color: var(--ink-muted); }
.char-row__voice { width: 132px; flex: none; }

.char-row__outfit {
  margin: 0;
  font-size: var(--fs-small);
  color: var(--ink-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.char-row__actions { display: flex; flex-wrap: wrap; justify-content: flex-end; align-items: center; gap: 2px; }
.char-row__danger { color: var(--seal); }
.char-row__danger:hover { color: var(--seal); }

@media (max-width: 960px) {
  .char-row { grid-template-columns: 76px minmax(0, 1fr); }
  .char-row__thumb { width: 76px; }
  .char-row__actions { grid-column: 1 / -1; justify-content: flex-start; }
}
</style>
