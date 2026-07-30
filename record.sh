#!/bin/bash
# 录制：把手机上的真实手势录成事件日志，并解析为可回放的动作脚本
#
#   ./record.sh start [输出.actions]   录制手势，Ctrl-C 结束并自动解析
#   ./record.sh raw   [输出.log]       只录原始 getevent 日志
#   ./record.sh parse <原始.log> [输出.actions]
#   ./record.sh coords                 屏幕开启坐标浮层（手动读坐标）
#   ./record.sh coords-off
#   ./record.sh widgets                列出当前界面控件中心坐标
#   ./record.sh info                   显示触摸设备与量程

set -u
cd "$(dirname "$0")"
source lib/common.sh

RAW_LOG=""
OUT_ACTIONS=""

# ---------------------------------------------------------------- 原始录制

# 录制原始事件日志（Ctrl-C 结束）
raw() {
  check_device
  local out="${1:-record_$(date +%m%d_%H%M%S).log}" dev
  dev=$(touch_dev)
  [ -n "$dev" ] || die "未找到触摸屏设备节点"

  echo "触摸设备 : $dev"
  echo "输出文件 : $out"
  echo "开始录制，请在手机上操作；完成后按 Ctrl-C 结束"
  echo "----------------------------------------------------"

  sh_ getevent -lt "$dev" > "$out"
  echo "已保存: $out ($(wc -l < "$out" | tr -d ' ') 行事件)"
  RAW_LOG="$out"
}

# ---------------------------------------------------------------- 解析

# parse <raw.log> [out.actions]
# 输出中间格式 .actions，每行: tap x y | long x y ms | swipe x1 y1 x2 y2 ms | sleep sec
parse() {
  local log="${1:?usage: parse <raw.log> [out.actions]}"
  local out="${2:-${log%.log}.actions}"
  [ -s "$log" ] || die "日志为空或不存在: $log"

  check_device
  init_size
  local rng maxx maxy
  rng=$(touch_range)
  maxx=${rng% *}; maxy=${rng#* }

  python3 lib/parse_events.py "$log" "$W" "$H" "${maxx:-0}" "${maxy:-0}" > "$out" || {
    rm -f "$out"; die "解析失败"
  }
  echo "已生成动作脚本: $out"
  echo "----------------------------------------------------"
  grep -v '^#' "$out" | head -20
  local n
  n=$(grep -cv -e '^#' -e '^sleep' -e '^$' "$out")
  echo "----------------------------------------------------"
  echo "共 $n 个手势。回放: ./replay.sh run $out"
  OUT_ACTIONS="$out"
}

# ---------------------------------------------------------------- 一步到位

start() {
  local out="${1:-record_$(date +%m%d_%H%M%S).actions}"
  local raw="${out%.actions}.log"
  trap 'echo; echo "录制结束，开始解析..."' INT
  raw "$raw" || true
  trap - INT
  [ -s "$raw" ] || die "没有录到事件"
  parse "$raw" "$out"
}

# ---------------------------------------------------------------- 辅助取坐标

coords() {
  check_device
  sh_ settings put system pointer_location 1
  sh_ settings put system show_touches 1
  echo "已开启坐标浮层 + 触摸反馈，手指按屏幕即可在顶部读到 X/Y"
  echo "关闭: ./record.sh coords-off"
}

coords-off() {
  sh_ settings put system pointer_location 0
  sh_ settings put system show_touches 0
  echo "已关闭坐标浮层"
}

widgets() { check_device; list_widgets; }

info() {
  check_device
  init_size
  local dev rng
  dev=$(touch_dev); rng=$(touch_range "$dev")
  echo "分辨率     : ${W}x${H}"
  echo "density    : $(sh_ wm density | tr -d '\r' | tail -1 | awk -F': ' '{print $2}')"
  echo "触摸设备   : $dev"
  echo "原始量程   : X 0-${rng% *}  Y 0-${rng#* }"
  echo "当前界面   : $(current_activity)"
}

usage() { sed -n '2,10p' "$0" | sed 's/^#\{1,\} \?//'; }

cmd="${1:-start}"; shift || true
case "$cmd" in
  start|raw|parse|coords|coords-off|widgets|info) "$cmd" "$@" ;;
  -h|--help|help) usage ;;
  *) usage; exit 1 ;;
esac
