<template>
  <div class="page">
    <PageHeader title="模型" subtitle="模型按用途分两类：对话模型用于写小说、转剧本、提取、拆分镜；出图模型用于资产图和四格分镜图。两类各有一个默认。">
      <template #actions>
        <BaseButton variant="text" @click="openGlobalKey">全局密钥</BaseButton>
        <BaseButton variant="primary" @click="openEdit()">新建模型</BaseButton>
      </template>
    </PageHeader>

    <div class="table-wrap">
      <el-table v-loading="loading" :data="shown" empty-text="还没有模型。新建一个，或直接使用全局密钥。">
        <el-table-column label="名称" min-width="160">
          <template slot-scope="{ row }">
            <div>{{ row.name }}</div>
            <div v-if="row.remark" class="cell-sub">{{ row.remark }}</div>
          </template>
        </el-table-column>
        <el-table-column label="供应商" min-width="110">
          <template slot-scope="{ row }">{{ providerLabel(row.provider) }}</template>
        </el-table-column>
        <el-table-column label="模型 ID" min-width="220">
          <template slot-scope="{ row }">
            <div>{{ modelIds(row).join('、') }}</div>
            <div v-if="row.base_url" class="cell-sub">{{ row.base_url }}</div>
          </template>
        </el-table-column>
        <el-table-column label="用途" width="90">
          <template slot-scope="{ row }">{{ kindLabel(row) }}</template>
        </el-table-column>
        <el-table-column label="Key" width="100">
          <template slot-scope="{ row }">
            <StatusText :status="keyCount(row) ? 'key_some' : 'key_none'" :n="keyCount(row)" />
          </template>
        </el-table-column>
        <el-table-column label="默认" width="100">
          <template slot-scope="{ row }">
            <StatusText v-if="row.is_default" status="default" :text="`${kindLabel(row)}默认`" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200">
          <template slot-scope="{ row }">
            <BaseButton variant="text" @click="openEdit(row)">编辑</BaseButton>
            <BaseButton v-if="!row.is_default" variant="text" @click="setDefault(row)">设为默认</BaseButton>
            <BaseButton variant="text" @click="remove(row)">删除</BaseButton>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 新建 / 编辑模型 -->
    <el-dialog append-to-body :title="editing._id ? '编辑模型' : '新建模型'" :visible.sync="editVisible" width="560px">
      <div class="form-stack">
        <FormField label="供应商" hint="选预设会自动填接入地址；也可以直接输入自定义供应商名。">
          <el-select v-model="editing.provider" filterable allow-create default-first-option placeholder="选择或输入" @change="onProviderChange">
            <el-option v-for="(p, key) in providers" :key="key" :label="p.label" :value="key" />
          </el-select>
        </FormField>
        <FormField label="名称" required>
          <el-input v-model="editing.name" placeholder="如：DeepSeek 对话模型" />
        </FormField>
        <FormField label="模型 ID" required hint="一行一个模型调用名，以供应商文档为准；第一个为默认。">
          <el-input v-model="modelsText" type="textarea" :rows="2" />
        </FormField>
        <FormField label="用途" hint="对话：写小说、转剧本、提取、拆分镜；出图：资产图、四格分镜图。自动 = 按模型 ID 的名字判断，判断错了在这里手动指定。">
          <el-select v-model="editing.model_type" placeholder="自动">
            <el-option v-for="m in modelTypes" :key="m.value" :label="m.label" :value="m.value" />
          </el-select>
        </FormField>
        <FormField label="接入地址" hint="OpenAI 兼容接口地址；第三方或代理可自行填写。">
          <el-input v-model="editing.base_url" placeholder="https://api.deepseek.com/v1" />
        </FormField>
        <FormField label="API 密钥" hint="一行一个，多个会轮流使用以分散限流；留空则复用全局密钥。">
          <el-input v-model="keysText" type="textarea" :rows="3" />
        </FormField>
        <FormField label="思考档位" hint="自动：按模型能力（可关思考的模型提取时关闭，始终思考的模型用低档）；接口报不支持时会自动降级。">
          <el-select v-model="editing.thinking_mode" placeholder="自动">
            <el-option v-for="m in thinkingModes" :key="m.value" :label="m.label" :value="m.value" />
          </el-select>
        </FormField>
        <FormField label="备注">
          <el-input v-model="editing.remark" type="textarea" :rows="2" />
        </FormField>
      </div>
      <template #footer>
        <BaseButton variant="text" @click="editVisible = false">取消</BaseButton>
        <BaseButton variant="primary" :loading="saving" @click="save">保存</BaseButton>
      </template>
    </el-dialog>

    <!-- 全局密钥（没有单独配置 Key 的模型都用它） -->
    <el-dialog append-to-body title="全局密钥" :visible.sync="keyVisible" width="520px">
      <div class="form-stack">
        <p class="muted small">
          {{ globalKey.has_api_key ? '已配置全局密钥。留空表示不修改。' : '还没有配置全局密钥。' }}
          密钥只保存在你的账号下。
        </p>
        <FormField label="API 密钥">
          <el-input v-model="globalKey.doubao_api_key" type="password" show-password autocomplete="off" />
        </FormField>
        <FormField label="接入地址">
          <el-input v-model="globalKey.doubao_base_url" placeholder="https://open.bigmodel.cn/api/paas/v4" />
        </FormField>
        <FormField label="模型">
          <el-input v-model="globalKey.doubao_model" placeholder="glm-4.5-flash" />
        </FormField>
      </div>
      <template #footer>
        <BaseButton variant="text" @click="keyVisible = false">取消</BaseButton>
        <BaseButton variant="primary" :loading="saving" @click="saveGlobalKey">保存</BaseButton>
      </template>
    </el-dialog>
  </div>
</template>

<script>
import { api } from '@/api'
import { confirmDelete } from '@/utils/dialogs'
import { toastError } from '@/utils/notify'

// 后端 /api/models 也会返回 providers，这里只做兜底
const FALLBACK_PROVIDERS = {
  zhipu: { label: '智谱 GLM', base_url: 'https://open.bigmodel.cn/api/paas/v4' },
  deepseek: { label: 'DeepSeek', base_url: 'https://api.deepseek.com/v1' },
  openai: { label: 'OpenAI', base_url: 'https://api.openai.com/v1' },
  gemini: { label: 'Google Gemini', base_url: 'https://generativelanguage.googleapis.com/v1beta/openai/' },
  volcengine: {
    label: '火山方舟（豆包 Seedream）',
    base_url: 'https://ark.cn-beijing.volces.com/api/v3',
    suggest_name: 'Seedream 5.5 出图',
    suggest_models: ['doubao-seedream-5-5-261028']
  },
  other: { label: '其他', base_url: '' }
}

// 后端 /api/models 返回 thinking_modes，这里只做兜底
const FALLBACK_THINKING_MODES = [
  { value: 'auto', label: '自动（按模型能力）' },
  { value: 'disabled', label: '关闭思考' },
  { value: 'low', label: '低（low）' },
  { value: 'high', label: '高（high）' }
]

const FALLBACK_MODEL_TYPES = [
  { value: 'auto', label: '自动（按模型名判断）' },
  { value: 'chat', label: '对话' },
  { value: 'image', label: '出图' }
]
const KIND_LABELS = { chat: '对话', image: '出图' }

const lines = text => (text || '').split('\n').map(s => s.trim()).filter(Boolean)

export default {
  name: 'ModelsSettings',
  data() {
    return {
      loading: false,
      saving: false,
      list: [],
      providers: FALLBACK_PROVIDERS,
      thinkingModes: FALLBACK_THINKING_MODES,
      modelTypes: FALLBACK_MODEL_TYPES,
      editVisible: false,
      editing: {},
      modelsText: '',
      keysText: '',
      keyVisible: false,
      globalKey: { has_api_key: false, doubao_api_key: '', doubao_base_url: '', doubao_model: '' }
    }
  },
  computed: {
    shown() { return this.list }
  },
  created() {
    this.load()
  },
  methods: {
    providerLabel(p) {
      if (!p) return '其他'
      return (this.providers[p] || {}).label || p
    },
    kindLabel(row) {
      const kinds = row.kinds && row.kinds.length ? row.kinds : [row.model_type === 'image' ? 'image' : 'chat']
      return kinds.map(k => KIND_LABELS[k] || k).join(' + ')
    },
    modelIds(row) {
      return row.models && row.models.length ? row.models : [row.model].filter(Boolean)
    },
    keyCount(row) {
      if (Array.isArray(row.api_keys)) return row.api_keys.filter(k => k && String(k).trim()).length
      return row.api_key ? 1 : 0
    },
    async load() {
      this.loading = true
      try {
        const r = await api.model.list()
        this.list = r.data || []
        if (r.providers) this.providers = r.providers
        if (r.thinking_modes) this.thinkingModes = r.thinking_modes
        if (r.model_types) this.modelTypes = r.model_types
      } catch (e) {
        this.list = []
      } finally {
        this.loading = false
      }
    },
    onProviderChange() {
      const p = this.providers[this.editing.provider]
      if (p && p.base_url) this.editing.base_url = p.base_url
      // 供应商带了建议的名称 / 模型 ID 时，空着的才填，不覆盖已经写的
      if (p && p.suggest_name && !(this.editing.name || '').trim()) this.editing.name = p.suggest_name
      if (p && p.suggest_models && !this.modelsText.trim()) this.modelsText = p.suggest_models.join('\n')
    },
    openEdit(row) {
      if (row) {
        this.editing = { thinking_mode: 'auto', model_type: 'auto', ...row }
        this.keysText = (Array.isArray(row.api_keys) ? row.api_keys : [row.api_key].filter(Boolean)).join('\n')
        this.modelsText = this.modelIds(row).join('\n')
      } else {
        this.editing = {
          name: '', provider: '', model: '', models: [], base_url: '', api_keys: [], remark: '', thinking_mode: 'auto', model_type: 'auto'
        }
        this.keysText = ''
        this.modelsText = ''
      }
      this.editVisible = true
    },
    async save() {
      const models = lines(this.modelsText)
      if (!this.editing.name || !models.length) {
        this.$message.warning('请填写名称和至少一个模型 ID')
        return
      }
      const keys = lines(this.keysText)
      const data = { ...this.editing, models, model: models[0], api_keys: keys, api_key: keys[0] || '' }
      this.saving = true
      try {
        if (data._id) await api.model.update(data._id, data)
        else await api.model.create(data)
        this.editVisible = false
        this.$message.success('已保存')
        this.load()
      } catch (e) {
        toastError(e)
      } finally {
        this.saving = false
      }
    },
    async setDefault(row) {
      try {
        await api.model.setDefault(row._id)
        this.load()
      } catch (e) { toastError(e) }
    },
    async remove(row) {
      if (!(await confirmDelete(`删除模型“${row.name}”？`))) return
      try {
        await api.model.delete(row._id)
        this.$message.success('已删除')
        this.load()
      } catch (e) { toastError(e) }
    },
    async openGlobalKey() {
      this.keyVisible = true
      try {
        const res = await api.auth.getConfig()
        const d = (res && res.data) || {}
        this.globalKey = {
          has_api_key: !!d.has_api_key,
          doubao_api_key: '',
          doubao_base_url: d.doubao_base_url || '',
          doubao_model: d.doubao_model || ''
        }
      } catch (e) { toastError(e) }
    },
    async saveGlobalKey() {
      const { doubao_api_key: key, doubao_base_url: baseUrl, doubao_model: model } = this.globalKey
      const data = { doubao_base_url: baseUrl, doubao_model: model }
      if (key) data.doubao_api_key = key
      this.saving = true
      try {
        await api.auth.updateConfig(data)
        this.$store.dispatch('setHasApiKey', this.globalKey.has_api_key || !!key)
        this.keyVisible = false
        this.$message.success('已保存')
      } catch (e) {
        toastError(e)
      } finally {
        this.saving = false
      }
    }
  }
}
</script>
