<#
.SYNOPSIS
  Windows 签名校验（L-10）。【未实测】本机是 macOS，没有 Windows 环境。

.DESCRIPTION
  对目录/文件里的全部 .exe .dll .pyd .node .msi：
    1. signtool verify /pa /v（Authenticode 默认策略，含链校验）
    2. 列出所有未签名或签名无效的文件
    3. 检查带有 RFC 3161 时间戳（没有时间戳的签名在证书过期后失效）
    4. 签名人（证书 Subject）一致；-ExpectedPublisher 可指定必须包含的发布者名称
  输出「通过/失败」清单，有失败时退出码为 1（供 CI 用）。

.PARAMETER Path
  文件或目录（可多个）。
.PARAMETER ExpectedPublisher
  证书 Subject 必须包含的字符串（公司名），防止被别的证书签过。
.PARAMETER AllowThirdParty
  允许存在其他发布者的签名（例如保留 Electron/node/mongod 官方签名时，配合 sign_win.ps1 -SkipAlreadySigned）。
  此时只要求每个文件签名有效且带时间戳，不要求签名人一致。
.PARAMETER SignToolPath
  signtool.exe 路径；默认在 PATH 和 Windows SDK 目录里找。
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string[]]$Path,
  [string]$ExpectedPublisher,
  [switch]$AllowThirdParty,
  [string]$SignToolPath = $env:SIGNTOOL_PATH
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Extensions = @('.exe', '.dll', '.pyd', '.node', '.msi')

function Find-SignTool {
  if ($SignToolPath -and (Test-Path -LiteralPath $SignToolPath)) { return $SignToolPath }
  $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  $kits = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'
  if (Test-Path -LiteralPath $kits) {
    $found = Get-ChildItem -LiteralPath $kits -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
      Where-Object { $_.FullName -match '\\x64\\' } | Sort-Object FullName -Descending | Select-Object -First 1
    if ($found) { return $found.FullName }
  }
  throw '找不到 signtool.exe：安装 Windows SDK，或设置 SIGNTOOL_PATH'
}

$files = New-Object System.Collections.Generic.List[string]
foreach ($p in $Path) {
  if (-not (Test-Path -LiteralPath $p)) { throw "路径不存在：$p" }
  $item = Get-Item -LiteralPath $p
  if ($item.PSIsContainer) {
    Get-ChildItem -LiteralPath $item.FullName -Recurse -File |
      Where-Object { $Extensions -contains $_.Extension.ToLowerInvariant() } | ForEach-Object { $files.Add($_.FullName) }
  } else { $files.Add($item.FullName) }
}
if ($files.Count -eq 0) { throw '没有找到需要校验的文件' }

$signtool = Find-SignTool
$unsigned = New-Object System.Collections.Generic.List[string]
$invalid = New-Object System.Collections.Generic.List[string]
$noTimestamp = New-Object System.Collections.Generic.List[string]
$wrongPublisher = New-Object System.Collections.Generic.List[string]
$subjects = @{}

foreach ($f in $files) {
  $sig = Get-AuthenticodeSignature -LiteralPath $f
  if ($sig.Status -eq 'NotSigned') { $unsigned.Add($f); continue }
  # signtool verify /pa /v：退出码 0 才算通过
  $out = & $signtool verify /pa /v $f 2>&1
  if ($LASTEXITCODE -ne 0) { $invalid.Add("$f：$(($out | Select-Object -Last 2) -join ' ')"); continue }
  if (-not $sig.TimeStamperCertificate) { $noTimestamp.Add($f) }
  $subj = $sig.SignerCertificate.Subject
  if (-not $subjects.ContainsKey($subj)) { $subjects[$subj] = 0 }
  $subjects[$subj]++
  if ($ExpectedPublisher -and -not $subj.Contains($ExpectedPublisher)) { $wrongPublisher.Add("$f：$subj") }
}

$script:fail = 0
function Report([bool]$ok, [string]$title, $detail) {
  if ($ok) { Write-Host "  [通过] $title" }
  else {
    $script:fail++
    Write-Host "  [失败] $title"
    foreach ($d in ($detail | Select-Object -First 25)) { Write-Host "         $d" }
    if (@($detail).Count -gt 25) { Write-Host "         …… 共 $(@($detail).Count) 项，只显示前 25 项" }
  }
}

Write-Host "== 校验 $($files.Count) 个文件"
Report ($unsigned.Count -eq 0) "全部文件都已签名" $unsigned
Report ($invalid.Count -eq 0) "signtool verify /pa /v 全部通过" $invalid
Report ($noTimestamp.Count -eq 0) "全部签名带 RFC 3161 时间戳" $noTimestamp
if ($ExpectedPublisher) { Report ($wrongPublisher.Count -eq 0) "发布者包含「$ExpectedPublisher」" $wrongPublisher }
if (-not $AllowThirdParty) {
  $list = @($subjects.GetEnumerator() | ForEach-Object { "$($_.Value) 个：$($_.Key)" })
  Report ($subjects.Count -le 1) "签名人一致" $list
}

Write-Host ''
if ($script:fail -eq 0) { Write-Host '结果：通过'; exit 0 } else { Write-Host "结果：失败（$($script:fail) 项）"; exit 1 }
