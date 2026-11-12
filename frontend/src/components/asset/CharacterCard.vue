<template>
  <AssetCard
    :title="item.name"
    :meta="currentOutfit"
    :badge="badge"
    :src="src"
    ratio="16 / 9"
    fit="contain"
    :tone="item.id"
    :glyph="glyph"
    clamp
    @open="$emit('edit', item)"
  >
    <CharacterFormTags
      v-if="forms.length > 1"
      v-model="form"
      :item="item"
      :saving="savingForms"
      @save="(forms, done) => $emit('save-forms', item, forms, done)"
    />

    <FormField v-if="conf.hasVoice" label="音色">
      <el-select
        :value="item.voice_name"
        placeholder="选择音色"
        filterable
        @change="v => $emit('voice', item, v)"
      >
        <el-option v-for="o in voiceOptions(voices, item.voice_name)" :key="o.value" :label="o.label" :value="o.value" :disabled="o.disabled" />
      </el-select>
    </FormField>

    <template #footer>
      <div class="char-card__footer">
        <BaseButton variant="secondary" block :loading="busy" @click="$emit('generate', item, form)">
          {{ busy ? '生成中' : conf.generateText }}
        </BaseButton>
        <div class="char-card__sub">
          <BaseButton variant="text" @click="$emit('upload', item, form)">上传</BaseButton>
          <BaseButton variant="text" @click="$emit(hasRef ? 'clear-ref' : 'pick-ref', item, form)">{{ hasRef ? '已选参考' : '参考图' }}</BaseButton>
          <BaseButton variant="text" @click="$emit('change-outfit', item, form)">变装</BaseButton>
          <BaseButton variant="text" @click="$emit('edit', item)">编辑</BaseButton>
          <BaseButton variant="text" class="char-card__danger" @click="$emit('delete', item)">删除</BaseButton>
        </div>
      </div>
    </template>
  </AssetCard>
</template>

<script>
/**
 * 角色大图卡片（复用全站 AssetCard 外壳）：上半 16:9 横版三视图为主视觉，
 * 下面名字 / 形态标签 / 穿搭 / 音色；底部主操作整宽突出，次要操作规整一排弱化。
 * 变装 = 给该角色新增一套穿搭形态（forms 追加一项），由页面层提交整份 forms。
 */
import { api } from '@/api'
import { assetKind, assetBadge } from './kinds'
import { characterForms, formImage } from './forms'
import { voiceOptions } from '@/components/voice/voices'
import CharacterFormTags from './CharacterFormTags.vue'

export default {
  name: 'CharacterCard',
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
    currentOutfit() { return this.currentForm.outfit || this.item.description || '' },
    src() {
      const p = formImage(this.item, this.form)
      return p ? api.staticUrl(p) : ''
    }
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
.char-card__footer { display: flex; flex-direction: column; gap: 6px; width: 100%; }
.char-card__sub { display: flex; flex-wrap: wrap; align-items: center; gap: 2px 4px; }
.char-card__sub .base-btn--text { min-height: 28px; padding: 0 4px; font-size: var(--fs-caption); }
.char-card__danger { color: var(--ink-muted); }
.char-card__danger:hover { color: var(--seal); }
</style>
