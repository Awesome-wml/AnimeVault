<#
.SYNOPSIS
  Windows 代码签名（L-10）。【未实测】本机是 macOS，没有 Windows 机器和证书，脚本只按 signtool 文档编写并做了人工审阅。

.DESCRIPTION
  对应用目录（electron-builder 的 win-unpacked）和/或安装包里的全部 PE 文件签名并带 RFC 3161 时间戳：
  .exe .dll .pyd .node .msi（含 dongai-backend.exe、mongod.exe、playwright 的 node.exe、Electron 的 exe/dll、
  Nuitka 产出的 .pyd 扩展模块）。命令形态：
      signtool sign /fd SHA256 /tr <时间戳地址> /td SHA256 <证书选择参数> <文件...>

  顺序很重要（NSIS 安装包会把应用文件打进去，所以必须「先签应用文件，再打安装包，最后签安装包」）：
      1. npx electron-builder --win --x64 --dir           （出 out\win-unpacked，不签）
      2. sign_win.ps1 -Path out\win-unpacked ...           （签应用里所有 exe/dll）
      3. npx electron-builder --prepackaged out\win-unpacked --win nsis --x64   （用已签好的目录打安装包）
      4. sign_win.ps1 -Path out\DongAI-Setup-x.y.z.exe ... （签安装包本身）
      5. verify_win.ps1 -Path out\win-unpacked,out\DongAI-Setup-x.y.z.exe
  也可以改用 electron-builder 内置钩子 win.sign 逐文件调用本脚本，见 desktop/signing/README.md。

  证书选择方式（三选一，都不给会报错）：
    -CertThumbprint <SHA1>   证书库里的证书（硬件令牌/EV 令牌驱动、或云厂商的本地 KSP 把证书同步到证书库后）。对应 signtool 的 /sha1
    -SignToolArgs @(...)     原样透传的 signtool 证书参数，适配云签名的 dlib/KSP 方式，例如：
                             Azure Trusted Signing:  @('/dlib','C:\tools\Azure.CodeSigning.Dlib.dll','/dmdf','C:\tools\metadata.json')
                             DigiCert KeyLocker(KSP): @('/csp','DigiCert Signing Manager KSP','/kc','<密钥对别名>','/f','C:\tools\cert.crt')
                             SSL.com eSigner：官方提供独立的 CodeSignTool（Java），不是 signtool 参数；要接 CI 需另写一层，见 README
                             以上全部【未实测】，参数以各厂商当前文档为准。
    -PfxPath/-PfxPassword    仅限本机调试用的自签名测试证书。行业规定正式的代码签名私钥不能放在文件里，不要拿它签正式包

  时间戳地址不写死：-TimestampUrl 或环境变量 WIN_TIMESTAMP_URL，由所选 CA/云签名服务指定（例如它文档里给的 RFC 3161 地址）。

.PARAMETER Path
  要签名的文件或目录（可多个）。目录会递归找 .exe .dll .pyd .node .msi。
.PARAMETER TimestampUrl
  RFC 3161 时间戳服务地址（必填，或设环境变量 WIN_TIMESTAMP_URL）。
.PARAMETER SkipAlreadySigned
  跳过已经有有效签名的文件（保留 Electron/node/mongod 官方自带的发布者签名）。默认不跳过，全部用我们的证书重签，让发布者一致。
  取舍见 README，发版前需要和负责人确认。
.PARAMETER Description
  signtool /d 描述，默认 DongAI。
.PARAMETER DryRun
  只打印将执行的 signtool 命令，不签名。
.PARAMETER NoVerify
  签完不自动跑 verify_win.ps1。

.EXAMPLE
  # 证书在证书库/令牌里
  .\sign_win.ps1 -Path ..\shell\out\win-unpacked -CertThumbprint <指纹> -TimestampUrl <RFC3161地址>
.EXAMPLE
  # 只看会执行什么
  .\sign_win.ps1 -Path ..\shell\out\win-unpacked -CertThumbprint 0000 -TimestampUrl http://example.invalid/ts -DryRun
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string[]]$Path,
  [string]$TimestampUrl = $env:WIN_TIMESTAMP_URL,
  [string]$CertThumbprint = $env:WIN_CERT_THUMBPRINT,
  [string[]]$SignToolArgs,
  [string]$PfxPath,
  [string]$PfxPassword = $env:WIN_PFX_PASSWORD,
  [string]$SignToolPath = $env:SIGNTOOL_PATH,
  [string]$Description = 'DongAI',
  [switch]$SkipAlreadySigned,
  [switch]$DryRun,
  [switch]$NoVerify
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Extensions = @('.exe', '.dll', '.pyd', '.node', '.msi')

function Find-SignTool {
  if ($SignToolPath) {
    if (-not (Test-Path -LiteralPath $SignToolPath)) { throw "SIGNTOOL_PATH 指向的文件不存在：$SignToolPath" }
    return $SignToolPath
  }
  $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  # Windows SDK 默认安装位置，取最新版本的 x64
  $kits = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'
  if (Test-Path -LiteralPath $kits) {
    $found = Get-ChildItem -LiteralPath $kits -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
      Where-Object { $_.FullName -match '\\x64\\' } | Sort-Object FullName -Descending | Select-Object -First 1
    if ($found) { return $found.FullName }
  }
  throw '找不到 signtool.exe：安装 Windows SDK，或设置环境变量 SIGNTOOL_PATH'
}

if (-not $TimestampUrl) { throw '必须给时间戳服务地址：-TimestampUrl 或环境变量 WIN_TIMESTAMP_URL（没有时间戳，证书过期后签名就失效）' }

# 证书选择参数
$certArgs = @()
if ($SignToolArgs -and $SignToolArgs.Count -gt 0) {
  $certArgs = $SignToolArgs
} elseif ($CertThumbprint) {
  $certArgs = @('/sha1', $CertThumbprint)
} elseif ($PfxPath) {
  $certArgs = @('/f', $PfxPath)
  if ($PfxPassword) { $certArgs += @('/p', $PfxPassword) }
} else {
  throw '没有指定证书：给 -CertThumbprint（或环境变量 WIN_CERT_THUMBPRINT），或用 -SignToolArgs 透传云签名参数'
}

# 枚举要签的文件
$files = New-Object System.Collections.Generic.List[string]
foreach ($p in $Path) {
  if (-not (Test-Path -LiteralPath $p)) { throw "路径不存在：$p" }
  $item = Get-Item -LiteralPath $p
  if ($item.PSIsContainer) {
    Get-ChildItem -LiteralPath $item.FullName -Recurse -File |
      Where-Object { $Extensions -contains $_.Extension.ToLowerInvariant() } |
      ForEach-Object { $files.Add($_.FullName) }
  } else {
    $files.Add($item.FullName)
  }
}
if ($files.Count -eq 0) { throw '没有找到需要签名的文件' }

if ($SkipAlreadySigned -and -not $DryRun) {
  $todo = New-Object System.Collections.Generic.List[string]
  foreach ($f in $files) {
    $sig = Get-AuthenticodeSignature -LiteralPath $f
    if ($sig.Status -eq 'Valid') { Write-Host "跳过（已有有效签名：$($sig.SignerCertificate.Subject)）：$f" } else { $todo.Add($f) }
  }
  $files = $todo
}

# 由内到外：路径深的先签，安装包/最外层的最后签；.msi 与顶层 exe 自然排在最后
$sorted = $files | Sort-Object @{ Expression = { ($_ -split '[\\/]').Count }; Descending = $true }, @{ Expression = { $_ } }

$signtool = if ($DryRun) { 'signtool.exe' } else { Find-SignTool }
Write-Host "==> 待签名文件 $(@($sorted).Count) 个，signtool：$signtool"

# 分批，避免命令行过长
$batchSize = 40
$all = @($sorted)
for ($i = 0; $i -lt $all.Count; $i += $batchSize) {
  $end = [Math]::Min($i + $batchSize, $all.Count) - 1
  $batch = $all[$i..$end]
  $stArgs = @('sign', '/fd', 'SHA256', '/tr', $TimestampUrl, '/td', 'SHA256') + $certArgs + @('/d', $Description) + $batch
  if ($DryRun) {
    # 打印时遮住密码
    $shown = @(); $mask = $false
    foreach ($a in $stArgs) { if ($mask) { $shown += '***'; $mask = $false } else { $shown += ('"{0}"' -f $a); if ($a -eq '/p') { $mask = $true } } }
    Write-Host "[dry-run] $signtool $($shown -join ' ')"
  } else {
    & $signtool @stArgs
    if ($LASTEXITCODE -ne 0) { throw "signtool sign 失败（退出码 $LASTEXITCODE），批次起始：$($batch[0])" }
  }
}

if ($DryRun) { Write-Host '==> dry-run 结束，未签名任何文件'; return }

if (-not $NoVerify) {
  Write-Host '==> 校验'
  & (Join-Path $PSScriptRoot 'verify_win.ps1') -Path $Path -SignToolPath $signtool
  if ($LASTEXITCODE -ne 0) { throw '签名后校验失败' }
}
Write-Host '==> 完成'
