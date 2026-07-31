#!/bin/bash
# 回放：执行录制生成的 .actions 动作脚本
#
#   ./replay.sh run <文件.actions> [重复次数]   回放（默认1次）
#   ./replay.sh show <文件.actions>             预览动作，不执行
#   ./replay.sh export <文件.actions> [out.sh]  导出为独立的纯 adb 脚本
#   ./replay.sh check                           检查 input 注入权限
#
# 环境变量:
#   SPEED=2      速度倍率，2=两倍速（手势时长与间隔均减半）
#   DRY=1        只打印将要执行的 adb 命令
#   NO_SLEEP=1   忽略手势之间的等待

set -u
cd "$(dirname "$0")"
source lib/common.sh

SPEED="${SPEED:-1}"
DRY="${DRY:-0}"
NO_SLEEP="${NO_SLEEP:-0}"

# 按 SPEED 缩放时长(ms)，最小 50
scale_ms() { awk -v v="$1" -v s="$SPEED" 'BEGIN{r=v/s; printf "%d", (r<50?50:r)}'; }
scale_s()  { awk -v v="$1" -v s="$SPEED" 'BEGIN{printf "%.2f", v/s}'; }

run_cmd() {
  if [ "$DRY" = "1" ]; then
    echo "  [dry] $ADB shell $*"
  else
    sh_ "$@" </dev/null
  fi
}

# 逐行执行动作文件
_exec_actions() {
  local file="$1" i=0
  while read -r op a b c d e; do
    case "$op" in
      ''|\#*) continue ;;
      tap)
        i=$((i+1)); printf '%3d  tap   %s,%s\n' "$i" "$a" "$b"
        run_cmd input tap "$a" "$b"
        ;;
      long)
        i=$((i+1)); local ms; ms=$(scale_ms "${c:-800}")
        printf '%3d  long  %s,%s  %sms\n' "$i" "$a" "$b" "$ms"
        run_cmd input swipe "$a" "$b" "$a" "$b" "$ms"
        ;;
      swipe)
        i=$((i+1)); local ms; ms=$(scale_ms "${e:-300}")
        printf '%3d  swipe %s,%s -> %s,%s  %sms\n' "$i" "$a" "$b" "$c" "$d" "$ms"
        run_cmd input swipe "$a" "$b" "$c" "$d" "$ms"
        ;;
      key)
        i=$((i+1)); printf '%3d  key   %s\n' "$i" "$a"
        run_cmd input keyevent "$a"
        ;;
      text)
        i=$((i+1)); printf '%3d  text  %s\n' "$i" "$a"
        run_cmd input text "$a"
        ;;
      sleep)
        [ "$NO_SLEEP" = "1" ] && continue
        sleep "$(scale_s "$a")"
        ;;
      *) echo "  跳过未知动作: $op $a" >&2 ;;
    esac
  done < "$file"
  echo "完成 $i 个动作"
}

run() {
  local file="${1:?usage: run <文件.actions> [重复次数]}" loop="${2:-1}"
  [ -s "$file" ] || die "动作文件不存在或为空: $file"
  check_device
  [ "$DRY" = "1" ] || check_inject || exit 1

  echo "回放 $file   重复 ${loop} 次   SPEED=${SPEED}"
  echo "----------------------------------------------------"
  local n
  for n in $(seq 1 "$loop"); do
    # 始终打印轮次头，便于外部工具（如 PerfDog 联动）按轮打标
    echo "===== 第 $n/$loop 轮 ====="
    _exec_actions "$file"
  done
}

show() {
  local file="${1:?usage: show <文件.actions>}"
  DRY=1 NO_SLEEP=1 _exec_actions "$file"
}

# 导出为不依赖本仓库的独立脚本
export_sh() {
  local file="${1:?usage: export <文件.actions> [out.sh]}"
  local out="${2:-${file%.actions}_replay.sh}"
  {
    echo '#!/bin/bash'
    echo "# 由 $file 自动生成，可独立运行"
    echo 'ADB="adb"; [ -n "${SERIAL:-}" ] && ADB="adb -s $SERIAL"'
    echo
    while read -r op a b c d e; do
      case "$op" in
        ''|\#*) continue ;;
        tap)   echo "\$ADB shell input tap $a $b" ;;
        long)  echo "\$ADB shell input swipe $a $b $a $b ${c:-800}" ;;
        swipe) echo "\$ADB shell input swipe $a $b $c $d ${e:-300}" ;;
        key)   echo "\$ADB shell input keyevent $a" ;;
        text)  echo "\$ADB shell input text $a" ;;
        sleep) echo "sleep $a" ;;
      esac
    done < "$file"
  } > "$out"
  chmod +x "$out"
  echo "已导出: $out"
}

check() {
  check_device
  init_size
  echo "设备 : $($ADB devices | tr -d '\r' | grep -w device | head -1)"
  echo "屏幕 : ${W}x${H}"
  if check_inject; then
    echo "注入权限 : OK，可以回放"
  else
    echo "注入权限 : 不可用" >&2
    exit 1
  fi
}

usage() { sed -n '2,13p' "$0" | sed 's/^#\{1,\} \?//'; }

cmd="${1:-}"; shift || true
case "$cmd" in
  run|show|check) "$cmd" "$@" ;;
  export)         export_sh "$@" ;;
  -h|--help|help|'') usage ;;
  *) usage; exit 1 ;;
esac
