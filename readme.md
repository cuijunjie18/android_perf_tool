# Android 自动化性能分析

基于 `adb` + `getevent` / `input` 的 Android UI 自动化工具集，用于**录制真实手势 → 生成动作脚本 → 稳定回放**，配合性能采集做可复现的性能测试。

无需 root，无需 App 侵入，无需安装 Python 依赖。

---

## 前置条件

### 1. 环境

| 依赖 | 说明 |
| --- | --- |
| `adb` | Android SDK Platform-Tools，需在 `PATH` 中 |
| `python3` | 仅用标准库，无需 pip 安装 |
| Bash | macOS / Linux 自带 |

```bash
adb devices -l      # 确认设备已连接
```

### 2. 手机端设置

- 打开**开发者选项** → **USB 调试**
- **允许模拟点击 / 注入事件**。小米 & HyperOS 机型必须额外开启：
  - **USB调试（安全设置）** —— 需登录小米账号，开启后可能等待约 10 分钟生效
  - **USB安装**、**通过USB撤销权限验证**

  未开启时 `input` 会报错：
  ```
  SecurityException: Injecting input events requires ... INJECT_EVENTS permission
  ```
  可用 `./replay.sh check` 一键自检。

- 建议关闭屏幕自动旋转、固定屏幕亮度、关闭自动锁屏，避免回放坐标错位。
- 如需在屏幕上实时看到操作坐标：
  ```bash
  ./record.sh coords        # 开启指针位置浮层 + 触摸反馈
  ./record.sh coords-off    # 关闭
  ```

---

## 目录结构

```
android_perf_tool/
├── record.sh              录制：真实手势 → .actions 动作脚本
├── replay.sh              回放：执行 .actions
├── demo.sh                操作 demo：各类 input 事件示例与性能场景
├── perfdog_demo.sh        （预留）PerfDog 性能采集联动
└── lib/
    ├── common.sh          公共库：adb 封装 / input 原子操作 / 控件定位
    └── parse_events.py    getevent 日志解析器
```

三个入口脚本均 `source lib/common.sh`，各自独立可运行。

---

## 快速开始

```bash
# 1. 环境自检
./demo.sh info

# 2. 录制一段操作（在手机上正常操作，完成后 Ctrl-C）
./record.sh start login.actions

# 3. 回放 3 轮
./replay.sh run login.actions 3
```

---

## 一、录制 `record.sh`

把手机上的真实手指操作录成事件日志，并解析为可读、可编辑的动作脚本。

```bash
./record.sh start [输出.actions]      # 录制 + 自动解析（推荐）
./record.sh raw   [输出.log]          # 只录原始 getevent 日志
./record.sh parse <原始.log> [输出.actions]
./record.sh coords / coords-off       # 屏幕坐标浮层开关
./record.sh widgets                   # 列出当前界面控件中心坐标
./record.sh info                      # 触摸设备与坐标量程
```

`info` 输出示例：

```
分辨率     : 1220x2656
density    : 520
触摸设备   : /dev/input/event7
原始量程   : X 0-121999  Y 0-265599
当前界面   : com.miui.home/.launcher.Launcher
```

### 原理

读取 `adb shell getevent -lt /dev/input/eventN` 的内核触摸事件流，按 `ABS_MT_TRACKING_ID` / `BTN_TOUCH` 切分手势，把原始坐标（如 X 0-121999）按比例换算为屏幕像素，再按位移与时长归类：

| 判定条件 | 输出动作 |
| --- | --- |
| 位移 < 15px 且时长 < 400ms | `tap` |
| 位移 < 15px 且时长 ≥ 400ms | `long` |
| 位移 ≥ 15px | `swipe` |
| 手势间隔 > 0.05s | `sleep` |

阈值可在 `lib/parse_events.py` 顶部的 `TAP_DIST` / `LONG_MS` 调整。

> **注意**：`input` 命令注入的事件不经过内核输入设备，因此录制只能捕获**真实手指操作**，无法录制脚本自身产生的事件。这是预期行为。
>
> 录制只需读权限，**不受 `INJECT_EVENTS` 限制**，可以先把操作录好，再去开权限做回放。

---

## 二、回放 `replay.sh`

```bash
./replay.sh run <文件.actions> [重复次数]    # 回放，默认 1 次
./replay.sh show <文件.actions>              # 预览动作，不执行
./replay.sh export <文件.actions> [out.sh]   # 导出为独立的纯 adb 脚本
./replay.sh check                            # 注入权限自检
```

环境变量：

| 变量 | 作用 |
| --- | --- |
| `SPEED=2` | 速度倍率，2 = 两倍速（手势时长与间隔均减半） |
| `DRY=1` | 只打印将要执行的 adb 命令，不实际执行 |
| `NO_SLEEP=1` | 忽略手势之间的等待，快速跑完 |
| `SERIAL=<序列号>` | 多设备时指定目标设备 |

示例：

```bash
./replay.sh run feed.actions 20            # 压测：连续回放 20 轮
SPEED=2 ./replay.sh run feed.actions       # 2 倍速
DRY=1 NO_SLEEP=1 ./replay.sh run feed.actions   # 调试：只看命令
./replay.sh export feed.actions ci_case.sh # 导出给 CI，不依赖本仓库
```

回放输出示例：

```
回放 feed.actions   重复 2 次   SPEED=1
----------------------------------------------------
===== 第 1/2 轮 =====
  1  swipe 626,2653 -> 715,2321  104ms
  2  swipe 1011,1796 -> 801,1835  50ms
完成 2 个动作
```

---

## 三、操作 Demo `demo.sh`

各类 `input` 事件的可运行示例，也可直接当性能测试场景用。

```bash
./demo.sh list                         # 列出所有 demo
./demo.sh info                         # 设备信息 + 注入权限自检
./demo.sh all                          # 全套演示

./demo.sh tap_demo                     # 单击 / 相对坐标 / 长按 / 双击 / DOWN-MOVE-UP
./demo.sh swipe_demo                   # 四方向 / 慢速 / 自定义 / 拖拽 / 滚轮
./demo.sh key_demo                     # 返回 / 多任务 / 长按 / 组合键截屏
./demo.sh text_demo "hello world"      # 文本输入
./demo.sh widget_demo "登录"            # 按控件文字定位并点击

./demo.sh feed_scroll <包名> [次数]     # 启动 App 后连续慢滑 —— 滑动流畅度场景
./demo.sh app_switch  <包名> [次数]     # 冷启动 / 强杀循环 —— 启动耗时场景
```

---

## 四、`.actions` 动作格式

录制与回放通过纯文本格式解耦，可手写、可 `diff`、可纳入版本管理。

```
# 由 rec.log 生成  屏幕 1220x2656  原始量程 121999x265599
# 手势数 2
swipe 626 2653 715 2321 104
sleep 0.48
swipe 1011 1796 801 1835 50
```

| 语法 | 含义 |
| --- | --- |
| `tap x y` | 单击 |
| `long x y ms` | 长按 ms 毫秒 |
| `swipe x1 y1 x2 y2 ms` | 滑动，ms 越大越慢、惯性越小 |
| `key KEYCODE_BACK` | 按键 |
| `text 内容` | 输入文本 |
| `sleep 0.5` | 等待秒数 |
| `# ...` | 注释 |

录制后可手工编辑：插入 `key KEYCODE_BACK`、调大 `sleep` 等待加载、把滑动时长改成 1500ms 做匀速滑动测帧率。

---

## 五、坐标获取的四种方式

| 方式 | 命令 | 适用场景 |
| --- | --- | --- |
| 屏幕坐标浮层 | `./record.sh coords` | 快速确认单个点的坐标 |
| 控件树 dump | `./record.sh widgets` | **推荐**，拿到控件中心坐标 + 文字，稳定不怕换机型 |
| 手势录制 | `./record.sh start` | 记录一整套连续操作 |
| 截图量取 | `./demo.sh info` 后配合截图 | 补充手段 |

`widgets` 输出示例：

```
      center  clickable text / desc / id
  136,237     true      返回
  610,390     true      USB安装 允许通过USB安装应用
```

拿到文字后可直接按文字点击，避免硬编码坐标：

```bash
./demo.sh widget_demo "USB安装"
```

---

## 六、常用 adb input 命令速查

以 1220x2656 为例（中心点 610,1328）：

### 点击

```bash
adb shell input tap 610 1328                        # 单击
adb shell input swipe 610 1328 610 1328 800         # 长按 800ms
adb shell input motionevent DOWN 610 1328           # 精细控制：按下
adb shell input motionevent MOVE 610 1000           #            移动
adb shell input motionevent UP   610 1000           #            抬起
```

### 滑动

```bash
adb shell input swipe 610 1859 610 796  300         # 上滑：下一页 / 下一条
adb shell input swipe 610 796  610 1859 300         # 下滑：下拉刷新
adb shell input swipe 976 1328 244 1328 300         # 左滑：切右侧 Tab
adb shell input swipe 244 1328 976 1328 300         # 右滑：返回手势
adb shell input swipe 610 2124 610 531  1500        # 慢速匀速：无 fling，测帧率
adb shell input draganddrop 610 1328 610 800 1000   # 拖拽
adb shell input scroll --axis VSCROLL,-2            # 滚轮向下
```

`duration` 越小惯性越大。测滑动流畅度建议用 1200~2000ms 匀速滑，结果更稳定。

### 按键与文本

```bash
adb shell input keyevent KEYCODE_BACK               # 返回
adb shell input keyevent KEYCODE_HOME               # 桌面
adb shell input keyevent KEYCODE_APP_SWITCH         # 多任务
adb shell input keyevent --longpress KEYCODE_POWER  # 长按
adb shell input keycombination -t 100 KEYCODE_POWER KEYCODE_VOLUME_DOWN   # 截屏
adb shell input text "hello%sworld"                 # 空格用 %s
```

> 中文输入需安装 [ADBKeyboard](https://github.com/senzhk/ADBKeyBoard) 输入法。

---

## 七、典型工作流

### 场景 1：Feed 滑动流畅度回归

```bash
./record.sh start feed.actions       # 录一遍进入 Feed 并滑动的操作
vi feed.actions                      # 把 swipe 时长统一改成 1500，去掉多余 sleep
./replay.sh run feed.actions 20      # 回放 20 轮，同时用 PerfDog / dumpsys gfxinfo 采集
```

### 场景 2：冷启动耗时

```bash
./demo.sh app_switch com.example.app 10     # 输出每轮 TotalTime / WaitTime
```

### 场景 3：多机型一致性

`.actions` 中的坐标随录制机型固定。换分辨率机型时任选：

- 用 `./demo.sh widget_demo "文字"` / `find_center` 走控件定位，天然适配；
- 或在目标机型上重新 `./record.sh start`。

---

## 八、故障排查

| 现象 | 原因与处理 |
| --- | --- |
| `SecurityException ... INJECT_EVENTS` | 未开启模拟点击。小米需开 **USB调试(安全设置)**，用 `./replay.sh check` 复验 |
| `sendevent: Permission denied` | 写 `/dev/input/*` 需 root。本工具回放走 `input`，无需理会 |
| 录制文件为空 | 录制期间没有**真实手指**操作；脚本注入的事件录不到 |
| `uiautomator dump 失败` | 当前界面禁止 dump（如某些安全键盘 / 播放器），改用坐标录制 |
| 回放只执行了第一个动作 | 已修复（`adb shell` 抢占 stdin，`run_cmd` 已加 `</dev/null`） |
| 回放坐标错位 | 录制与回放的屏幕方向或分辨率不一致，锁定方向后重录 |
| 找不到触摸设备 | 手动指定：`TOUCH_DEV=/dev/input/event7 ./record.sh start` |
| 多设备冲突 | `SERIAL=680533f ./replay.sh run x.actions` |

---

## 九、公共库 API

在自己的脚本里复用：

```bash
#!/bin/bash
cd "$(dirname "$0")"
source lib/common.sh

check_device        # 设备在线校验
init_size           # 读取分辨率到全局 W / H
check_inject        # 注入权限自检

tap 610 1328              # 点击
rtap 0.5 0.5              # 相对坐标点击（0~1），跨机型适配
longpress 610 1328 1000   # 长按
doubletap 610 1328        # 双击
swipe_up 300              # 上滑
slow_swipe_up 1500        # 慢速匀速上滑
drag 610 1328 610 800     # 拖拽

key_back / key_home / key_recent / key_enter
text "hello world"

tap_text "登录"            # 按控件文字点击
find_center "登录"         # 返回 "x y"
list_widgets              # 列出控件坐标

launch_app com.example.app
stop_app   com.example.app
current_activity
screenshot shot.png
```

---

## 已验证环境

- 设备：Xiaomi pudding / 25113PN0EC，1220x2656，density 520，Android 16
- 主机：macOS，Bash + Python 3
