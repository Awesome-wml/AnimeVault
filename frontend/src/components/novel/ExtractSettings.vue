<template>
  <section class="section">
    <h2 class="section-title">提取设置</h2>
    <FormField label="资产提取 · 模型">
      <ModelSelect :value="value.extractModel" :groups="modelGroups" @input="v => set('extractModel', v)" />
    </FormField>
    <FormField label="资产提取 · 提示词">
      <PromptSelect :value="value.extractPrompt" :prompts="prompts.extract" @input="v => set('extractPrompt', v)" />
    </FormField>
    <FormField label="拆分镜 · 模型">
      <ModelSelect :value="value.splitModel" :groups="modelGroups" @input="v => set('splitModel', v)" />
    </FormField>
    <FormField label="拆分镜 · 提示词">
      <PromptSelect :value="value.splitPrompt" :prompts="prompts.split" @input="v => set('splitPrompt', v)" />
    </FormField>
    <p class="note">一键提取会依次生成角色、道具、场景和分镜{{ episodeName ? `，分镜写入“${episodeName}”` : '' }}。</p>
    <p v-if="scriptCount" class="note">
      已有剧本 {{ scriptCount }} 场：资产提取和拆分镜都基于剧本场次，不再用左边的小说正文。
      <router-link :to="scriptLink">查看剧本</router-link>
    </p>
  </section>
</template>

<script>
/** 一键提取 / 拆分镜用的模型与提示词。v-model 为 { extractModel, extractPrompt, splitModel, splitPrompt }。 */
import ModelSelect from './ModelSelect.vue'
import PromptSelect from './PromptSelect.vue'

export default {
  name: 'ExtractSettings',
  components: { ModelSelect, PromptSelect },
  props: {
    value: { type: Object, required: true },
    modelGroups: { type: Array, default: () => [] },
    prompts: { type: Object, required: true },
    episodeName: { type: String, default: '' },
    /** 剧本场次数（>0 时提取基于剧本）与剧本页链接 */
    scriptCount: { type: Number, default: 0 },
    scriptLink: { type: [String, Object], default: '' }
  },
  methods: {
    set(key, v) { this.$emit('input', { ...this.value, [key]: v }) }
  }
}
</script>
