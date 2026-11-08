/**
 * 宣纸山水：在离屏 canvas 上画出最终画面（docs/design/ink-reference.js 的 painting() 原样移植）。
 * InkStage 把它作为着色器纹理；无 WebGL 时直接把这张画当静态背景。
 * 用固定种子，每次画出来一样。
 */
export const PAPER = '#FDFCFA'
export const PAINTING_W = 1600
export const PAINTING_H = 900

function seeded(s) {
  return function () {
    s = (s * 16807) % 2147483647
    return (s - 1) / 2147483646
  }
}

function ridge(x, W, H, base, amp, col, blur, seed, fadeTop, fadeBot) {
  const c = document.createElement('canvas')
  c.width = W
  c.height = H
  const g = c.getContext('2d')
  g.filter = 'blur(' + blur + 'px)'
  g.fillStyle = col
  g.beginPath()
  g.moveTo(-30, H + 30)
  for (let i = -30; i <= W + 30; i += 5) {
    const k = Math.pow(Math.max(0, i / W), 1.35)
    const y = base - amp * k * (0.62 + 0.5 * Math.sin(i * 0.0042 + seed) + 0.22 * Math.sin(i * 0.0125 + seed * 1.7) +
      0.08 * Math.sin(i * 0.041 + seed * 2.3) + 0.03 * Math.sin(i * 0.11 + seed))
    g.lineTo(i, y)
  }
  g.lineTo(W + 30, H + 30)
  g.closePath()
  g.fill()
  g.filter = 'none'
  g.globalCompositeOperation = 'destination-out'
  const a = g.createLinearGradient(0, fadeTop, 0, fadeBot)
  a.addColorStop(0, 'rgba(0,0,0,0)')
  a.addColorStop(1, 'rgba(0,0,0,1)')
  g.fillStyle = a
  g.fillRect(0, 0, W, H)
  const b = g.createLinearGradient(0, 0, W * 0.62, 0)
  b.addColorStop(0, 'rgba(0,0,0,1)')
  b.addColorStop(0.55, 'rgba(0,0,0,.72)')
  b.addColorStop(1, 'rgba(0,0,0,0)')
  g.fillStyle = b
  g.fillRect(0, 0, W, H)
  x.drawImage(c, 0, 0)
}

export function painting() {
  const W = PAINTING_W
  const H = PAINTING_H
  const cv = document.createElement('canvas')
  cv.width = W
  cv.height = H
  const x = cv.getContext('2d')
  const rnd = seeded(20261108)
  x.fillStyle = PAPER
  x.fillRect(0, 0, W, H)

  // 远山到近山，四层
  ridge(x, W, H, 470, 430, 'rgba(120,124,122,.34)', 9, 1.1, 300, 640)
  ridge(x, W, H, 590, 420, 'rgba(84,88,86,.5)', 5, 2.7, 430, 760)
  ridge(x, W, H, 700, 330, 'rgba(48,50,48,.7)', 2.5, 4.3, 560, 860)
  ridge(x, W, H, 800, 170, 'rgba(32,33,31,.8)', 1.4, 6.2, 700, 900)

  // 枯笔皴擦，从左到右渐显
  x.globalCompositeOperation = 'multiply'
  for (let i = 0; i < 760; i++) {
    const a = W * (0.42 + 0.58 * Math.sqrt(rnd()))
    const b = 210 + rnd() * 500
    const l = 7 + rnd() * 20
    const k = Math.max(0, (a / W - 0.42) / 0.58)
    x.strokeStyle = 'rgba(40,42,40,' + ((0.01 + rnd() * 0.04) * k) + ')'
    x.lineWidth = 0.5 + rnd() * 0.9
    x.beginPath()
    x.moveTo(a, b)
    x.lineTo(a - l * 0.3, b + l)
    x.stroke()
  }
  x.globalCompositeOperation = 'source-over'

  // 一叶孤舟，极小
  const fx = W * 0.56
  const fy = H * 0.70
  x.fillStyle = 'rgba(38,36,31,.88)'
  x.beginPath()
  x.moveTo(fx - 27, fy - 4)
  x.quadraticCurveTo(fx, fy + 6, fx + 29, fy - 6)
  x.quadraticCurveTo(fx, fy - 0.5, fx - 27, fy - 4)
  x.fill()
  x.fillRect(fx - 2.2, fy - 13, 4.4, 11)
  x.beginPath()
  x.arc(fx, fy - 15.5, 2.6, 0, 7)
  x.fill()
  x.strokeStyle = 'rgba(38,36,31,.13)'
  x.lineWidth = 1
  x.beginPath()
  x.moveTo(fx - 52, fy + 8)
  x.lineTo(fx + 60, fy + 8)
  x.stroke()
  x.beginPath()
  x.moveTo(fx - 24, fy + 13)
  x.lineTo(fx + 30, fy + 13)
  x.stroke()

  return cv
}
