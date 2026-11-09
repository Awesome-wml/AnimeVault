/**
 * 墨迹洇开着色器（docs/design/ink-reference.js 的 Stage() 移植）。
 * 由 InkStage.vue 按需动态加载，three.js 因此单独成块，只在产品首页/登录页下载。
 *
 * 画面：t 从 0 到 9 秒墨迹按噪声阈值洇开显出山水，之后只剩两条薄雾极慢地流动。
 */
import * as THREE from 'three'
import { painting, PAPER } from './painting'

export const REVEAL_SECONDS = 9
/** reduced-motion 或静态展示时画这一帧：墨迹已完全显现 */
export const FINAL_T = 30

const VS = 'varying vec2 vUv;void main(){vUv=uv;gl_Position=vec4(position.xy,0.,1.);}'
const FS = [
  'precision highp float;varying vec2 vUv;uniform sampler2D tex;uniform float t;uniform float aspect;uniform vec2 sc;uniform float ax;uniform vec3 paper;',
  'float h(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}',
  'float n(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);return mix(mix(h(i),h(i+vec2(1.,0.)),f.x),mix(h(i+vec2(0.,1.)),h(i+vec2(1.,1.)),f.x),f.y);}',
  'float fbm(vec2 p){float v=0.,a=.5;for(int i=0;i<5;i++){v+=a*n(p);p=p*2.03+vec2(7.,3.);a*=.5;}return v;}',
  'void main(){vec2 q=vec2(vUv.x*aspect,vUv.y);vec2 u=vec2(ax,0.)+(vUv-vec2(ax,0.))*sc;',
  'float x=clamp(t/' + REVEAL_SECONDS.toFixed(1) + ',0.,1.);float prog=1.-pow(1.-x,2.2);',
  'float th=fbm(q*2.4+1.7)*.62+(1.-vUv.y)*.14;',
  'float rv=smoothstep(th-.2,th+.2,prog*1.25-.18);',
  'vec3 c=texture2D(tex,u).rgb;vec3 col=mix(paper,c,rv);',
  'float m=fbm(vec2(q.x*1.25-t*.009,q.y*4.2+sin(t*.021)*.25));',
  'float band=smoothstep(.2,.0,abs(vUv.y-.34))+.7*smoothstep(.13,.0,abs(vUv.y-.58));',
  'col=mix(col,paper,clamp(band,0.,1.)*smoothstep(.38,.7,m)*.62*prog);',
  'gl_FragColor=vec4(col,1.);}'
].join('')

function hexToVec3(c) {
  const v = parseInt(c.slice(1), 16)
  return new THREE.Vector3((v >> 16 & 255) / 255, (v >> 8 & 255) / 255, (v & 255) / 255)
}

/**
 * @param {HTMLCanvasElement} canvas 渲染目标
 * @param {number} anchorX 画面横向锚点（1 = 靠右对齐，产品首页；.62 = 登录页左栏）
 * @returns {null | {start(reduce:boolean):void, stop():void, size():void, redraw():void, dispose():void}}
 */
export function createInkStage(canvas, anchorX) {
  let renderer
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: false })
  } catch (e) {
    return null
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5))

  const texture = new THREE.CanvasTexture(painting())
  texture.minFilter = THREE.LinearFilter
  const uniforms = {
    tex: { value: texture },
    t: { value: 0 },
    aspect: { value: 1 },
    sc: { value: new THREE.Vector2(1, 1) },
    ax: { value: anchorX },
    paper: { value: hexToVec3(PAPER) }
  }
  const geometry = new THREE.PlaneGeometry(2, 2)
  const material = new THREE.ShaderMaterial({ uniforms, vertexShader: VS, fragmentShader: FS, depthTest: false })
  const scene = new THREE.Scene()
  const camera = new THREE.Camera()
  scene.add(new THREE.Mesh(geometry, material))

  let t0 = 0
  let running = false
  let raf = 0
  let last = 0

  function size() {
    const b = canvas.getBoundingClientRect()
    if (!b.width || !b.height) return
    renderer.setSize(b.width, b.height, false)
    const a = b.width / b.height
    const ta = 16 / 9
    uniforms.aspect.value = a
    if (a > ta) uniforms.sc.value.set(1, ta / a)
    else uniforms.sc.value.set(a / ta, 1)
  }

  function draw(seconds) {
    uniforms.t.value = seconds
    renderer.render(scene, camera)
  }

  function loop(now) {
    if (!running) return
    raf = requestAnimationFrame(loop)
    if (now - last < 33) return // 约 30 帧足够
    last = now
    draw((now - t0) / 1000)
  }

  size()

  return {
    start(reduce) {
      size()
      if (reduce) {
        draw(FINAL_T)
        return
      }
      if (running) return
      running = true
      if (!t0) t0 = performance.now()
      raf = requestAnimationFrame(loop)
    },
    stop() {
      running = false
      cancelAnimationFrame(raf)
    },
    size,
    /** 尺寸变化后、未在播放时重画当前帧 */
    redraw() {
      size()
      if (!running) draw(uniforms.t.value || FINAL_T)
    },
    dispose() {
      running = false
      cancelAnimationFrame(raf)
      geometry.dispose()
      material.dispose()
      texture.dispose()
      renderer.dispose()
      renderer.forceContextLoss()
    }
  }
}
