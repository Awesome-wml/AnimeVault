<template>
  <el-dialog :title="title" :visible="visible" width="560px" @update:visible="v => $emit('update:visible', v)" @open="reset">
    <div class="form-stack">
      <FormField label="名称" required>
        <el-input v-model.trim="form.name" :placeholder="`${conf.label}名称`" maxlength="40" />
      </FormField>
      <FormField v-if="conf.typeField" label="类型">
        <el-input v-model.trim="form.type" :placeholder="conf.typePlaceholder" maxlength="20" />
      </FormField>
      <template v-if="isCharacter">
        <FormField label="固定面部特征" hint="全剧不变的底层长相：骨相、脸型、眼型、发色、五官比例、年龄感；不写服装">
          <el-input v-model="form.face" type="textarea" :autosize="{ minRows: 3, maxRows: 8 }" placeholder="如：58岁女性，圆脸微胖，颧骨较高，眼尾下垂有岁月纹路，短发烫着小卷" />
        </FormField>
        <FormField label="形态" hint="只有剧情里换装 / 造型变化才拆多个形态；“出现场次”填剧本的场次号，这一场的视频就用这个形态的参考图（没有剧本时都用第一个形态）">
          <CharacterFormsEditor v-model="form.forms" />
        </FormField>
        <FormField label="声音设定" hint="成片里这个角色的人声照这份设定生成，每一段都用同一句；可以点角色页的“AI 设计音色”自动填，手改后不会被覆盖">
          <div class="voice-design">
            <el-select v-model="form.voice_design.pitch" placeholder="音高" clearable>
              <el-option v-for="o in pitches" :key="o" :label="`音高${o}`" :value="o" />
            </el-select>
            <el-select v-model="form.voice_design.pace" placeholder="语速" clearable>
              <el-option v-for="o in paces" :key="o" :label="`语速${o}`" :value="o" />
            </el-select>
            <el-input v-model.trim="form.voice_design.timbre" class="voice-design__wide" placeholder="音质，如：清亮带少年气" maxlength="12" />
            <el-input v-model.trim="form.voice_design.manner" class="voice-design__wide" placeholder="说话方式，如：咬字用力，句尾下压" maxlength="24" />
            <el-input v-model.trim="form.voice_design.habit" class="voice-design__wide" placeholder="说话习惯（可不填），如：开口前先顿半拍" maxlength="24" />
          </div>
        </FormField>
        <FormField label="音色备注" hint="提取角色时写的一句话；没有声音设定时用它">
          <el-input v-model.trim="form.voice" placeholder="如：28岁男性，低磁" maxlength="40" />
        </FormField>
      </template>
      <FormField v-else :label="conf.descLabel">
        <el-input v-model="form.description" type="textarea" :autosize="{ minRows: 4, maxRows: 10 }" :placeholder="conf.descPlaceholder" />
      </FormField>
      <template v-if="isScene">
        <FormField label="剧情状态" hint="剧情发生时该场景的关键物件状态，40 字内（如 石像已碎成一地石块）；环境描述要按这个状态写">
          <el-input v-model.trim="form.state_note" :maxlength="40" show-word-limit placeholder="如：窗户被撞碎、桌椅倒地；没有可留空" />
        </FormField>
        <FormField label="视角" hint="同一个空间的多个机位，每个视角出一张无人场景图；只有一个视角时保持默认即可">
          <SceneViewsEditor v-model="form.views" />
        </FormField>
      </template>
      <FormField v-if="conf.hasVoice" label="配音音色" hint="配音页逐句合成用的音色库">
        <el-select v-model="form.voice_name" placeholder="选择音色" filterable clearable>
          <el-option v-for="o in voiceOptions(voices, form.voice_name)" :key="o.value" :label="o.label" :value="o.value" :disabled="o.disabled"></el-option>
        </el-select>
      </FormField>
    </div>
    <template #footer>
      <BaseButton @click="$emit('update:visible', false)">取消</BaseButton>
      <BaseButton variant="primary" :loading="saving" @click="save">保存</BaseButton>
    </template>
  </el-dialog>
</template>

<script>
/**
 * 新建 / 编辑一个资产。item 为空时新建。保存成功 emit('saved')。
 * 角色：固定面部特征 + 形态列表（CharacterFormsEditor）+ 音色描述；description 由后端按 面部 + 第一形态穿搭 生成。
 * 场景：一段描述 + 剧情状态 + 视角列表（SceneViewsEditor）；道具：一段描述。
 */
import { assetKind } from './kinds'
import { formDrafts, cleanForms } from './forms'
import { viewDrafts, cleanViews } from './views'
import { voiceOptions, voiceDesignDraft, VOICE_PITCHES, VOICE_PACES, EMPTY_VOICE_DESIGN } from '@/components/voice/voices'
import { runAction, toastWarning } from '@/utils/notify'
import CharacterFormsEditor from './CharacterFormsEditor.vue'
import SceneViewsEditor from './SceneViewsEditor.vue'

export default {
  name: 'AssetFormDialog',
  components: { CharacterFormsEditor, SceneViewsEditor },
  props: {
    visible: Boolean,
    kind: { type: String, required: true },
    projectId: { type: String, required: true },
    item: { type: Object, default: null },
    voices: { type: Array, default: () => [] }
  },
  data() {
    return { saving: false, form: { name: '', type: '', description: '', face: '', forms: [], state_note: '', views: [], voice: '', voice_design: { ...EMPTY_VOICE_DESIGN }, voice_name: '' }, pitches: VOICE_PITCHES, paces: VOICE_PACES, voiceDesignWas: '' }
  },
  computed: {
    conf() { return assetKind(this.kind) },
    isCharacter() { return this.kind === 'character' },
    isScene() { return this.kind === 'scene' },
    title() { return this.item ? `编辑${this.conf.label}` : `添加${this.conf.label}` }
  },
  methods: {
    voiceOptions,
    reset() {
      const it = this.item || {}
      this.form = {
        name: it.name || '',
        type: (this.conf.typeField && it[this.conf.typeField]) || '',
        description: it.description || '',
        face: it.face || '',
        forms: this.item ? formDrafts(it) : [{ name: '', outfit: '', scene_nos: '', image_path: null }],
        state_note: it.state_note || '',
        views: this.isScene && this.item ? viewDrafts(it) : [{ name: '', camera: '', image_path: null }],
        voice: it.voice || '',
        voice_design: voiceDesignDraft(it),
        voice_name: it.voice_name || ''
      }
      this.voiceDesignWas = JSON.stringify(this.form.voice_design)
    },
    payload() {
      const data = { name: this.form.name }
      if (this.isCharacter) {
        data.face = this.form.face
        data.forms = cleanForms(this.form.forms)
        data.voice = this.form.voice
        // 声音设定改过才传：一传就记为手动设定，之后 AI 设计不再覆盖
        if (JSON.stringify(this.form.voice_design) !== this.voiceDesignWas) data.voice_design = { ...this.form.voice_design }
      } else {
        data.description = this.form.description
      }
      if (this.isScene) {
        data.state_note = this.form.state_note
        // 新建且没填任何视角：不传，后端按默认单视角
        const views = cleanViews(this.form.views)
        if (this.item || this.form.views.some(v => v.name || v.camera)) data.views = views
      }
      if (this.conf.typeField) data[this.conf.typeField] = this.form.type
      if (this.conf.hasVoice && this.form.voice_name) data.voice_name = this.form.voice_name
      return data
    },
    async save() {
      if (!this.form.name) { toastWarning('请填写名称'); return }
      const data = this.payload()
      if (this.isCharacter && !data.forms.length) { toastWarning('至少填一个形态的穿搭'); return }
      this.saving = true
      const ok = await runAction(
        () => (this.item
          ? this.conf.api.update(this.item.id, data)
          : this.conf.api.create({ project_id: this.projectId, ...data })),
        { success: this.item ? '已保存' : '已添加', error: '保存失败' }
      )
      this.saving = false
      if (ok) {
        this.$emit('update:visible', false)
        this.$emit('saved')
      }
    }
  }
}
</script>

<style scoped>
.voice-design { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.voice-design__wide { grid-column: 1 / -1; }
</style>
