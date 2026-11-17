// utils/release.js：semver 比较（含 1.10.0 > 1.9.0、+构建信息忽略）、表单校验、状态机、展示文案
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  compareSemver, isSemver, isDownloadUrl, isSha256, releaseFormErrors, toPayload, toForm, releaseActions,
  releaseStatusMeta, formatSize, releaseNotice, releaseLabel
} from '../../src/utils/release.js'
import { CHANNELS, PLATFORMS } from '../../src/config/releases.js'
import { mapError } from '../../src/utils/errors.js'
import { can, menuFor } from '../../src/config/roles.js'

const SHA = 'a'.repeat(64)
const good = () => ({
  version: '1.2.3', channel: 'stable', platform: 'mac-arm64', notes: '说明', url: 'https://dl.example.com/a.dmg',
  sha256: SHA, size: 1234, min_supported: ''
})

test('semver：数字比较而不是字符串比较', () => {
  assert.equal(compareSemver('1.10.0', '1.9.0'), 1)
  assert.equal(compareSemver('1.9.0', '1.10.0'), -1)
  assert.equal(compareSemver('2.0.0', '1.99.99'), 1)
  assert.equal(compareSemver('1.2.3', '1.2.3'), 0)
})

test('semver：忽略 +构建信息，预发布低于正式版', () => {
  assert.equal(compareSemver('1.2.3+testbuild', '1.2.3'), 0)
  assert.equal(compareSemver('1.2.3+a', '1.2.3+b'), 0)
  assert.equal(compareSemver('1.2.3-beta.1', '1.2.3'), -1)
  assert.equal(compareSemver('1.2.3-beta.2', '1.2.3-beta.10'), -1)
  assert.equal(compareSemver('1.2.3-alpha', '1.2.3-beta'), -1)
})

test('semver：格式校验', () => {
  for (const v of ['1.2.3', '0.0.1', '1.2.3+testbuild', '1.2.3-rc.1+b7']) assert.ok(isSemver(v), v)
  for (const v of ['1.2', 'v1.2.3', '01.2.3', '1.2.3.4', '', 'a.b.c', '1.2.3+', null]) assert.ok(!isSemver(v), String(v))
  assert.ok(Number.isNaN(compareSemver('x', '1.0.0')))
})

test('下载地址：https，开发允许 http://127.0.0.1', () => {
  assert.ok(isDownloadUrl('https://dl.example.com/a.dmg'))
  assert.ok(isDownloadUrl('http://127.0.0.1:9000/a.dmg'))
  for (const u of ['http://dl.example.com/a', 'ftp://x.com/a', 'https://', 'https://u:p@x.com/a', 'http://127.0.0.1.evil.com/a', '', 'x'])
    assert.ok(!isDownloadUrl(u), u)
})

test('sha256 必须 64 位十六进制', () => {
  assert.ok(isSha256(SHA) && isSha256('A'.repeat(64)))
  assert.ok(!isSha256('a'.repeat(63)) && !isSha256('g'.repeat(64)) && !isSha256(''))
})

test('表单校验：合法无错误，逐项报错', () => {
  assert.deepEqual(releaseFormErrors(good()), {})
  const e = releaseFormErrors({ ...good(), version: '1.2', channel: '', platform: '', url: 'http://x.com', sha256: 'abc', size: 0 })
  assert.deepEqual(Object.keys(e).sort(), ['channel', 'platform', 'sha256', 'size', 'url', 'version'])
  assert.ok(releaseFormErrors({ ...good(), size: 1.5 }).size)
  assert.ok(releaseFormErrors({ ...good(), size: undefined }).size)
})

test('强制升级线：格式、不得高于自身版本（忽略构建信息）', () => {
  assert.ok(releaseFormErrors({ ...good(), min_supported: 'abc' }).min_supported)
  assert.match(releaseFormErrors({ ...good(), min_supported: '1.2.4' }).min_supported, /不能高于/)
  assert.deepEqual(releaseFormErrors({ ...good(), min_supported: '1.2.3' }), {})
  assert.deepEqual(releaseFormErrors({ ...good(), version: '1.2.3+b1', min_supported: '1.2.3' }), {})
  assert.deepEqual(releaseFormErrors({ ...good(), min_supported: '1.10.0', version: '1.10.1' }), {})
  assert.ok(releaseFormErrors({ ...good(), min_supported: '1.10.0', version: '1.9.0' }).min_supported)
})

test('payload：去空白、sha256 小写、空强制线为 null', () => {
  const p = toPayload({ ...good(), version: ' 1.2.3 ', sha256: ' ' + 'A'.repeat(64) + ' ', min_supported: '  ' })
  assert.equal(p.version, '1.2.3')
  assert.equal(p.sha256, SHA)
  assert.equal(p.min_supported, null)
  assert.equal(toPayload({ ...good(), min_supported: ' 1.0.0 ' }).min_supported, '1.0.0')
  const f = toForm({ ...good(), min_supported: null, notes: null })
  assert.equal(f.min_supported, '')
  assert.equal(f.notes, '')
})

test('状态机：草稿可编辑/发布，已发布可撤回，已撤回无操作', () => {
  assert.deepEqual(releaseActions('draft'), { edit: true, publish: true, withdraw: false })
  assert.deepEqual(releaseActions('published'), { edit: false, publish: false, withdraw: true })
  assert.deepEqual(releaseActions('withdrawn'), { edit: false, publish: false, withdraw: false })
  assert.deepEqual(releaseActions('x'), { edit: false, publish: false, withdraw: false })
})

test('状态颜色与文案', () => {
  assert.equal(releaseStatusMeta('draft').tone, 'grey')
  assert.equal(releaseStatusMeta('published').tone, 'green')
  assert.equal(releaseStatusMeta('withdrawn').label, '已撤回')
  assert.equal(releaseStatusMeta('zzz').label, 'zzz')
  assert.equal(releaseLabel(PLATFORMS, 'win-x64'), 'Windows 64 位')
  assert.equal(releaseLabel(CHANNELS, 'nope'), 'nope')
})

test('文件大小与提示文案', () => {
  assert.equal(formatSize(512), '512 B')
  assert.equal(formatSize(1536), '1.5 KB')
  assert.equal(formatSize(120 * 1024 * 1024), '120 MB')
  assert.equal(formatSize(-1), '-')
  assert.equal(releaseNotice({ warnings: ['a', 'b'] }), 'a；b')
  assert.equal(releaseNotice({ warnings: [] }), '')
  assert.equal(releaseNotice(null), '')
})

test('错误码映射', () => {
  assert.match(mapError({ status: 409, data: { code: 'RELEASE_DUPLICATE' } }).message, /相同版本号/)
  assert.match(mapError({ status: 409, data: { code: 'RELEASE_NOT_DRAFT' } }).message, /草稿/)
  assert.match(mapError({ status: 422, data: { code: 'MIN_SUPPORTED_TOO_HIGH' } }).message, /不能高于/)
  assert.match(mapError({ status: 422, data: { code: 'URL_INVALID' } }).message, /https/)
})

test('权限：readonly 可看不可写，菜单里有版本发布', () => {
  assert.ok(can('readonly', 'release.read') && !can('readonly', 'release.write'))
  assert.ok(can('ops', 'release.write') && can('super', 'release.write'))
  for (const r of ['super', 'ops', 'readonly']) assert.ok(menuFor(r).some(m => m.path === '/releases'), r)
})
