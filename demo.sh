#!/bin/bash
# 操作 Demo：各类 input 事件的示例与常见测试场景
#
#   ./demo.sh list                     列出所有 demo
#   ./demo.sh info                     设备信息
#   ./demo.sh all                      依次演示 点击/长按/双击/四方向滑动/拖拽/按键
#   ./demo.sh tap_demo                 点击类演示
#   ./demo.sh swipe_demo               滑动类演示
#   ./demo.sh key_demo                 按键类演示
#   ./demo.sh text_demo <文本>         文本输入演示
#   ./demo.sh widget_demo <控件文本>   按控件文字点击
#   ./demo.sh feed_scroll <包名> [次数] 启动App后连续慢滑（滑动性能场景）
#   ./demo.sh app_switch <包名> [次数]  冷启/退出循环（启动性能场景）
#
# 环境变量: SERIAL=<序列号> 指定设备

set -u
cd "$(dirname "$0")"
source lib/common.sh

setup() { check_device; init_size; check_inject || exit 1; }

step() { echo; echo ">>> $*"; }

# ---------------------------------------------------------------- 点击

tap_demo() {
  setup
  local cx=$((W/2)) cy=$((H/2))

  step "单击屏幕中心 ($cx,$cy)"
  tap $cx $cy; sleep 1

  step "相对坐标单击 (0.5, 0.35)  —— 换机型自动适配"
  rtap 0.5 0.35; sleep 1

  step "长按 1000ms"
  longpress $cx $cy 1000; sleep 1

  step "双击 (间隔 120ms)"
  doubletap $cx $cy 120; sleep 1

  step "精细触摸序列 DOWN -> MOVE -> UP（自定义轨迹）"
  touch_down $cx $((H*7/10))
  local y
  for y in 6 5 4 3; do
    touch_move $cx $((H*y/10)); sleep 0.05
  done
  touch_up $cx $((H*3/10))
}

# ---------------------------------------------------------------- 滑动

swipe_demo() {
  setup

  step "上滑（翻到下一页/下一条）"
  swipe_up 300; sleep 1

  step "下滑（下拉刷新方向）"
  swipe_down 300; sleep 1

  step "左滑（切到右侧 Tab）"
  swipe_left 300; sleep 1

  step "右滑（返回手势/切到左侧 Tab）"
  swipe_right 300; sleep 1

  step "慢速匀速上滑 1500ms —— 无 fling，适合测滑动帧率"
  slow_swipe_up 1500; sleep 1

  step "自定义滑动 swipe x1 y1 x2 y2 ms"
  swipe $((W/2)) $((H*3/4)) $((W/2)) $((H/4)) 500; sleep 1

  step "拖拽 draganddrop（桌面图标、列表排序）"
  drag $((W/2)) $((H/2)) $((W/2)) $((H/3)) 1000; sleep 1

  step "滚轮向下滚动"
  scroll_v -2
}

# ---------------------------------------------------------------- 按键

key_demo() {
  setup

  step "返回键"       ; key_back;   sleep 1
  step "多任务"       ; key_recent; sleep 1.5
  step "返回键退出"   ; key_back;   sleep 1
  step "音量下键"     ; key KEYCODE_VOLUME_DOWN; sleep 1
  step "长按电源键"   ; key_long KEYCODE_POWER; sleep 1; key_back; sleep 1
  step "组合键截屏（电源+音量下）"; key_combo KEYCODE_POWER KEYCODE_VOLUME_DOWN; sleep 1
  step "回到桌面"     ; key_home
}

# ---------------------------------------------------------------- 文本

text_demo() {
  setup
  local s="${1:-hello world}"
  step "输入文本: $s  （空格自动转 %s；中文需装 ADBKeyboard）"
  text "$s"; sleep 1
  step "回车"     ; key_enter; sleep 1
  step "删除3个字符"
  local i; for i in 1 2 3; do key_del; done
}

# ---------------------------------------------------------------- 控件定位

widget_demo() {
  setup
  local kw="${1:-}"
  if [ -z "$kw" ]; then
    step "当前界面控件坐标一览"
    list_widgets
    echo
    echo "用法: ./demo.sh widget_demo \"控件文字\"  即可点击"
    return
  fi
  step "查找并点击控件: $kw"
  local xy
  xy=$(find_center "$kw") || die "未找到控件: $kw"
  echo "中心坐标: $xy"
  tap ${xy}
}

# ---------------------------------------------------------------- 性能测试场景

# 滑动流畅度：连续慢速上滑
feed_scroll() {
  setup
  local pkg="${1:?usage: feed_scroll <包名> [次数]}" n="${2:-10}"

  step "启动 $pkg"
  launch_app "$pkg"; sleep 5
  echo "当前界面: $(current_activity)"

  local i
  for i in $(seq 1 "$n"); do
    echo "  滑动 $i/$n"
    slow_swipe_up 1200
    sleep 1
  done

  step "回到桌面"
  key_home
}

# 启动耗时：冷启动 + 强杀 循环
app_switch() {
  setup
  local pkg="${1:?usage: app_switch <包名> [次数]}" n="${2:-5}"
  local i
  for i in $(seq 1 "$n"); do
    step "第 $i/$n 轮冷启动"
    stop_app "$pkg" >/dev/null 2>&1
    sleep 1
    sh_ am start-activity -W -S "$pkg" 2>/dev/null | tr -d '\r' | grep -E 'TotalTime|WaitTime' \
      || { launch_app "$pkg"; }
    sleep 4
    key_home
    sleep 1
  done
}

# ---------------------------------------------------------------- 综合

all() {
  setup
  echo "屏幕 ${W}x${H}"
  tap_demo
  swipe_demo
  key_demo
  echo
  echo "全部演示结束"
}

info() {
  check_device
  init_size
  echo "设备     : $($ADB devices -l | tr -d '\r' | grep -w device | head -1)"
  echo "分辨率   : ${W}x${H}"
  echo "density  : $(sh_ wm density | tr -d '\r' | tail -1 | awk -F': ' '{print $2}')"
  echo "Android  : $(sh_ getprop ro.build.version.release | tr -d '\r')"
  echo "触摸设备 : $(touch_dev)"
  echo "当前界面 : $(current_activity)"
  echo -n "注入权限 : "
  if check_inject 2>/dev/null; then echo "OK"; else echo "受限（见上方提示）"; fi
}

list() { usage; }

usage() { sed -n '2,15p' "$0" | sed 's/^#\{1,\} \?//'; }

cmd="${1:-list}"; shift || true
case "$cmd" in
  all|info|list|tap_demo|swipe_demo|key_demo|text_demo|widget_demo|feed_scroll|app_switch)
    "$cmd" "$@" ;;
  -h|--help|help) usage ;;
  *) echo "未知命令: $cmd" >&2; usage; exit 1 ;;
esac
