# shellcheck shell=bash
# sign_mac.sh / verify_mac.sh 共用的函数。只被 source，不单独运行。兼容 macOS 自带 bash 3.2。

SIGNING_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_ENTITLEMENTS="$SIGNING_DIR/../shell/resources/entitlements.mac.plist"                 # Electron 主程序与 Helper
DEFAULT_SIDECAR_ENTITLEMENTS="$SIGNING_DIR/../shell/resources/entitlements.sidecar.mac.plist"  # Resources/ 下的 sidecar 可执行文件

die() { echo "错误：$*" >&2; exit 2; }

# 列出 .app 里所有 Mach-O（用 file 判断，不看扩展名；符号链接不算）。
# 输出每行：<类型>\t<相对路径>，类型 = exec | lib（.so/.dylib/framework 主库/bundle 都归 lib）
list_macho() {
  local root="$1" path desc kind
  (cd "$root" && find . -type f ! -type l -print0 | xargs -0 file -0 2>/dev/null) |
  while IFS= read -r -d '' path && IFS= read -r desc; do
    case "$desc" in
      *Mach-O*executable*) kind=exec ;;
      *Mach-O*) kind=lib ;;
      *) continue ;;
    esac
    printf '%s\t%s\n' "$kind" "${path#./}"
  done
}

# 列出需要作为 bundle 整体签名的目录（.app / .framework / .xpc / .appex），不含根 app 自己，相对路径
list_bundles() {
  local root="$1"
  (cd "$root" && find . -type d \( -name '*.app' -o -name '*.framework' -o -name '*.xpc' -o -name '*.appex' \) -print) |
    sed 's#^\./##' | grep -v '^$' || true
}

# bundle 的主可执行文件（相对 root）。bundle 整体签名时会连它一起签，所以不进「单个文件」队列。
bundle_main_exe() {
  local root="$1" b="$2" info exe
  case "$b" in
    *.framework)
      info="$root/$b/Resources/Info.plist"
      exe=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$info" 2>/dev/null) || return 1
      # 框架主库经 Versions/Current 指向 Versions/A 里的真实文件
      local real; real=$(cd "$root/$b/Versions" 2>/dev/null && ls -d [A-Z]* 2>/dev/null | head -1)
      [ -n "$real" ] && echo "$b/Versions/$real/$exe" ;;
    *)
      info="$root/$b/Contents/Info.plist"
      exe=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$info" 2>/dev/null) || return 1
      echo "$b/Contents/MacOS/$exe" ;;
  esac
}

# 路径深度（用于由内到外排序）
depth() { awk -F/ '{print NF}' <<<"$1"; }

# 取签名信息：输出 codesign -dvv 的 stderr
sig_info() { codesign -dvv "$1" 2>&1 || true; }

# 签名人标识：ad-hoc -> adhoc；未签名 -> unsigned；否则 TeamIdentifier
signer_of() {
  local info; info="$(sig_info "$1")"
  if grep -q 'code object is not signed at all' <<<"$info"; then echo unsigned
  elif grep -q '^Signature=adhoc' <<<"$info" || grep -q 'flags=.*adhoc' <<<"$info"; then echo adhoc
  else sed -n 's/^TeamIdentifier=//p' <<<"$info" | head -1; fi
}

# entitlements 键名列表（排序、每行一个）
ent_keys_of_file() {  # 已签名的 Mach-O / bundle
  codesign -d --entitlements :- "$1" 2>/dev/null | plutil -p - 2>/dev/null | sed -n 's/^ *"\([^"]*\)" =>.*/\1/p' | sort || true
}
ent_keys_of_plist() { plutil -p "$1" | sed -n 's/^ *"\([^"]*\)" =>.*/\1/p' | sort; }
