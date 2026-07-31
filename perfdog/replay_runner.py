# coding: utf-8
"""驱动 replay.sh 执行回放，并把回放进度实时回调给调用方。

被 test.py 用作 PerfDog 采集期间的 workload：
    采集启动 -> run_replay() 阻塞直到回放真正结束 -> stop + save_data
从而摆脱 time.sleep 猜时长的做法。
"""

import logging
import os
import re
import signal
import subprocess
import threading
import time

# perfdog/ 的上一级即项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPLAY_SH = os.path.join(PROJECT_ROOT, 'replay.sh')
CASES_DIR = os.path.join(PROJECT_ROOT, 'cases')

# replay.sh 多轮回放时打印的轮次分隔行： ===== 第 1/3 轮 =====
ROUND_RE = re.compile(r'第\s*(\d+)\s*/\s*(\d+)\s*轮')
# 每轮结束： 完成 N 个动作
DONE_RE = re.compile(r'完成\s+(\d+)\s+个动作')


class ReplayError(RuntimeError):
    """回放进程异常退出"""


def resolve_case(case):
    """解析动作文件路径：绝对路径 > 当前目录 > 项目根 > cases/ > cases/<name>.actions"""
    candidates = [case]
    if not os.path.isabs(case):
        candidates += [
            os.path.join(PROJECT_ROOT, case),
            os.path.join(CASES_DIR, case),
            os.path.join(CASES_DIR, case + '.actions'),
        ]
    for path in candidates:
        if os.path.isfile(path):
            return os.path.abspath(path)
    raise FileNotFoundError('找不到动作文件: %s' % case)


def build_env(speed=None, serial=None, dry=False, no_sleep=False):
    env = os.environ.copy()
    if speed is not None:
        env['SPEED'] = str(speed)
    if serial:
        env['SERIAL'] = str(serial)
    if dry:
        env['DRY'] = '1'
    if no_sleep:
        env['NO_SLEEP'] = '1'
    return env


def run_replay(case, loop=1, speed=None, serial=None, dry=False, no_sleep=False,
               on_round=None, on_action=None, timeout=None):
    """同步执行 ./replay.sh run <case> <loop>，直到回放结束才返回。

    :param on_round:  回调 (轮次, 总轮次)，可用于打 PerfDog label
    :param on_action: 回调 (动作描述行)
    :param timeout:   秒，超时则杀掉回放进程
    :return: 回放实际耗时（秒）
    :raise ReplayError: 回放进程返回非 0
    """
    if not os.access(REPLAY_SH, os.X_OK):
        raise ReplayError('replay.sh 不存在或不可执行: %s' % REPLAY_SH)

    case_path = resolve_case(case)
    cmd = [REPLAY_SH, 'run', case_path, str(loop)]
    env = build_env(speed, serial, dry, no_sleep)

    logging.info('Replay: 开始回放 %s  轮次=%s  SPEED=%s',
                 os.path.basename(case_path), loop, env.get('SPEED', '1'))

    begin = time.time()
    proc = subprocess.Popen(
        cmd,
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,     # 避免子进程抢占标准输入
        text=True,
        bufsize=1,
        encoding='utf-8',
        errors='replace',
        start_new_session=True,       # 独立进程组，便于整组终止
    )

    def _signal_group(sig):
        """整组终止：只杀 bash 的话，其 sleep/adb 子进程仍会占住管道"""
        try:
            os.killpg(os.getpgid(proc.pid), sig)
        except (ProcessLookupError, PermissionError):
            pass

    # 读 stdout 会一直阻塞到 EOF，超时只能靠看门狗线程主动终止进程组
    timed_out = threading.Event()
    watchdog = None
    if timeout:
        def _kill_on_timeout():
            timed_out.set()
            logging.error('Replay: 超时 %ss，强制结束回放', timeout)
            _signal_group(signal.SIGKILL)

        watchdog = threading.Timer(timeout, _kill_on_timeout)
        watchdog.daemon = True
        watchdog.start()

    try:
        for raw in proc.stdout:
            line = raw.rstrip()
            if not line:
                continue
            logging.info('Replay| %s', line)

            m = ROUND_RE.search(line)
            if m and on_round:
                try:
                    on_round(int(m.group(1)), int(m.group(2)))
                except Exception:
                    logging.exception('on_round 回调异常')
                continue

            if on_action and (DONE_RE.search(line) is None):
                try:
                    on_action(line)
                except Exception:
                    logging.exception('on_action 回调异常')

        proc.wait()
    except KeyboardInterrupt:
        logging.warning('Replay: 收到中断，正在结束回放进程')
        _signal_group(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _signal_group(signal.SIGKILL)
        raise
    finally:
        if watchdog:
            watchdog.cancel()
        if proc.stdout:
            proc.stdout.close()

    elapsed = time.time() - begin
    if timed_out.is_set():
        raise ReplayError('回放超时（%ss），已强制结束，实际执行 %.1fs' % (timeout, elapsed))
    if proc.returncode != 0:
        raise ReplayError('回放失败，退出码 %s' % proc.returncode)

    logging.info('Replay: 回放结束，耗时 %.1fs', elapsed)
    return elapsed
