#!/usr/bin/env bash
# macOS 签名校验（L-09）。可对任意已签名的 .app 或 .dmg 运行，输出「通过/失败」清单，有失败时退出码为 1（供 CI 用）。
#
# 用法：
#   desktop/signing/verify_mac.sh [选项] <DongAI.app | DongAI.dmg>
# 选项：
#   --release          发布模式：不允许 ad-hoc，必须是真实证书签名，spctl 必须通过，必须已公证并钉票据。
#                      默认模式下 ad-hoc 签名时这几项记为「跳过」（本机演练用），其余检查照常严格。
#   --entitlements F   Electron 主程序/Helper 期望的 entitlements，默认 desktop/shell/resources/entitlements.mac.plist
#   --sidecar-entitlements F  Contents/Resources/ 下可执行文件期望的，默认 .../entitlements.sidecar.mac.plist
# 退出码：0 全部通过（可有跳过）；1 有失败；2 用法错误
#
# 检查项（.app）：
#   1. codesign --verify --deep --strict 整体校验
#   2. 每个 Mach-O 都已签名且签名有效（用 file 判断，列出所有未签名/仅链接器占位签名/校验失败的文件）
#   3. 全部 Mach-O 的签名人一致（TeamIdentifier 相同；ad-hoc 全部 ad-hoc）
#   4. Hardened Runtime（flags 含 runtime）
#   5. entitlements：可执行文件的键集合必须等于声明的集合，其余文件不得出现声明之外的键
#   6. 安全时间戳（真实证书必须有；ad-hoc 跳过）
#   7. spctl --assess --type execute；stapler validate（公证票据）
# 检查项（.dmg）：dmg 自身签名有效、签名人、stapler validate、spctl --type open，并挂载后对里面的 .app 做上面全部检查
set -uo pipefail

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib_mac.sh
source "$SELF_DIR/lib_mac.sh"

RELEASE=0; ENT="$DEFAULT_ENTITLEMENTS"; SIDECAR_ENT="$DEFAULT_SIDECAR_ENTITLEMENTS"; TARGET=""
while [ $# -gt 0 ]; do
  case "$1" in
    --release) RELEASE=1 ;;
    --entitlements) shift; ENT="${1:?--entitlements 需要参数}" ;;
    --sidecar-entitlements) shift; SIDECAR_ENT="${1:?--sidecar-entitlements 需要参数}" ;;
    -h|--help) sed -n '2,/^set -uo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) die "未知选项 $1" ;;
    *) [ -z "$TARGET" ] || die "只能给一个目标"; TARGET="$1" ;;
  esac
  shift
done
[ -n "$TARGET" ] || die "用法：verify_mac.sh [--release] <app 或 dmg>"
[ -e "$TARGET" ] || die "找不到 $TARGET"
[ -f "$ENT" ] || die "找不到 entitlements 文件 $ENT"
[ -f "$SIDECAR_ENT" ] || die "找不到 sidecar entitlements 文件 $SIDECAR_ENT"

PASS=0; FAIL=0; SKIP=0
pass() { PASS=$((PASS+1)); echo "  [通过] $1"; }
fail() {
  FAIL=$((FAIL+1)); echo "  [失败] $1"; shift
  local l n
  for l in "$@"; do
    n=$(printf '%s\n' "$l" | wc -l | tr -d ' ')
    printf '%s\n' "$l" | head -25 | sed 's/^ */         /'
    [ "$n" -gt 25 ] && echo "         …… 共 $n 行，只显示前 25 行"
  done
  return 0
}
skip() { SKIP=$((SKIP+1)); echo "  [跳过] $1"; }
# 发布模式下「ad-hoc 时跳过」的项要记为失败
skip_or_fail() { if [ "$RELEASE" = 1 ]; then fail "$1 （--release 要求真实证书签名）"; else skip "$1"; fi; }

TMP="$(mktemp -d)"; MNT=""
cleanup() { [ -n "$MNT" ] && hdiutil detach "$MNT" -quiet -force >/dev/null 2>&1; rm -rf "$TMP"; }
trap cleanup EXIT

EXPECT_MAIN="$(ent_keys_of_plist "$ENT")"; EXPECT_SIDECAR="$(ent_keys_of_plist "$SIDECAR_ENT")"

check_app() {
  local app="$1" out rc
  echo "== 校验 .app：$app"

  # 1. 整体校验
  out="$(codesign --verify --deep --strict --verbose=2 "$app" 2>&1)"; rc=$?
  out="$(grep -v -E '^--(prepared|validated):' <<<"$out")"   # 去掉逐个嵌套项的进度行，只留错误
  if [ $rc -eq 0 ]; then pass "codesign --verify --deep --strict"; else fail "codesign --verify --deep --strict" "$out"; fi

  # 2~6. 逐个 Mach-O
  list_macho "$app" > "$TMP/macho.tsv"
  local total; total=$(wc -l < "$TMP/macho.tsv" | tr -d ' ')
  : > "$TMP/bad_unsigned"; : > "$TMP/bad_invalid"; : > "$TMP/bad_runtime"; : > "$TMP/bad_ent"; : > "$TMP/bad_ts"; : > "$TMP/signers"
  local kind path info signer keys extra missing
  while IFS=$'\t' read -r kind path; do
    info="$(codesign -dvv "$app/$path" 2>&1)"
    if grep -q 'not signed at all' <<<"$info"; then
      echo "${path}（完全未签名）" >> "$TMP/bad_unsigned"; continue
    fi
    if grep -q 'linker-signed' <<<"$info"; then
      echo "${path}（只有链接器占位的 ad-hoc 签名）" >> "$TMP/bad_unsigned"; continue
    fi
    if grep -q '^Signature=adhoc' <<<"$info"; then signer=adhoc
    else signer="$(sed -n 's/^TeamIdentifier=//p' <<<"$info" | head -1)"; [ -n "$signer" ] && [ "$signer" != "not set" ] || signer="无TeamID"; fi
    printf '%s\t%s\n' "$signer" "$path" >> "$TMP/signers"
    out="$(codesign --verify --strict "$app/$path" 2>&1)" || echo "${path}：$(head -1 <<<"$out")" >> "$TMP/bad_invalid"
    grep -q 'flags=0x[0-9a-f]*([^)]*runtime' <<<"$info" || echo "$path" >> "$TMP/bad_runtime"
    if [ "$signer" != adhoc ] && ! grep -q '^Timestamp=' <<<"$info"; then echo "$path" >> "$TMP/bad_ts"; fi
    case "$path" in Contents/Resources/*) EXPECT_KEYS="$EXPECT_SIDECAR" ;; *) EXPECT_KEYS="$EXPECT_MAIN" ;; esac
    keys="$(ent_keys_of_file "$app/$path")"
    extra="$(comm -13 <(printf '%s\n' "$EXPECT_KEYS") <(printf '%s\n' "$keys") | grep -v '^$' | tr '\n' ' ')"
    if [ "$kind" = exec ]; then missing="$(comm -23 <(printf '%s\n' "$EXPECT_KEYS") <(printf '%s\n' "$keys") | grep -v '^$' | tr '\n' ' ')"
    else missing=""; fi
    if [ -n "$extra" ] || [ -n "$missing" ]; then echo "${path}：多出[${extra% }] 缺少[${missing% }]" >> "$TMP/bad_ent"; fi
  done < "$TMP/macho.tsv"

  if [ ! -s "$TMP/bad_unsigned" ]; then pass "全部 $total 个 Mach-O 都已签名"
  else fail "有未签名的 Mach-O（$(wc -l < "$TMP/bad_unsigned" | tr -d ' ') 个）" "$(cat "$TMP/bad_unsigned")"; fi
  if [ ! -s "$TMP/bad_invalid" ]; then pass "全部 Mach-O 签名校验有效（codesign --verify --strict）"
  else fail "Mach-O 签名校验失败" "$(cat "$TMP/bad_invalid")"; fi

  local nsig; nsig=$(cut -f1 "$TMP/signers" | sort -u | wc -l | tr -d ' ')
  if [ "$nsig" -le 1 ]; then pass "签名人一致（$(cut -f1 "$TMP/signers" | sort -u | head -1)）"
  else fail "签名人不一致（$nsig 种）" "$(cut -f1 "$TMP/signers" | sort | uniq -c | awk '{print $2" ×"$1}')" ; fi

  if [ ! -s "$TMP/bad_runtime" ]; then pass "Hardened Runtime：全部 Mach-O 带 runtime 标志"
  else fail "缺少 Hardened Runtime 标志（--options runtime）" "$(cat "$TMP/bad_runtime")"; fi

  if [ ! -s "$TMP/bad_ent" ]; then pass "entitlements 与声明一致（主程序/Helper：$(echo $EXPECT_MAIN | sed 's/com.apple.security.cs.//g')；sidecar：$(echo $EXPECT_SIDECAR | sed 's/com.apple.security.cs.//g')）"
  else fail "entitlements 与声明的 plist 不一致" "$(cat "$TMP/bad_ent")"; fi

  local main_signer; main_signer="$(signer_of "$app")"
  if [ "$main_signer" = adhoc ]; then
    skip_or_fail "安全时间戳（ad-hoc 签名没有）"
  elif [ ! -s "$TMP/bad_ts" ]; then pass "全部 Mach-O 带安全时间戳"
  else fail "缺少安全时间戳（公证会拒绝）" "$(cat "$TMP/bad_ts")"; fi

  # 7. Gatekeeper 与公证票据
  if [ "$main_signer" = adhoc ] || [ "$main_signer" = unsigned ]; then
    skip_or_fail "spctl --assess：ad-hoc/未签名的包必然被 Gatekeeper 拒绝"
    skip_or_fail "stapler validate：ad-hoc 包不可能有公证票据"
  else
    out="$(spctl --assess --type execute -vv "$app" 2>&1)"; rc=$?
    if [ $rc -eq 0 ]; then pass "spctl --assess --type execute：$(tail -1 <<<"$out")"; else fail "spctl --assess --type execute" "$out"; fi
    out="$(xcrun stapler validate "$app" 2>&1)"; rc=$?
    if [ $rc -eq 0 ]; then pass "stapler validate：公证票据已钉入"; else
      if [ "$RELEASE" = 1 ]; then fail "stapler validate：没有公证票据" "$out"; else skip "stapler validate：没有公证票据（非 --release 不强制）"; fi
    fi
  fi
}

check_dmg() {
  local dmg="$1" out rc signer
  echo "== 校验 .dmg：$dmg"
  out="$(codesign --verify --verbose=2 "$dmg" 2>&1)"; rc=$?
  if [ $rc -eq 0 ]; then pass "dmg codesign --verify"; else fail "dmg codesign --verify（dmg 未签名或被改动）" "$out"; fi
  signer="$(signer_of "$dmg")"
  if [ "$signer" = adhoc ] || [ "$signer" = unsigned ]; then
    skip_or_fail "dmg 签名人为 $signer"
    skip_or_fail "dmg 公证票据（stapler validate）"
    skip_or_fail "dmg spctl --assess --type open"
  else
    pass "dmg 签名人：$signer"
    out="$(xcrun stapler validate "$dmg" 2>&1)"; rc=$?
    if [ $rc -eq 0 ]; then pass "dmg 公证票据已钉入（stapler validate）"; else
      if [ "$RELEASE" = 1 ]; then fail "dmg 没有公证票据" "$out"; else skip "dmg 没有公证票据（非 --release 不强制）"; fi
    fi
    out="$(spctl --assess --type open --context context:primary-signature -vv "$dmg" 2>&1)"; rc=$?
    if [ $rc -eq 0 ]; then pass "dmg spctl --assess --type open"; else fail "dmg spctl --assess" "$out"; fi
  fi
  MNT="$TMP/mnt"; mkdir -p "$MNT"
  if hdiutil attach "$dmg" -nobrowse -readonly -noverify -mountpoint "$MNT" -quiet >/dev/null 2>&1; then
    local app; app="$(find "$MNT" -maxdepth 1 -name '*.app' | head -1)"
    if [ -n "$app" ]; then check_app "$app"; else fail "dmg 里没有找到 .app"; fi
  else
    fail "无法挂载 dmg"; MNT=""
  fi
}

case "$TARGET" in
  *.dmg) check_dmg "$TARGET" ;;
  *.app) check_app "$TARGET" ;;
  *) die "目标必须是 .app 或 .dmg：$TARGET" ;;
esac

echo
if [ "$FAIL" -eq 0 ]; then echo "结果：通过（通过 ${PASS}，跳过 ${SKIP}，失败 0）"; [ "$SKIP" -gt 0 ] && echo "注意：有跳过项（ad-hoc 签名），这种包不能发布；发布前用 --release 复查。"; exit 0
else echo "结果：失败（通过 ${PASS}，跳过 ${SKIP}，失败 ${FAIL}）"; exit 1; fi
