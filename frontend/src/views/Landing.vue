<template>
  <div class="landing">
    <section class="landing__hero">
      <InkStage variant="hero" />
      <header class="landing__bar">
        <strong class="landing__brand serif">DongAI</strong>
        <router-link to="/login" class="landing__login">登录</router-link>
      </header>
      <main class="landing__main">
        <div class="landing__titles">
          <h1 class="landing__title vt serif ink-in-1">把小说，<br>拍成短剧。</h1>
          <p class="landing__verse vt serif ink-in-2">暴雨如注，雷声轰鸣。</p>
        </div>
        <div class="landing__cta ink-in-3">
          <Seal text="戏" />
          <router-link to="/register" class="landing__start serif">开始创作</router-link>
        </div>
      </main>
    </section>

    <section class="landing__steps">
      <h2 class="landing__steps-title serif">从文字，到画面</h2>
      <div class="card-grid">
        <article v-for="step in steps" :key="step.no" class="landing__step">
          <div class="landing__step-no serif">{{ step.no }}</div>
          <h3 class="landing__step-title serif">{{ step.title }}</h3>
          <p class="muted">{{ step.desc }}</p>
        </article>
      </div>
    </section>

    <footer class="landing__footer">
      <div class="landing__footer-inner">
        <span v-for="item in footer" :key="item">{{ item }}</span>
      </div>
    </footer>
  </div>
</template>

<script>
import InkStage from '@/components/ink/InkStage.vue'

export default {
  name: 'LandingPage',
  components: { InkStage },
  data() {
    return {
      steps: [
        { no: '一', title: '贴小说', desc: '也可以让 AI 先写一篇。角色、道具、场景和分镜会自动整理出来。' },
        { no: '二', title: '定人物', desc: '为角色生成三视图、绑定音色，让人物在每一镜里都认得出。' },
        { no: '三', title: '出片子', desc: '逐镜生成视频，不满意就重做这一镜，再导出到剪映精修。' }
      ],
      // 设计稿占位，待产品提供正式信息
      footer: ['[ 公司名称 ]', '[ ICP 备案号 ]', '[ 用户协议 ]', '[ 隐私政策 ]']
    }
  }
}
</script>

<style scoped>
.landing { font-size: 15px; line-height: 1.8; }

.landing__hero {
  position: relative;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.landing__hero > :not(.ink-stage) { position: relative; z-index: 1; }

.landing__bar { display: flex; align-items: center; gap: 20px; padding: 24px 48px; }
.landing__brand { flex: 1; font-size: 20px; }
.landing__login { display: flex; align-items: center; min-height: 44px; }

.landing__main {
  flex: 1;
  padding: 12px 48px 56px clamp(48px, 12vw, 190px);
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 28px;
}
.landing__titles { display: flex; align-items: flex-start; gap: 30px; }
.landing__title {
  font-size: 54px;
  font-weight: 700;
  line-height: 1.5;
  height: min(52vh, 470px);
}
.landing__verse {
  margin-top: 6px;
  font-size: 15px;
  line-height: 2;
  color: var(--ink-muted);
  height: min(46vh, 400px);
}
.landing__cta { display: flex; align-items: center; gap: 18px; }
.landing__start {
  display: inline-flex;
  align-items: center;
  min-height: 44px;
  font-size: 17px;
  text-decoration: underline;
  text-underline-offset: 6px;
}

.landing__steps {
  max-width: 1040px;
  margin: 0 auto;
  padding: 96px 48px 112px;
  display: flex;
  flex-direction: column;
  gap: 44px;
}
.landing__steps-title { font-size: var(--fs-title); font-weight: 700; }
.landing__step { display: flex; flex-direction: column; gap: 6px; padding-top: 18px; border-top: 1px solid var(--line); }
.landing__step-no { font-size: var(--fs-body); color: var(--ink-muted); }
.landing__step-title { font-size: 22px; font-weight: 700; }

.landing__footer { border-top: 1px solid var(--line); }
.landing__footer-inner {
  max-width: 1040px;
  margin: 0 auto;
  padding: 24px 48px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 24px;
  font-size: var(--fs-small);
  color: var(--ink-muted);
}

@media (max-width: 760px) {
  .landing__bar { padding: 16px 20px; }
  .landing__main { padding: 12px 20px 40px 32px; }
  .landing__title { font-size: 38px; }
  .landing__steps { padding: 64px 20px 72px; gap: 32px; }
  .landing__footer-inner { padding: 20px; }
}
</style>
