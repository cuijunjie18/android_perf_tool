#!/usr/bin/env python3
"""把 getevent -lt 原始日志解析为动作脚本(.actions)

用法: parse_events.py <raw.log> <屏宽> <屏高> [rawMaxX] [rawMaxY]

输出格式，每行一条：
    tap   x y
    long  x y ms
    swipe x1 y1 x2 y2 ms
    sleep 秒
"""
import re
import sys

TAP_DIST = 15        # px，小于该位移视为点击
LONG_MS = 400        # ms，原地按压超过则视为长按

LINE_RE = re.compile(r'\[\s*([\d.]+)\]\s*(?:\S+:\s+)?(EV_\w+)\s+(\w+)\s+(\S+)')


def parse_val(s):
    s = s.strip()
    if s == 'DOWN':
        return 1
    if s == 'UP':
        return 0
    try:
        return int(s, 16)
    except ValueError:
        return 0


def load(path):
    evts = []
    with open(path, errors='ignore') as f:
        for line in f:
            m = LINE_RE.search(line.replace('\r', ''))
            if m:
                evts.append((float(m.group(1)), m.group(2), m.group(3),
                             parse_val(m.group(4))))
    return evts


def split_gestures(evts, sx, sy):
    """按 TRACKING_ID / BTN_TOUCH 切分为手势，每个手势是 [(t, x, y), ...]"""
    gestures, cur = [], []
    x = y = None
    down = False
    for t, typ, code, val in evts:
        if code == 'ABS_MT_TRACKING_ID':
            if val == 0xFFFFFFFF:
                if cur:
                    gestures.append(cur)
                cur, down = [], False
            else:
                cur, down = [], True
        elif code == 'ABS_MT_POSITION_X':
            x = val
        elif code == 'ABS_MT_POSITION_Y':
            y = val
        elif code == 'BTN_TOUCH':
            if val == 0:
                if cur:
                    gestures.append(cur)
                cur, down = [], False
            else:
                down = True
        elif typ == 'EV_SYN' and code == 'SYN_REPORT':
            if down and x is not None and y is not None:
                cur.append((t, sx(x), sy(y)))
    if cur:
        gestures.append(cur)
    return [g for g in gestures if g]


def main():
    if len(sys.argv) < 4:
        print(__doc__, file=sys.stderr)
        return 2

    log = sys.argv[1]
    SW, SH = int(sys.argv[2]), int(sys.argv[3])
    raw_x = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    raw_y = int(sys.argv[5]) if len(sys.argv) > 5 else 0

    evts = load(log)
    if not evts:
        print('未解析到任何事件，检查日志格式', file=sys.stderr)
        return 1

    # 量程：优先用 getevent -pl 读到的 max，否则从数据推断
    xs = [v for _, _, c, v in evts if c == 'ABS_MT_POSITION_X']
    ys = [v for _, _, c, v in evts if c == 'ABS_MT_POSITION_Y']
    RX = raw_x or (max(xs) if xs and max(xs) > SW else SW)
    RY = raw_y or (max(ys) if ys and max(ys) > SH else SH)
    if RX < SW:
        RX = SW
    if RY < SH:
        RY = SH

    clamp = lambda v, hi: max(0, min(hi - 1, v))
    sx = lambda v: clamp(round(v * SW / RX), SW)
    sy = lambda v: clamp(round(v * SH / RY), SH)

    gestures = split_gestures(evts, sx, sy)
    if not gestures:
        print('未解析到手势，确认录制期间有触摸操作', file=sys.stderr)
        return 1

    print(f'# 由 {log} 生成  屏幕 {SW}x{SH}  原始量程 {RX}x{RY}')
    print(f'# 手势数 {len(gestures)}')

    prev_end = None
    for g in gestures:
        t0, x0, y0 = g[0]
        t1, x1, y1 = g[-1]
        dur = int((t1 - t0) * 1000)
        dist = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5

        if prev_end is not None:
            gap = t0 - prev_end
            if gap > 0.05:
                print(f'sleep {gap:.2f}')

        if dist < TAP_DIST:
            if dur >= LONG_MS:
                print(f'long {x0} {y0} {dur}')
            else:
                print(f'tap {x0} {y0}')
        else:
            print(f'swipe {x0} {y0} {x1} {y1} {max(dur, 50)}')
        prev_end = t1

    return 0


if __name__ == '__main__':
    sys.exit(main())
