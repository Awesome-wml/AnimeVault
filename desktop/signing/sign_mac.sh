#!/usr/bin/env bash
# macOS 签名 + 公证（L-09）。
#
# 用法：
#   desktop/signing/sign_mac.sh [选项] [APP路径]            签名 .app，（真实身份时）公证并钉票据
#   desktop/signing/sign_mac.sh [选项] --dmg-only DMG路径    只处理 dmg：签名、公证、钉票据（dmg 由已签好的 .app 打出来之后调用）
#
# 默认 APP = desktop/shell/out/mac-arm64/DongAI.app
#
# 选项：
#   --dry-run         只打印将执行的 codesign / notarytool / stapler / spctl 命令，不改任何文件、不联网
#   --no-notarize     身份是真实证书时也不公证（本地调试用；发布流程不要用）
#   --skip-verify     签完不跑 verify_mac.sh（不建议）
#   --entitlements F  Electron 主程序和 Helper 用的 entitlements，默认 desktop/shell/resources/entitlements.mac.plist
#   --sidecar-entitlements F  Contents/Resources/ 下可执行文件（dongai-backend、mongod、playwright node）用的，
#                     默认 desktop/shell/resources/entitlements.sidecar.mac.plist
#   -h, --help
#
# 环境变量（仓库里不放任何真实值，全部由使用者提供）：
#   MAC_SIGN_IDENTITY   签名身份，默认 "-"（ad-hoc，只用来在本机演练流程，产物不能发布）。
#                       真实值形如 "Developer ID Application: 公司名 (TEAMID)"，或证书 SHA-1。
#   公证凭据，二选一（ad-hoc 时不公证，不需要）：
#     NOTARY_PROFILE                          notarytool 的 keychain profile 名（xcrun notarytool store-credentials 生成，推荐）
#     APPLE_ID + APPLE_APP_SPECIFIC_PASSWORD + APPLE_TEAM_ID
#                                             注意：密码会出现在命令行参数里（ps 可见），CI 请用受控机器并开日志脱敏
#
# 签名顺序（由内到外，错一步公证就失败）：
#   1. 所有「不属于某个 bundle 主程序」的 Mach-O 逐个签：后端 sidecar、mongod、playwright node、全部 .so/.dylib、
#      框架里的 Helpers/Libraries/ShipIt 等（用 file 判断，不看扩展名）
#   2. bundle 由深到浅：Electron 的 Helper .app、各 .framework
#   3. 最后签主应用（它的资源封印包含上面所有文件，之后任何文件再被改动都会让封印失效）
set -euo pipefail

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib_mac.sh
source "$SELF_DIR/lib_mac.sh"

DRY_RUN=0; NOTARIZE=1; VERIFY=1; DMG_ONLY=""; APP=""; ENT="$DEFAULT_ENTITLEMENTS"; SIDECAR_ENT="$DEFAULT_SIDECAR_ENTITLEMENTS"
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --no-notarize) NOTARIZE=0 ;;
    --skip-verify) VERIFY=0 ;;
    --entitlements) shift; ENT="${1:?--entitlements 需要参数}" ;;
    --sidecar-entitlements) shift; SIDECAR_ENT="${1:?--sidecar-entitlements 需要参数}" ;;
    --dmg-only) shift; DMG_ONLY="${1:?--dmg-only 需要 dmg 路径}" ;;
    -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) die "未知选项 $1" ;;
    *) [ -z "$APP" ] || die "只能给一个 APP 路径"; APP="$1" ;;
  esac
  shift
done

IDENTITY="${MAC_SIGN_IDENTITY:--}"
ADHOC=0; [ "$IDENTITY" = "-" ] && ADHOC=1
[ -f "$ENT" ] || die "找不到 entitlements 文件 $ENT"
[ -f "$SIDECAR_ENT" ] || die "找不到 sidecar entitlements 文件 $SIDECAR_ENT"

# 打印并（非 dry-run 时）执行命令
run() {
  if [ "$DRY_RUN" = 1 ]; then printf '[dry-run]'; printf ' %q' "$@"; printf '\n'; else "$@"; fi
}

# ---- 签名参数 ----
# ad-hoc 不能带 --timestamp（没有证书，时间戳服务拒绝）；真实证书必须带，公证要求安全时间戳
SIGN_COMMON=(--force --options runtime)
if [ "$ADHOC" = 1 ]; then SIGN_COMMON+=(--timestamp=none); else SIGN_COMMON+=(--timestamp); fi

sign_one() {  # sign_one <path> [entitlements]
  local path="$1" ent="${2:-}"
  if [ -n "$ent" ]; then
    run codesign "${SIGN_COMMON[@]}" --entitlements "$ent" --sign "$IDENTITY" "$path"
  else
    run codesign "${SIGN_COMMON[@]}" --sign "$IDENTITY" "$path"
  fi
}

# ---- 公证 ----
NOTARY_AUTH=()
setup_notary_auth() {
  if [ -n "${NOTARY_PROFILE:-}" ]; then
    NOTARY_AUTH=(--keychain-profile "$NOTARY_PROFILE")
  elif [ -n "${APPLE_ID:-}" ] && [ -n "${APPLE_APP_SPECIFIC_PASSWORD:-}" ] && [ -n "${APPLE_TEAM_ID:-}" ]; then
    NOTARY_AUTH=(--apple-id "$APPLE_ID" --password "$APPLE_APP_SPECIFIC_PASSWORD" --team-id "$APPLE_TEAM_ID")
  elif [ "$DRY_RUN" = 1 ]; then
    NOTARY_AUTH=(--keychain-profile "<NOTARY_PROFILE 或 APPLE_ID/APPLE_APP_SPECIFIC_PASSWORD/APPLE_TEAM_ID 未设置>")
  else
    die "要公证需要设置 NOTARY_PROFILE，或同时设置 APPLE_ID、APPLE_APP_SPECIFIC_PASSWORD、APPLE_TEAM_ID（不想公证加 --no-notarize）"
  fi
}

# 打印命令时遮住密码
run_notary() {
  if [ "$DRY_RUN" = 1 ]; then
    local a masked=() skip=0
    for a in "$@"; do
      if [ "$skip" = 1 ]; then masked+=("***"); skip=0; continue; fi
      masked+=("$a"); [ "$a" = "--password" ] && skip=1
    done
    printf '[dry-run]'; printf ' %q' "${masked[@]}"; printf '\n'
  else
    "$@"
  fi
}

notarize_submit() {  # notarize_submit <zip 或 dmg>
  local file="$1" out id status
  if [ "$DRY_RUN" = 1 ]; then
    run_notary xcrun notarytool submit "$file" "${NOTARY_AUTH[@]}" --wait
    echo "[dry-run] 状态不是 Accepted 时：xcrun notarytool log <submission-id> <同样的凭据参数>，打印后以失败退出"
    return 0
  fi
  # 注意：notarytool 在 Invalid 时退出码也可能是 0，必须解析 status 行
  out="$(xcrun notarytool submit "$file" "${NOTARY_AUTH[@]}" --wait 2>&1)" || true
  echo "$out"
  id="$(sed -n 's/^ *id: *//p' <<<"$out" | head -1)"
  status="$(sed -n 's/^ *status: *//p' <<<"$out" | tail -1)"
  if [ "$status" != "Accepted" ]; then
    echo "公证未通过（status=${status:-未知}），拉取公证日志：" >&2
    if [ -n "$id" ]; then xcrun notarytool log "$id" "${NOTARY_AUTH[@]}" >&2 || true; fi
    die "公证失败：$file"
  fi
}

notarize_app() {  # 把 .app 压成 zip 提交，通过后把票据钉进 .app
  local app="$1" tmp zip
  setup_notary_auth
  tmp="$(mktemp -d)"; zip="$tmp/$(basename "$app" .app).zip"
  run ditto -c -k --keepParent "$app" "$zip"
  notarize_submit "$zip"
  run xcrun stapler staple "$app"
  run xcrun stapler validate "$app"
  run spctl --assess --type execute -vv "$app"
  rm -rf "$tmp"
}

notarize_dmg() {
  local dmg="$1"
  setup_notary_auth
  notarize_submit "$dmg"
  run xcrun stapler staple "$dmg"
  run xcrun stapler validate "$dmg"
  run spctl --assess --type open --context context:primary-signature -vv "$dmg"
}

preflight_identity() {
  [ "$ADHOC" = 1 ] && return 0
  [ "$DRY_RUN" = 1 ] && return 0
  if ! security find-identity -v -p codesigning | grep -qF -- "$IDENTITY"; then
    die "钥匙串里找不到签名身份「${IDENTITY}」（security find-identity -v -p codesigning 查看）。CI 里先把 p12 导入临时钥匙串"
  fi
}

if [ "$ADHOC" = 1 ]; then
  echo "==> 签名身份：ad-hoc（-）。仅用于本机演练：不带时间戳、不公证，产物 Gatekeeper 一定拦截，不能发布"
else
  echo "==> 签名身份：$IDENTITY"
fi
preflight_identity

# ---------------- dmg 模式 ----------------
if [ -n "$DMG_ONLY" ]; then
  [ -f "$DMG_ONLY" ] || die "找不到 dmg：$DMG_ONLY"
  echo "==> 签名 dmg：$DMG_ONLY"
  # dmg 不是 Mach-O，没有 hardened runtime / entitlements，只需要签名和（真实证书时）时间戳
  if [ "$ADHOC" = 1 ]; then run codesign --force --timestamp=none --sign "$IDENTITY" "$DMG_ONLY"
  else run codesign --force --timestamp --sign "$IDENTITY" "$DMG_ONLY"; fi
  if [ "$ADHOC" = 0 ] && [ "$NOTARIZE" = 1 ]; then
    echo "==> 公证 dmg 并钉票据"
    notarize_dmg "$DMG_ONLY"
  fi
  if [ "$VERIFY" = 1 ] && [ "$DRY_RUN" = 0 ]; then "$SELF_DIR/verify_mac.sh" "$DMG_ONLY"; fi
  exit 0
fi

# ---------------- .app 模式 ----------------
[ -n "$APP" ] || APP="$SELF_DIR/../shell/out/mac-arm64/DongAI.app"
[ -d "$APP" ] || die "找不到 .app：${APP}（先 desktop/build_all.sh --dir）"
APP="$(cd "$APP" && pwd)"
case "$APP" in *.app) ;; *) die "APP 路径必须以 .app 结尾：$APP" ;; esac

# 签名会原地改写文件。如果 .app 是别人的构建产物，请先拷一份再签。
echo "==> 枚举 $APP 里的 Mach-O 和 bundle"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
list_macho "$APP" > "$TMP/macho.tsv"
list_bundles "$APP" > "$TMP/bundles.txt"

# bundle 主程序由 bundle 整体签名处理，从单个文件队列里去掉
: > "$TMP/skip.txt"
while IFS= read -r b; do bundle_main_exe "$APP" "$b" >> "$TMP/skip.txt" || true; done < "$TMP/bundles.txt"
# 根 app 的主程序
bundle_main_exe "$APP" "." 2>/dev/null | sed 's#^\./##' >> "$TMP/skip.txt" || true

# 单个文件队列：深的先签；每行 "深度<TAB>类型<TAB>路径"
: > "$TMP/files.tsv"
while IFS=$'\t' read -r kind path; do
  if grep -qxF -- "$path" "$TMP/skip.txt"; then continue; fi
  printf '%s\t%s\t%s\n' "$(depth "$path")" "$kind" "$path" >> "$TMP/files.tsv"
done < "$TMP/macho.tsv"
sort -t$'\t' -k1,1nr -k3,3 "$TMP/files.tsv" > "$TMP/files.sorted.tsv"

NFILES=$(wc -l < "$TMP/files.sorted.tsv" | tr -d ' ')
NBUNDLES=$(wc -l < "$TMP/bundles.txt" | tr -d ' ')
echo "    单个 Mach-O $NFILES 个，嵌套 bundle $NBUNDLES 个，另加主应用"

echo "==> [1/3] 签名嵌套 Mach-O（可执行文件带 entitlements（Resources/ 下用 sidecar 版），库不带）"
while IFS=$'\t' read -r _ kind path; do
  if [ "$kind" = exec ]; then
    case "$path" in Contents/Resources/*) sign_one "$APP/$path" "$SIDECAR_ENT" ;; *) sign_one "$APP/$path" "$ENT" ;; esac
  else sign_one "$APP/$path"; fi
done < "$TMP/files.sorted.tsv"

echo "==> [2/3] 签名嵌套 bundle（由深到浅）"
: > "$TMP/bundles.sorted"
while IFS= read -r b; do printf '%s\t%s\n' "$(depth "$b")" "$b" >> "$TMP/bundles.sorted"; done < "$TMP/bundles.txt"
sort -t$'\t' -k1,1nr -k2,2 "$TMP/bundles.sorted" | cut -f2 |
while IFS= read -r b; do
  case "$b" in
    *.framework) sign_one "$APP/$b" ;;          # 框架主库不带 entitlements
    *) sign_one "$APP/$b" "$ENT" ;;
  esac
done

echo "==> [3/3] 签名主应用（最后一步）"
sign_one "$APP" "$ENT"

if [ "$DRY_RUN" = 1 ]; then
  if [ "$ADHOC" = 0 ] && [ "$NOTARIZE" = 1 ]; then echo "==> 公证（dry-run）"; notarize_app "$APP"; fi
  echo "==> dry-run 结束，未改动任何文件"
  exit 0
fi

if [ "$VERIFY" = 1 ]; then
  echo "==> 校验签名结果"
  "$SELF_DIR/verify_mac.sh" "$APP"
fi

if [ "$ADHOC" = 0 ] && [ "$NOTARIZE" = 1 ]; then
  echo "==> 公证 .app 并钉票据"
  notarize_app "$APP"
  if [ "$VERIFY" = 1 ]; then "$SELF_DIR/verify_mac.sh" "$APP"; fi
fi
echo "==> 完成"
