# PerfDog Service 自动化工具

在 PerfDog 采集期间执行 UI 回放，**采集时长由回放真实结束时间决定**，不再用 `time.sleep` 猜。

## 环境配置

建议用虚拟环境（项目根目录已有 `.venv`）：

```bash
pip install --upgrade pip
pip install grpcio protobuf
```

`config.py` 不再存放任何密钥，改为从 **环境变量 > `local_env/.env`** 加载：

```bash
cp local_env/.env.example local_env/.env
```

```txt
SERVICE_TOKEN = '<申请到的 token>'
SERVICE_PATH  = '<PerfDogService 可执行文件路径>'
PD_PACKAGE    = '<被测 App 包名>'
PD_DEVICE     = ''            # 留空则自动探测唯一在线设备
```

`local_env/` 已被 `.gitignore` 忽略（仅保留 `.env.example`），不会把 token 提交进仓库。
环境变量 `PERFDOG_TOKEN` / `PERFDOG_SERVICE_PATH` / `PD_PACKAGE` / `PD_DEVICE` 优先级更高；
`PERFDOG_ENV_FILE` 可指定其它配置文件路径。

配置在连接 PerfDog **之前**校验：token 缺失、路径不存在或无可执行权限都会直接报错退出。

## 执行时序

```
启动 PerfDog 采集
    ↓ 等待首帧性能数据（超时 60s 仅告警）
set_label('replay_begin')
    ↓ subprocess 调用 ./replay.sh run <case> <loop>
    ↓ 阻塞直到回放进程退出；每轮打标 round_N_M
add_note('replay_end') → test.stop() → test.save_data()
```

关键点：回放以子进程方式运行，Python 侧 `for line in proc.stdout` 阻塞读取直到 EOF，因此**回放不结束绝不会走到 `save_data`**。

## 用法

推荐用项目根目录的一键入口：

```bash
./pipeline.sh wechat_enter_live                 # 回放 1 轮
./pipeline.sh wechat_enter_live 5               # 回放 5 轮
./pipeline.sh wechat_enter_live 3 --speed 2 --export --export-dir ./report
./pipeline.sh --duration 30                     # 不回放，纯定时采集
```

`pipeline.sh` 会自动选择 `.venv` 解释器、校验依赖、先跑 `./replay.sh check` 确认注入权限，再调用 `test.py`。

直接调用 `test.py`：

```bash
.venv/bin/python perfdog/test.py --case wechat_enter_live --loop 3
```

### 参数

| 参数 | 说明 |
| --- | --- |
| `-d, --device` | 设备 ID。缺省读 `PD_DEVICE`，再缺省自动探测唯一在线设备；多设备时必须指定 |
| `-p, --package` | 被测包名。缺省读 `PD_PACKAGE`，两者都无则报错退出 |
| `--wifi` | 设备通过 `adb connect` 连接 |
| `-c, --case` | 动作文件，可写用例名 / `cases/x.actions` / 绝对路径 |
| `-n, --loop` | 回放轮次，默认 1 |
| `--speed` | 回放倍率，透传 `replay.sh` 的 `SPEED` |
| `--replay-timeout` | 回放超时秒数，超时强制结束整个进程组 |
| `--duration` | 不接回放时的纯定时采集秒数 |
| `--case-name` | PerfDog 用例名，默认 `<用例>_x<轮次>_<时间戳>` |
| `--no-upload` | 不上传云端，**必须配合 `--export`** |
| `--export` / `--export-dir` / `--export-format` | 导出本地文件，格式 `excel`(默认)/`json`/`protobuf` |
| `--all-types` | 启用设备支持的全部指标 |
| `--quiet-perf-data` | 不逐条打印性能数据 |

`pipeline.sh` 另支持环境变量 `PD_DEVICE` / `PD_PACKAGE` / `PYTHON`。

## 标签与元信息

- `replay_begin`：回放开始点
- `round_N_M`：第 N 轮开始点，导出的 Excel 中每轮是**独立工作表**，便于分轮对比
- `replay_end`：note，标记回放结束
- `extra_info`：随报告写入 `case` / `loop` / `speed` / `duration_s`

## 文件说明

| 文件 | 职责 |
| --- | --- |
| `test.py` | 入口：参数解析、采集配置、时序编排、`save_data` |
| `replay_runner.py` | 驱动 `replay.sh`，流式解析输出、轮次回调、超时看门狗 |
| `test_base.py` | Service 创建、设备/包名解析、指标枚举、浮窗设置 |
| `config.py` | 配置加载器（不含密钥），读环境变量与 `local_env/.env` |
| `perfdog.py` / `perfdog_pb2*.py` | 官方 SDK 封装与 gRPC 桩代码 |

## 实测结果

设备 Xiaomi 25113PN0EC / Android 16，用例 `wechat_enter_live`（7 个动作，含 31s 等待）：

| 轮次 | 回放耗时 | 实际采集 | 导出工作表 |
| --- | --- | --- | --- |
| 1 | 31.7s | 31.7s | `all` `Label1` `replay_begin` `@FrameInfo` |
| 2 | 63.4s | 63.5s | `all` `Label1` `round_1_2` `round_2_2` `@FrameInfo` |

采集时长与回放耗时一致，说明已完全由回放结束控制。

## 排障

| 现象 | 原因与处理 |
| --- | --- |
| `缺少配置 SERVICE_TOKEN` | 未创建 `local_env/.env`，执行 `cp local_env/.env.example local_env/.env` 后填值 |
| `SERVICE_PATH 指向的文件不存在` | PerfDogService 路径错误或版本升级后目录名变了 |
| `未指定被测 App 包名` | 传 `-p`，或在 `local_env/.env` 配 `PD_PACKAGE`；用 `python perfdog/cmds.py getapps <设备ID>` 查包名 |
| `检测到多台设备` | 用 `-d` 指定，或配 `PD_DEVICE` |
| `save_data` 报 `无效的操作` | 既不上传也不导出。`--no-upload` 必须配合 `--export` |
| `device not found` | 设备 ID 写错，或 `adb connect` 的设备未加 `--wifi` |
| 60s 未收到性能数据 | App 未在前台 / 包名错误。脚本会告警但仍继续回放 |
| `input 注入权限不可用` | 小米需开 **USB调试(安全设置)**，详见项目根 `readme.md` |
| 回放卡死 | 加 `--replay-timeout`，超时会 `killpg` 终止整个进程组 |
| `Locally cancelled by application!` | `test.stop()` 关闭数据流的正常日志，非错误 |

## 参考

- PerfDog Service 自动化文档：https://perfdog.qq.com/article_detail?id=10143&issue_id=0&plat_id=2
- PerfDog Service 自动化 Demo：https://github.com/perfdog/perfdog-service-demo-v2/blob/master/readme_zh.md
