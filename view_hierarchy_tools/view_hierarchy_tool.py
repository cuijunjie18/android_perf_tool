#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Android View Hierarchy 抓取与解析工具。

通过 adb 的 `dumpsys activity` 读取系统持有的真实 View 对象树。
与 `uiautomator dump` 走 Accessibility 快照不同，dumpsys 直接遍历 ViewRootImpl
中的 View 实例，因此能穿透微信等会主动屏蔽 uiautomator 的应用。

用法示例:
    python3 view_hierarchy_tool.py
    python3 view_hierarchy_tool.py -c com.tencent.mm/.ui.LauncherUI
    python3 view_hierarchy_tool.py -s <serial> --print-tree --raw raw.txt
"""
import argparse
import json
import re
import subprocess
import sys


# ---------------------------------------------------------------------------
# adb 执行
# ---------------------------------------------------------------------------
def run_adb(args, serial=None, timeout=60):
    cmd = ["adb"]
    if serial:
        cmd += ["-s", serial]
    cmd += args
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        sys.exit("错误：未找到 adb，请确认它已在 PATH 中。")
    except subprocess.TimeoutExpired:
        sys.exit("错误：adb 命令超时（%d 秒）。" % timeout)
    if proc.returncode != 0:
        sys.exit("错误：adb 执行失败：\n" + proc.stderr.strip())
    return proc.stdout


# ---------------------------------------------------------------------------
# 定位当前 Resumed Activity: 包名/Activity
# ---------------------------------------------------------------------------
def detect_resumed_activity(serial):
    out = run_adb(["shell", "dumpsys", "activity", "activities"], serial)
    m = re.search(
        r"(?:ResumedActivity|mResumedActivity):\s*ActivityRecord\{[^}]*\s+([\w.]+)/(\.?[\w.]+)",
        out,
    )
    if not m:
        out2 = run_adb(["shell", "dumpsys", "window", "windows"], serial)
        m = re.search(
            r"mResumeActivity:\s*ActivityRecord\{[^}]*\s+([\w.]+)/(\.?[\w.]+)", out2
        )
    if not m:
        sys.exit(
            "错误：无法获取当前 Resumed Activity，请确认设备已解锁、目标界面在前台，"
            "且 adb 拥有足够权限。"
        )
    return "%s/%s" % (m.group(1), m.group(2))


# ---------------------------------------------------------------------------
# 解析 View Hierarchy 文本
# ---------------------------------------------------------------------------
# 节点行形如:
#   android.widget.FrameLayout{e3b8c12 V.E...... ......I. 0,0-1080,2160 #id/content}
#   DecorView@f1c2d3e[LauncherUI]
#   DecorView@f1c2d3e[LauncherUI]{...}
#   com.android.internal.policy.DecorView{feb8aa6 ... aid=11}[FinderLivePersonalCenterUI]
#     —— 注意根 DecorView 的 [ActivityName] 可能出现在花括号之后，两种位置都要兼容
NODE_RE = re.compile(
    r"^(?P<indent>\s*)"
    r"(?P<cls>[\w$.]+)"
    r"(?:@(?P<hash>[0-9a-fA-F]+))?"
    r"(?:\[(?P<act1>[^\]]+)\])?"
    r"(?P<brace>\{.*\})?"
    r"(?:\[(?P<act2>[^\]]+)\])?$"
)
BOUNDS_RE = re.compile(r"(\d+),(\d+)-(\d+),(\d+)")


def parse_bounds(content):
    m = BOUNDS_RE.search(content)
    if not m:
        return None
    l, t, r, b = map(int, m.groups())
    return {
        "left": l,
        "top": t,
        "right": r,
        "bottom": b,
        "width": r - l,
        "height": b - t,
    }


def parse_id(content):
    # 真实 dumpsys 输出里资源 id 形如:
    #   #7f09312f app:id/finder_wx_recent_watch_tv
    # 优先匹配可读资源名（<package>:id/<name> 或 id/<name>），丢弃前导的十六进制引用
    m = re.search(r"(?:[\w.]+:)?id/[\w.]+", content)
    if m:
        return m.group(0)
    return None
    # 退化为纯十六进制引用（无资源名的场景）
    # m = re.search(r"#([0-9a-fA-F]+)", content)
    # return m.group(1) if m else None


def parse_flags(content):
    # 由 [A-Z.] 连续组成、长度 8~11 的 token 视为 mViewFlags / view state flags
    # （不使用 \b 词边界，因为 token 以 '.' 结尾时边界判断会失效）
    return re.findall(r"[A-Z.]{8,11}", content)


def derive_state(flags):
    state = {}
    if not flags:
        return state
    f1 = flags[0]
    if len(f1) > 0:
        state["visible"] = f1[0] == "V"
        state["invisible"] = f1[0] == "I"
        state["gone"] = f1[0] == "G"
    if len(f1) > 2:
        state["focusable"] = f1[1] == "F"
        state["enabled"] = f1[2] == "E"
    return state


def parse_hierarchy(text):
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if "View Hierarchy:" in line:
            start = i + 1
            break
    if start is None:
        return None

    root = {"class": "<root>", "children": []}
    stack = [(0, root)]  # (indent, node)

    for line in lines[start:]:
        if not line.strip():
            continue
        m = NODE_RE.match(line)
        if not m:
            # 遇到零缩进的非节点行，说明 View Hierarchy 段落已结束
            if not line.startswith((" ", "\t")):
                break
            continue

        indent = len(m.group("indent"))
        brace = m.group("brace") or ""
        node = {
            "class": m.group("cls"),
            "id": parse_id(brace),
            "bounds": parse_bounds(brace),
            "flags": parse_flags(brace),
        }
        if m.group("hash"):
            node["hash"] = m.group("hash")
        act = m.group("act1") or m.group("act2")
        if act:
            node["activity"] = act
        state = derive_state(node["flags"])
        if state:
            node["state"] = state

        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1] if stack else root
        parent.setdefault("children", []).append(node)
        stack.append((indent, node))

    return root


# ---------------------------------------------------------------------------
# 终端树形打印
# ---------------------------------------------------------------------------
def print_tree(node, depth=0):
    pad = "  " * depth
    cls = node.get("class", "")
    bid = node.get("id")
    b = node.get("bounds")
    extra = []
    if bid:
        extra.append("#%s" % bid)
    if b:
        extra.append("[%d,%d][%d,%d]" % (b["left"], b["top"], b["right"], b["bottom"]))
    print(pad + cls + (" " + " ".join(extra) if extra else ""))
    for c in node.get("children", []):
        print_tree(c, depth + 1)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="抓取并解析 Android View Hierarchy（基于 dumpsys activity，"
        "可穿透 uiautomator 被屏蔽的应用）"
    )
    ap.add_argument("-s", "--serial", help="指定设备 serial（多设备时必填）")
    ap.add_argument(
        "-c",
        "--component",
        help="指定 Activity 组件 包名/Activity；不填则自动检测 Resumed Activity",
    )
    ap.add_argument("-o", "--output", default="view_tree.json", help="JSON 输出路径")
    ap.add_argument("--raw", help="保存原始 dumpsys 文本的路径")
    ap.add_argument("--input", help="直接读取已保存的 dumpsys 文本文件（跳过 adb，离线解析）")
    ap.add_argument("--print-tree", action="store_true", help="在终端打印树形结构")
    args = ap.parse_args()

    if args.input:
        with open(args.input, encoding="utf-8") as f:
            raw = f.read()
        print("[*] 已从文件读取: %s" % args.input)
    else:
        if not args.component:
            args.component = detect_resumed_activity(args.serial)
            print("[*] 当前 Resumed Activity: %s" % args.component)

        raw = run_adb(["shell", "dumpsys", "activity", args.component], args.serial)
        if "View Hierarchy:" not in raw:
            print("[*] `dumpsys activity <component>` 未包含 View Hierarchy，回退到 `dumpsys activity top`")
            raw = run_adb(["shell", "dumpsys", "activity", "top"], args.serial)

    if args.raw:
        with open(args.raw, "w", encoding="utf-8") as f:
            f.write(raw)
        print("[*] 原始文本已保存: %s" % args.raw)

    tree = parse_hierarchy(raw)
    if tree is None:
        sys.exit("错误：未能在输出中找到 View Hierarchy，请检查设备/界面状态。")

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(tree, f, ensure_ascii=False, indent=2)
    print("[*] 已生成结构化树: %s" % args.output)

    if args.print_tree:
        print("\n=== View Hierarchy ===")
        print_tree(tree, 0)


if __name__ == "__main__":
    main()
