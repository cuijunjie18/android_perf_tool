#!/bin/bash
# PerfDog 采集 + UI 回放 一键入口
#
#   ./pipeline.sh <用例> [轮次] [其它 test.py 参数...]
#
# 示例:
#   ./pipeline.sh wechat_enter_live            # 回放 1 轮
#   ./pipeline.sh wechat_enter_live 5          # 回放 5 轮
#   ./pipeline.sh wechat_enter_live 3 --speed 2 --export --export-dir ./report
#   ./pipeline.sh --duration 30                # 不回放，纯定时采集 30s
#
# 环境变量:
#   PD_DEVICE=<设备ID>         留空则自动探测唯一在线设备
#   PD_PACKAGE=<包名>          被测 App 包名
#   PYTHON=.venv/bin/python    指定解释器
#
# 设备与包名也可写在 local_env/.env（见 local_env/.env.example），优先级：
#   命令行 > 环境变量 > local_env/.env > 唯一在线设备（仅设备）
#
# 时序: 启动采集 → 等首帧数据 → 回放(阻塞至结束) → stop + save_data

set -eu
cd "$(dirname "$0")"

# 解释器：优先 PYTHON，其次项目 .venv，最后系统 python3
if [ -n "${PYTHON:-}" ]; then
  PY="$PYTHON"
elif [ -x .venv/bin/python ]; then
  PY="$(pwd)/.venv/bin/python"
else
  PY="python3"
fi

"$PY" -c "import grpc, google.protobuf" 2>/dev/null || {
  echo "ERROR: 缺少依赖，请先执行: $PY -m pip install grpcio protobuf" >&2
  exit 1
}

usage() { sed -n '2,21p' "$0" | sed 's/^#\{1,\} \?//'; }

case "${1:-}" in
  ''|-h|--help|help) usage; exit 0 ;;
esac

ARGS=()
# 第一个参数不是选项时，视为用例名；紧随的纯数字视为轮次
if [ "${1#-}" = "$1" ]; then
  ARGS+=(--case "$1"); shift
  if [ $# -gt 0 ] && [ -z "${1//[0-9]/}" ]; then
    ARGS+=(--loop "$1"); shift
  fi
fi

# 设备/包名不在此处兜底，交由 test.py 按 .env 与自动探测统一解析
[ -n "${PD_DEVICE:-}" ] && ARGS+=(--device "$PD_DEVICE")
[ -n "${PD_PACKAGE:-}" ] && ARGS+=(--package "$PD_PACKAGE")

# 回放前先确认注入权限，避免起了采集才发现点不动
./replay.sh check >/dev/null || {
  echo "ERROR: input 注入权限不可用，执行 ./replay.sh check 查看详情" >&2
  exit 1
}

exec "$PY" perfdog/test.py "${ARGS[@]}" "$@"
