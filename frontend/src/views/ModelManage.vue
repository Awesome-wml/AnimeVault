<template>
  <div class="model-manage" style="padding:20px">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:20px">
      <el-button icon="el-icon-back" @click="$router.back()" size="small"
        style="background:rgba(255,255,255,0.08);border-color:rgba(255,255,255,0.15);color:#ddd">返回</el-button>
      <h2 style="margin:0">模型管理</h2>
      <el-button type="primary" size="small" @click="showDialog()">新建模型</el-button>
    </div>

    <el-table :data="list" size="small" :header-cell-style="{background:'#1a1a2e',color:'#aaa'}" :cell-style="{background:'#16162a',color:'#ddd'}">
      <el-table-column prop="name" label="名称" width="180"></el-table-column>
      <el-table-column label="供应商" width="110">
        <template slot-scope="s">
          <el-tag size="mini" :type="providerTagType(s.row.provider)">{{ providerLabel(s.row.provider) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="model" label="模型 ID" width="170"></el-table-column>
      <el-table-column prop="base_url" label="接入地址" show-overflow-tooltip></el-table-column>
      <el-table-column label="Key 数" width="80" align="center">
        <template slot-scope="s">
          <el-tag v-if="keyCount(s.row) > 0" type="success" size="mini">{{ keyCount(s.row) }}</el-tag>
          <el-tag v-else type="info" size="mini">复用全局</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="默认" width="70">
        <template slot-scope="s">
          <el-tag v-if="s.row.is_default" type="success" size="mini">默认</el-tag>
          <el-button v-else size="mini" text @click="setDefault(s.row)">设默认</el-button>
        </template>
      </el-table-column>
      <el-table-column prop="remark" label="备注" show-overflow-tooltip></el-table-column>
      <el-table-column label="操作" width="130">
        <template slot-scope="s">
          <el-button size="mini" @click="showDialog(s.row)">编辑</el-button>
          <el-button size="mini" type="danger" plain @click="del(s.row)">删</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog :visible.sync="dlg" :title="editing._id ? '编辑模型' : '新建模型'" width="600px">
      <el-form label-width="90px" size="small">
        <el-form-item label="供应商">
          <el-select v-model="editing.provider" @change="onProviderChange" style="width:100%">
            <el-option v-for="(p, key) in PROVIDERS" :key="key" :label="p.label" :value="key"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="名称"><el-input v-model="editing.name" placeholder="如：智谱 GLM-4.7 Flash"></el-input></el-form-item>
        <el-form-item label="模型 ID"><el-input v-model="editing.model" placeholder="如：glm-4.7-flash / deepseek-chat / gpt-4o-mini"></el-input></el-form-item>
        <el-form-item label="接入地址">
          <el-input v-model="editing.base_url" placeholder="https://..."></el-input>
        </el-form-item>
        <el-form-item label="API 密钥">
          <el-input v-model="keysText" type="textarea" :rows="3"
            placeholder="一行一个 Key，可填多个自动轮询分流；留空则复用账号全局密钥"></el-input>
          <div style="color:#909399;font-size:12px;margin-top:4px">多个 Key 时，提取/生成请求会自动轮换使用，分散限流与额度。</div>
        </el-form-item>
        <el-form-item label="备注"><el-input v-model="editing.remark" type="textarea" :rows="2"></el-input></el-form-item>
      </el-form>
      <div slot="footer">
        <el-button @click="dlg=false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </div>
    </el-dialog>
  </div>
</template>

<script>
import { api } from '@/api'

const PROVIDERS = {
  zhipu: { label: '智谱 GLM', base_url: 'https://open.bigmodel.cn/api/paas/v4' },
  deepseek: { label: 'DeepSeek', base_url: 'https://api.deepseek.com/v1' },
  openai: { label: 'OpenAI', base_url: 'https://api.openai.com/v1' },
  gemini: { label: 'Google Gemini', base_url: 'https://generativelanguage.googleapis.com/v1beta/openai/' },
  other: { label: '其他', base_url: '' }
}

export default {
  data() {
    return { PROVIDERS, list: [], dlg: false, editing: {}, keysText: '' }
  },
  created() { this.load() },
  methods: {
    providerLabel(p) {
      return (this.PROVIDERS[p] || {}).label || '其他'
    },
    providerTagType(p) {
      return { zhipu: '', deepseek: 'success', openai: 'primary', gemini: 'warning', other: 'info' }[p] || 'info'
    },
    keyCount(row) {
      if (Array.isArray(row.api_keys)) return row.api_keys.filter(k => k && String(k).trim()).length
      return row.api_key ? 1 : 0
    },
    async load() {
      const r = await api.model.list()
      this.list = r.data || []
    },
    onProviderChange() {
      const p = this.PROVIDERS[this.editing.provider]
      if (p) this.editing.base_url = p.base_url
    },
    showDialog(row) {
      if (row) {
        this.editing = { ...row }
        const keys = Array.isArray(row.api_keys) ? row.api_keys : (row.api_key ? [row.api_key] : [])
        this.keysText = keys.join('\n')
      } else {
        this.editing = {
          name: '', provider: 'zhipu', model: '',
          base_url: this.PROVIDERS.zhipu.base_url, api_keys: [], remark: ''
        }
        this.keysText = ''
      }
      this.dlg = true
    },
    async save() {
      if (!this.editing.name || !this.editing.model) {
        this.$message.warning('请填写名称和模型 ID')
        return
      }
      const keys = this.keysText.split('\n').map(k => k.trim()).filter(Boolean)
      this.editing.api_keys = keys
      this.editing.api_key = keys[0] || ''
      if (this.editing._id) await api.model.update(this.editing._id, this.editing)
      else await api.model.create(this.editing)
      this.dlg = false
      this.load()
    },
    async setDefault(row) {
      await api.model.setDefault(row._id)
      this.load()
    },
    async del(row) {
      await api.model.delete(row._id)
      this.load()
    }
  }
}
</script>
