<template>
  <ProjectPage title="风格">
    <EmptyState title="风格页二期实现" description="现在可以在角色、场景、道具页顶部的“项目风格”里选择题材风格，它会贯穿提取、三视图、拆分镜和文生图。">
      <template #actions>
        <BaseButton :to="`/projects/${pid}/characters`">去设置项目风格</BaseButton>
      </template>
    </EmptyState>
  </ProjectPage>
</template>

<script>
import ProjectPage from './ProjectPage.vue'

export default {
  name: 'StylePage',
  components: { ProjectPage },
  props: { pid: { type: String, required: true }, ep: { type: String, default: '' } }
}
</script>
