/** 版本发布的渠道与平台（与服务端 services/releases.py 一致；取值是契约，不要随意改） */
export const CHANNELS = [
  { value: 'stable', label: '正式版 stable' },
  { value: 'beta', label: '测试版 beta' }
]

export const PLATFORMS = [
  { value: 'mac-arm64', label: 'macOS Apple 芯片' },
  { value: 'mac-x64', label: 'macOS Intel' },
  { value: 'win-x64', label: 'Windows 64 位' }
]

export const MAX_NOTES = 5000
