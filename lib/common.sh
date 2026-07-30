#!/bin/bash
# 公共库：adb 封装 + input 原子操作 + 控件坐标工具
# 被 record.sh / replay.sh / demo.sh 通过 source 引入，不直接执行

# ---------------------------------------------------------------- 设备连接

ADB="adb"
SERIAL="${SERIAL:-}"                       # 多设备: SERIAL=680533f ./demo.sh ...
[ -n "$SERIAL" ] && ADB="adb -s $SERIAL"

W=1080
H=1920
TOUCH_DEV="${TOUCH_DEV:-}"

sh_() { $ADB shell "$@"; }

die() { echo "ERROR: $*" >&2; exit 1; }

# 检查设备在线
check_device() {
  local n
  n=$($ADB devices | tr -d '\r' | grep -cw device)
  [ "$n" -ge 1 ] || die "没有已连接的设备，先执行 adb devices 检查"
}

# 读取真实分辨率，写入全局 W/H
init_size() {
  local s
  s=$(sh_ wm size | tr -d '\r' | tail -1 | awk -F': ' '{print $2}')
  [ -n "$s" ] || die "无法获取屏幕尺寸"
  W=${s%x*}
  H=${s#*x}
}

# 识别触摸屏设备节点(/dev/input/eventN)
touch_dev() {
  [ -n "$TOUCH_DEV" ] && { echo "$TOUCH_DEV"; return; }
  sh_ getevent -pl 2>/dev/null | tr -d '\r' | awk '
    /^add device/ { dev=$4 }
    /ABS_MT_POSITION_X/ { print dev; exit }'
}

# 触摸设备原始坐标量程: 输出 "maxX maxY"
touch_range() {
  local dev="${1:-$(touch_dev)}"
  sh_ getevent -pl "$dev" 2>/dev/null | tr -d '\r' | awk '
    function getmax(line) { if (match(line, /max +[0-9]+/)) { s=substr(line, RSTART, RLENGTH); sub(/max +/, "", s); return s } return "" }
    /ABS_MT_POSITION_X/ { mx=getmax($0) }
    /ABS_MT_POSITION_Y/ { my=getmax($0) }
    END { print mx+0, my+0 }'
}

# 相对坐标(0~1) -> 像素
px() { awk -v v="$1" -v m="$2" 'BEGIN{printf "%d", v*m}'; }

# input 注入权限自检（小米/HyperOS 常见拦截）
check_inject() {
  local out
  out=$(sh_ input keyevent KEYCODE_WAKEUP 2>&1)
  if echo "$out" | grep -q INJECT_EVENTS; then
    cat >&2 <<'EOF'
ERROR: input 事件注入被系统拒绝 (缺少 INJECT_EVENTS)
  小米/HyperOS 需在手机端开启：
    设置 → 开发者选项 → USB调试(安全设置)   [需登录小米账号，可能等待10分钟]
    同时确认 "USB安装" / "通过USB撤销权限验证" 已开启
  注：录制(record.sh)不受此限制，可先录好操作再回放。
EOF
    return 1
  fi
  return 0
}

# ---------------------------------------------------------------- 点击

tap()       { sh_ input tap "$1" "$2"; }
rtap()      { sh_ input tap "$(px "$1" "$W")" "$(px "$2" "$H")"; }
longpress() { sh_ input swipe "$1" "$2" "$1" "$2" "${3:-800}"; }
doubletap() {
  sh_ input tap "$1" "$2"
  sleep "$(awk -v d="${3:-120}" 'BEGIN{print d/1000}')"
  sh_ input tap "$1" "$2"
}

touch_down() { sh_ input motionevent DOWN "$1" "$2"; }
touch_move() { sh_ input motionevent MOVE "$1" "$2"; }
touch_up()   { sh_ input motionevent UP   "$1" "$2"; }

# ---------------------------------------------------------------- 滑动

swipe()       { sh_ input swipe "$1" "$2" "$3" "$4" "${5:-300}"; }
swipe_up()    { sh_ input swipe $((W/2)) $((H*7/10)) $((W/2)) $((H*3/10)) "${1:-300}"; }
swipe_down()  { sh_ input swipe $((W/2)) $((H*3/10)) $((W/2)) $((H*7/10)) "${1:-300}"; }
swipe_left()  { sh_ input swipe $((W*8/10)) $((H/2)) $((W*2/10)) $((H/2)) "${1:-300}"; }
swipe_right() { sh_ input swipe $((W*2/10)) $((H/2)) $((W*8/10)) $((H/2)) "${1:-300}"; }

# 慢速匀速滑动：不触发 fling，适合测滑动帧率
slow_swipe_up() { sh_ input swipe $((W/2)) $((H*8/10)) $((W/2)) $((H*2/10)) "${1:-1500}"; }

drag()      { sh_ input draganddrop "$1" "$2" "$3" "$4" "${5:-1000}"; }
scroll_v()  { sh_ input scroll --axis VSCROLL,"$1"; }
scroll_at() { sh_ input mouse scroll "$1" "$2" --axis VSCROLL,"$3"; }

# ---------------------------------------------------------------- 按键 / 文本

key()        { sh_ input keyevent "$@"; }
key_back()   { sh_ input keyevent KEYCODE_BACK; }
key_home()   { sh_ input keyevent KEYCODE_HOME; }
key_recent() { sh_ input keyevent KEYCODE_APP_SWITCH; }
key_enter()  { sh_ input keyevent KEYCODE_ENTER; }
key_del()    { sh_ input keyevent KEYCODE_DEL; }
key_power()  { sh_ input keyevent KEYCODE_POWER; }
key_wake()   { sh_ input keyevent KEYCODE_WAKEUP; }
key_long()   { sh_ input keyevent --longpress "$1"; }
key_combo()  { sh_ input keycombination -t 100 "$@"; }

# 空格转 %s；中文需安装 ADBKeyboard 输入法
text() { sh_ input text "$(echo "$1" | sed 's/ /%s/g')"; }

unlock() { key_wake; sleep 0.3; sh_ input swipe $((W/2)) $((H*8/10)) $((W/2)) $((H*2/10)) 200; }

# ---------------------------------------------------------------- 控件坐标

UI_XML="${TMPDIR:-/tmp}/ui_dump.xml"

dump_ui() {
  sh_ uiautomator dump /sdcard/ui_dump.xml >/dev/null 2>&1 \
    || die "uiautomator dump 失败（当前界面可能不支持）"
  $ADB pull /sdcard/ui_dump.xml "$UI_XML" >/dev/null 2>&1 || die "pull ui xml 失败"
}

# find_center "登录" -> "x y"
find_center() {
  dump_ui
  UI_XML="$UI_XML" python3 - "$1" <<'PY'
import os, re, sys
xml = open(os.environ['UI_XML'], encoding='utf-8').read()
kw = sys.argv[1]
for node in re.findall(r'<node[^>]*>', xml):
    if kw in node:
        m = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
        if m:
            x1, y1, x2, y2 = map(int, m.groups())
            print((x1 + x2) // 2, (y1 + y2) // 2)
            break
else:
    sys.exit(1)
PY
}

tap_text() {
  local xy
  xy=$(find_center "$1") || { echo "未找到控件: $1" >&2; return 1; }
  tap ${xy}
}

# 列出当前界面控件中心坐标
list_widgets() {
  dump_ui
  UI_XML="$UI_XML" python3 - <<'PY'
import os, re
xml = open(os.environ['UI_XML'], encoding='utf-8').read()
print(f'{"center":>12}  {"clickable":9} text / desc / id')
for n in re.findall(r'<node[^>]*>', xml):
    b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', n)
    if not b:
        continue
    x1, y1, x2, y2 = map(int, b.groups())
    if x2 - x1 <= 0 or y2 - y1 <= 0:
        continue
    g = lambda k: (re.search(k + r'="([^"]*)"', n) or [None, ''])[1]
    label = g('text') or g('content-desc') or g('resource-id').split('/')[-1]
    if label:
        print(f'{(x1+x2)//2:>5},{(y1+y2)//2:<6}  {g("clickable"):9} {label}')
PY
}

current_activity() {
  sh_ dumpsys activity activities 2>/dev/null | tr -d '\r' \
    | grep -m1 -iE 'ResumedActivity' \
    | grep -oE '[A-Za-z0-9_.]+/[A-Za-z0-9_.]+' | head -1
}

screenshot() { $ADB exec-out screencap -p > "${1:-shot_$(date +%H%M%S).png}"; }

launch_app() {
  sh_ monkey -p "${1:?usage: launch_app <package>}" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
}
stop_app() { sh_ am force-stop "${1:?usage: stop_app <package>}"; }
