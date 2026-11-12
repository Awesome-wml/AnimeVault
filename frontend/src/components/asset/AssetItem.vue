<template>
  <AssetCard
    :title="item.name"
    :meta="item.description || '还没有描述'"
    :badge="badge"
    :src="src"
    :ratio="conf.ratio"
    :fit="conf.fit"
    :tone="item.id"
    :glyph="kind === 'character' ? item.name.slice(0, 1) : ''"
    :placeholder="placeholder"
    clamp
    @open="$emit('edit', item)"
  >
    <CharacterFormTags
      v-if="kind === 'character'"
      v-model="form"
      :item="item"
      :saving="savingForms"
      @save="(forms, done) => $emit('save-forms', item, forms, done)"
    />
    <SceneViewTags
      v-if="kind === 'scene'"
      v-model="form"
      :item="item"
      :saving="savingForms"
      @save="(views, done) => $emit('save-forms', item, views, done)"
    />
    <FormField v-if="conf.hasVoice" label="音色">
      <el-select :value="item.voice_name" placeholder="选择音色" filterable @change="v => $emit('voice', item, v)">
        <el-option v-for="o in voiceOptions(voices, item.voice_name)" :key="o.value" :label="o.label" :value="o.value" :disabled="o.disabled"></el-option>
      </el-select>
    </FormField>

    <template #footer>
      <div class="inline-actions">
        <BaseButton variant="text" strong :loading="busy" @click="$emit('generate', item, form)">{{ busy ? '生成中' : conf.generateText }}</BaseButton>
        <MoreMenu :items="menu" :label="`${item.name} 的更多操作`" @command="onCommand" />
      </div>
      <StatusText :status="src ? 'asset_has_image' : 'asset_no_image'" :text="(src ? '已有' : '缺') + conf.imageName" class="caption" />
    </template>
  </AssetCard>
</template>

<script>
/**
 * 一张资产卡片：图 + 名称 + 一行描述 + 状态；主操作“生成参考图/三视图”，
 * 上传、编辑、删除收进“更多”。点卡片也是编辑。
 * 角色额外带形态标签行（CharacterFormTags：点标签切换该形态的三视图，可改形态名 / 场次）和音色选择；
 * 场景带视角标签行（SceneViewTags）和剧情状态；生成 / 上传 / 状态都针对当前选中的形态 / 视角（form 下标）。
 */
import { api } from '@/api'
import { assetKind, assetBadge } from './kinds'
import { formImage } from './forms'
import { viewImage } from './views'
import { voiceOptions } from '@/components/voice/voices'
import CharacterFormTags from './CharacterFormTags.vue'
import SceneViewTags from './SceneViewTags.vue'

export default {
  name: 'AssetItem',
  components: { CharacterFormTags, SceneViewTags },
  props: {
    kind: { type: String, required: true },
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
    conf() { return assetKind(this.kind) },
    badge() { return assetBadge(this.kind, this.item) },
    imagePath() {
      if (this.kind === 'character') return formImage(this.item, this.form)
      if (this.kind === 'scene') return viewImage(this.item, this.form)
      return this.item.image_path
    },
    src() { return this.imagePath ? api.staticUrl(this.imagePath) : '' },
    placeholder() { return `未生成${this.conf.imageName}` },
    menu() {
      const refItem = this.hasRef
        ? { command: 'clear-ref', label: '清除参考图' }
        : { command: 'pick-ref', label: '选参考图（可选）' }
      return [
        { command: 'upload', label: this.conf.uploadText },
        refItem,
        { command: 'edit', label: '编辑' },
        { command: 'delete', label: '删除', danger: true }
      ]
    }
  },
  watch: {
    /** 形态被删到比当前下标少时回到第一个 */
    'item.forms'(forms) {
      if (Array.isArray(forms) && this.form >= forms.length) this.form = 0
    },
    'item.views'(views) {
      if (Array.isArray(views) && this.form >= views.length) this.form = 0
    }
  },
  methods: {
    voiceOptions,
    onCommand(cmd) { this.$emit(cmd, this.item, this.form) }
  }
}
</script>
