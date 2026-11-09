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
    :placeholder="`未生成${conf.imageName}`"
    clamp
    @open="$emit('edit', item)"
  >
    <FormField v-if="conf.hasVoice" label="音色">
      <el-select :value="item.voice_name" placeholder="选择音色" filterable @change="v => $emit('voice', item, v)">
        <el-option v-for="o in voiceOptions(voices, item.voice_name)" :key="o.value" :label="o.label" :value="o.value" :disabled="o.disabled"></el-option>
      </el-select>
    </FormField>

    <template #footer>
      <div class="inline-actions">
        <BaseButton variant="text" strong :loading="busy" @click="$emit('generate', item)">{{ busy ? '生成中' : conf.generateText }}</BaseButton>
        <MoreMenu :items="menu" :label="`${item.name} 的更多操作`" @command="onCommand" />
      </div>
      <StatusText :status="item.image_path ? 'asset_has_image' : 'asset_no_image'" :text="(item.image_path ? '已有' : '缺') + conf.imageName" class="caption" />
    </template>
  </AssetCard>
</template>

<script>
/**
 * 一张资产卡片：图 + 名称 + 一行描述 + 状态；主操作“生成参考图/三视图”，
 * 上传、编辑、删除收进“更多”。点卡片也是编辑。角色额外带音色选择。
 */
import { api } from '@/api'
import { assetKind, assetBadge } from './kinds'
import { voiceOptions } from '@/components/voice/voices'

export default {
  name: 'AssetItem',
  props: {
    kind: { type: String, required: true },
    item: { type: Object, required: true },
    voices: { type: Array, default: () => [] },
    busy: Boolean
  },
  computed: {
    conf() { return assetKind(this.kind) },
    badge() { return assetBadge(this.kind, this.item) },
    src() { return this.item.image_path ? api.staticUrl(this.item.image_path) : '' },
    menu() {
      return [
        { command: 'upload', label: this.conf.uploadText },
        { command: 'edit', label: '编辑' },
        { command: 'delete', label: '删除', danger: true }
      ]
    }
  },
  methods: {
    voiceOptions,
    onCommand(cmd) { this.$emit(cmd, this.item) }
  }
}
</script>
