<template>
  <div class="prompt-manage" style="padding:20px">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:20px">
      <el-button icon="el-icon-back" @click="$router.back()" size="small"
        style="background:rgba(255,255,255,0.08);border-color:rgba(255,255,255,0.15);color:#ddd">返回</el-button>
      <h2 style="margin:0">提示词管理</h2>
      <el-select v-model="filterType" placeholder="类型" @change="load" size="small" style="width:150px">
        <el-option label="全部" value=""></el-option>
        <el-option label="视频提示词" value="video"></el-option>
        <el-option label="拆分镜" value="split_shots"></el-option>
        <el-option label="生成小说" value="novel"></el-option>
        <el-option label="角色提取" value="character_extract"></el-option>
        <el-option label="道具提取" value="prop_extract"></el-option>
        <el-option label="场景提取" value="scene_extract"></el-option>
        <el-option label="资产提取(三合一)" value="asset_extract"></el-option>
        <el-option label="剧本转换" value="script_convert"></el-option>
        <el-option label="角色三视图" value="character_sheet"></el-option>
        <el-option label="提示词优化" value="prompt_optimize"></el-option>
      </el-select>
      <el-select v-model="filterCategory" placeholder="题材分类" @change="load" size="small" style="width:150px">
        <el-option label="全部" value=""></el-option>
        <el-option v-for="c in categories" :key="c" :label="c" :value="c"></el-option>
      </el-select>
      <el-button type="primary" size="small" @click="showDialog()">新建提示词</el-button>
    </div>

    <el-table :data="list" size="small" :header-cell-style="{background:'#1a1a2e',color:'#aaa'}" :cell-style="{background:'#16162a',color:'#ddd'}">
      <el-table-column prop="name" label="名称" width="160"></el-table-column>
      <el-table-column prop="version" label="版本" width="70"></el-table-column>
      <el-table-column prop="type" label="类型" width="120"></el-table-column>
      <el-table-column label="分类" width="100">
        <template slot-scope="s">
          <el-tag size="mini" :type="s.row.category === '通用' ? 'info' : 'warning'">{{ s.row.category || '通用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="默认" width="70">
        <template slot-scope="s">
          <el-tag v-if="s.row.is_default" type="success" size="mini">默认</el-tag>
          <el-button v-else size="mini" text @click="setDefault(s.row)">设默认</el-button>
        </template>
      </el-table-column>
      <el-table-column prop="content" label="内容" show-overflow-tooltip></el-table-column>
      <el-table-column label="操作" width="130">
        <template slot-scope="s">
          <el-button size="mini" @click="showDialog(s.row)">编辑</el-button>
          <el-button size="mini" type="danger" plain @click="del(s.row)">删</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog :visible.sync="dlg" :title="editing._id ? '编辑' : '新建'" width="600px">
      <el-form label-width="80px" size="small">
        <el-form-item label="名称"><el-input v-model="editing.name"></el-input></el-form-item>
        <el-form-item label="版本"><el-input v-model="editing.version" placeholder="v1.0"></el-input></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="editing.type">
            <el-option label="视频" value="video"></el-option>
            <el-option label="拆分镜" value="split_shots"></el-option>
            <el-option label="小说" value="novel"></el-option>
            <el-option label="角色提取" value="character_extract"></el-option>
            <el-option label="道具提取" value="prop_extract"></el-option>
            <el-option label="场景提取" value="scene_extract"></el-option>
            <el-option label="资产提取(三合一)" value="asset_extract"></el-option>
            <el-option label="剧本转换" value="script_convert"></el-option>
            <el-option label="角色三视图" value="character_sheet"></el-option>
            <el-option label="提示词优化" value="prompt_optimize"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="分类">
          <el-select v-model="editing.category" style="width:100%">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="内容">
          <el-input v-model="editing.content" type="textarea" :rows="10"></el-input>
        </el-form-item>
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
export default {
  data() {
    return { filterType: '', filterCategory: '', categories: [], list: [], dlg: false, editing: {} }
  },
  created() { this.load() },
  methods: {
    async load() {
      const r = await api.prompt.list(this.filterType, this.filterCategory)
      this.list = r.data || []
      this.categories = r.categories || []
    },
    showDialog(row) {
      this.editing = row
        ? { ...row }
        : { name: '', version: 'v1.0', type: this.filterType, category: '通用', content: '' }
      this.dlg = true
    },
    async save() {
      if (this.editing._id) await api.prompt.update(this.editing._id, this.editing)
      else await api.prompt.create(this.editing)
      this.dlg = false; this.load()
    },
    async setDefault(row) {
      await api.prompt.update(row._id, { is_default: true })
      this.load()
    },
    async del(row) {
      await api.prompt.delete(row._id)
      this.load()
    }
  }
}
</script>
