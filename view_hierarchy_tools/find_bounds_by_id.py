#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""根据资源 id 在视图树 JSON 中查找组件 bounds，便于自动化点击。

解析由 `view_hierarchy_tool.py` 生成的视图树 JSON，定位给定 id 的组件，
输出其可点击区域（bounds + 中心点）。

重要：视图树里每个节点的 bounds 是「相对父组件」的坐标（与 dumpsys 输出一致），
本脚本会沿父链累加偏移，将结果换算为「相对最外层 UI 组件 / 手机屏幕」的
绝对坐标，可直接用于 `adb shell input tap`。

规则：
  - 若目标组件自身 bounds 为全 0（left=top=right=bottom=0，常见于
    ViewStub / GONE 的容器），则沿父链向上查找最近一个 bounds 非全 0 的
    祖先组件，以其绝对 bounds 作为实际点击区域（父组件的 bounds 优先）。

用法示例：
    python3 find_bounds_by_id.py -f view_tree.json -i app:id/swipe
    python3 find_bounds_by_id.py -f view_tree.json -i swipe        # 仅传资源名
    python3 find_bounds_by_id.py -f view_tree.json -i swipe --tap -s <serial>
"""
import argparse
import json
import sys


# ---------------------------------------------------------------------------
# 判定 / 匹配逻辑
# ---------------------------------------------------------------------------
def is_zero_area(bounds):
    """bounds 缺失或面积为 0（width/height 为 0，即无实际布局区域）视为无效。

    用于判断「是否回退到父组件」：该判定基于组件自身相对父的坐标（width/height），
    与屏幕绝对偏移无关，避免「0,0,0,0 累加父偏移后变成 0,150,0,150」而漏掉回退。
    """
    if not bounds:
        return True
    return bounds.get("width", 0) == 0 or bounds.get("height", 0) == 0


def match_id(node_id, target):
    """精确匹配，或仅传资源名（如 'swipe' 匹配 'app:id/swipe'）。"""
    if not node_id:
        return False
    if node_id == target:
        return True
    # 支持 "app:id/swipe" / "android:id/swipe" 等前缀 + 资源名
    return node_id == "app:id/" + target or node_id.endswith("/" + target)


def to_abs_bounds(bounds, parent_left, parent_top):
    """把相对父组件的 bounds 换算为屏幕绝对坐标。

    bounds 为 None（无空间信息的容器节点）时返回 None，且其绝对原点
    等同于父原点（不贡献偏移）。
    """
    if not bounds:
        return None
    al = bounds["left"] + parent_left
    at = bounds["top"] + parent_top
    ar = bounds["right"] + parent_left
    ab = bounds["bottom"] + parent_top
    return {
        "left": al,
        "top": at,
        "right": ar,
        "bottom": ab,
        "width": ar - al,
        "height": ab - at,
    }


def find_node_with_path(node, target, path=None, parent_left=0, parent_top=0):
    """DFS 查找目标节点。

    返回 (node, abs_bounds, path)：
      - abs_bounds: 目标节点的「屏幕绝对坐标」bounds（已换算）；
      - path: 祖先链，每个元素为 {"node", "abs_bounds"}（不含自身）。
    未找到返回 None。
    """
    if path is None:
        path = []
    abs_bounds = to_abs_bounds(node.get("bounds"), parent_left, parent_top)
    if match_id(node.get("id"), target):
        return node, abs_bounds, path
    # 子节点的父原点 = 本节点绝对原点
    child_origin_left = abs_bounds["left"] if abs_bounds else parent_left
    child_origin_top = abs_bounds["top"] if abs_bounds else parent_top
    for child in node.get("children", []) or []:
        child_path = path + [{"node": node, "abs_bounds": abs_bounds}]
        res = find_node_with_path(
            child, target, child_path, child_origin_left, child_origin_top
        )
        if res:
            return res
    return None


def resolve_bounds(node, node_abs_bounds, path):
    """解析实际点击区域（绝对坐标）。

    返回 (bounds, source_id)：
      - 自身相对 bounds 非「零面积」时直接用自身绝对 bounds；
      - 否则沿父链向上取最近一个非「零面积」祖先（父组件优先），用其绝对 bounds；
      - 若整条链路都无效则返回 (None, None)。

    「是否回退」依据组件自身的相对 bounds（零面积）判断，输出则一律用绝对坐标。
    """
    if not is_zero_area(node.get("bounds")):
        return node_abs_bounds, node.get("id")
    for entry in reversed(path):
        if not is_zero_area(entry["node"].get("bounds")):
            return entry["abs_bounds"], entry["node"].get("id")
    return None, None


def center(bounds):
    """bounds 中心点（屏幕绝对坐标，用于 tap）。"""
    return (
        (bounds["left"] + bounds["right"]) // 2,
        (bounds["top"] + bounds["bottom"]) // 2,
    )


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="根据资源 id 在视图树 JSON 中查找组件可点击区域（bounds + 中心点）。"
    )
    ap.add_argument(
        "-f", "--file", default="view_tree.json", help="视图树 JSON 文件路径"
    )
    ap.add_argument(
        "-i",
        "--id",
        required=True,
        help="目标组件的资源 id，如 'app:id/swipe'，也可只传资源名如 'swipe'",
    )
    ap.add_argument(
        "--tap",
        action="store_true",
        help="额外输出 adb shell input tap 命令（需要 -s 指定设备 serial）",
    )
    ap.add_argument("-s", "--serial", help="设备 serial（配合 --tap 使用）")
    ap.add_argument(
        "--json", action="store_true", help="仅输出 JSON 结果（便于其它脚本解析）"
    )
    args = ap.parse_args()

    with open(args.file, encoding="utf-8") as f:
        tree = json.load(f)

    found = find_node_with_path(tree, args.id)
    if not found:
        msg = "错误：未在视图树中找到 id 匹配 '%s' 的组件。" % args.id
        if args.json:
            print(json.dumps({"found": False, "error": msg}, ensure_ascii=False))
        else:
            sys.exit(msg)

    node, node_abs_bounds, path = found
    bounds, source_id = resolve_bounds(node, node_abs_bounds, path)

    result = {
        "found": True,
        "target_id": node.get("id"),
        "target_class": node.get("class"),
        "bounds": bounds,
        "bounds_source_id": source_id,
        "used_parent": source_id != node.get("id"),
    }

    if bounds is None:
        msg = "错误：组件及其所有祖先的 bounds 均为全 0，无法确定点击区域。"
        if args.json:
            result["error"] = msg
            print(json.dumps(result, ensure_ascii=False))
        else:
            sys.exit(msg)
    else:
        cx, cy = center(bounds)
        result["center"] = {"x": cx, "y": cy}
        if args.tap:
            adb = "adb" + (" -s %s" % args.serial if args.serial else "")
            result["tap_command"] = "%s shell input tap %d %d" % (adb, cx, cy)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("[*] 目标组件: %s (%s)" % (result["target_id"], result["target_class"]))
        print("[*] 坐标已换算为相对屏幕（最外层 UI 组件）的绝对坐标。")
        if result["used_parent"]:
            print(
                "[*] 自身 bounds 为全 0，已采用祖先组件 '%s' 的 bounds。"
                % result["bounds_source_id"]
            )
        b = result["bounds"]
        print(
            "[*] 可点击区域(绝对) bounds: left=%d top=%d right=%d bottom=%d (w=%d h=%d)"
            % (b["left"], b["top"], b["right"], b["bottom"], b["width"], b["height"])
        )
        print("[*] 中心点(绝对): (%d, %d)" % (result["center"]["x"], result["center"]["y"]))
        if "tap_command" in result:
            print("[*] 点击命令: %s" % result["tap_command"])


if __name__ == "__main__":
    main()
