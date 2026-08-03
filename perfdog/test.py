# coding: utf-8
"""PerfDog 采集 + UI 回放 联动入口。

执行时序（采集时长由回放真实结束时间决定，不再靠 time.sleep 猜）：
    1. 启动 PerfDog 采集，等待首帧性能数据到达
    2. 调用 ./replay.sh run <case> <loop>，阻塞直到回放进程退出
    3. test.stop() -> test.save_data()

用法:
    python test.py --case wechat_enter_live --loop 3
    python test.py -d <设备ID> -p <包名> -c cases/x.actions -n 5 --speed 2
    python test.py --duration 30                      # 不接回放，纯定时采集
    python test.py --export --export-dir ./report     # 同时导出本地文件

设备与包名的取值优先级：命令行 > local_env/.env > 唯一在线设备（仅设备）
"""

import argparse
import logging
import os
import sys
import threading
import time

# 抑制 gRPC 在 fork 子进程（回放）时输出的告警噪声，需在导入 grpc 前设置
os.environ.setdefault('GRPC_VERBOSITY', 'ERROR')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import perfdog_pb2

import config
from perfdog import Test, TestAppBuilder
from replay_runner import ReplayError, resolve_case, run_replay
from test_base import (create_service, get_all_types, resolve_device_id,
                       resolve_package, set_floating_window)

# 等待首帧性能数据的超时（秒）
FIRST_DATA_TIMEOUT = 60

DEFAULT_TYPES = [
    perfdog_pb2.FPS,
    perfdog_pb2.FRAME_TIME,
    perfdog_pb2.CPU_USAGE,
    perfdog_pb2.MEMORY,
]
DEFAULT_DYNAMIC_TYPES = [
    (perfdog_pb2.GPU_COUNTER, 'GPU General'),
    (perfdog_pb2.GPU_COUNTER, 'GPU Stalls'),
]


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description='PerfDog 采集 + replay.sh 回放联动',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument('-d', '--device',
                   help='设备 ID，缺省读 local_env/.env 的 PD_DEVICE，再缺省自动探测唯一在线设备')
    p.add_argument('-p', '--package',
                   help='被测 App 包名，缺省读 local_env/.env 的 PD_PACKAGE')
    p.add_argument('--wifi', action='store_true', help='设备通过 adb connect 连接')

    p.add_argument('-c', '--case', help='动作文件，可写 cases/x.actions 或直接写用例名')
    p.add_argument('-n', '--loop', type=int, default=1, help='回放轮次，默认 1')
    p.add_argument('--speed', type=float, help='回放速度倍率，透传 replay.sh 的 SPEED')
    p.add_argument('--replay-timeout', type=float, help='回放超时秒数，超时强制结束')
    p.add_argument('--duration', type=float,
                   help='不指定 --case 时的纯定时采集时长（秒）')

    p.add_argument('--case-name', help='PerfDog 用例名，默认 <用例>_<轮次>_<时间戳>')
    p.add_argument('--no-upload', action='store_true', help='不上传报告到云端')
    p.add_argument('--export', action='store_true', help='导出数据到本地文件')
    p.add_argument('--export-dir', default='', help='导出目录，配合 --export')
    p.add_argument('--export-format', default='excel',
                   choices=['excel', 'json', 'protobuf'], help='导出格式，默认 excel')

    p.add_argument('--all-types', action='store_true', help='启用设备支持的全部性能指标')
    p.add_argument('--quiet-perf-data', action='store_true', help='不逐条打印性能数据')
    return p.parse_args(argv)


EXPORT_FORMATS = {
    'excel': perfdog_pb2.EXPORT_TO_EXCEL,
    'json': perfdog_pb2.EXPORT_TO_JSON,
    'protobuf': perfdog_pb2.EXPORT_TO_PROTOBUF,
}


def build_case_name(args):
    if args.case_name:
        return args.case_name
    stem = os.path.splitext(os.path.basename(args.case))[0] if args.case else 'timed'
    return '%s_x%d_%s' % (stem, args.loop, time.strftime('%m%d_%H%M%S'))


def main(argv=None):
    args = parse_args(argv)

    logging.basicConfig(format='%(asctime)s-%(levelname)s: %(message)s', level=logging.INFO)

    # 提前校验动作文件，避免起了采集才发现路径错
    if args.case:
        try:
            resolve_case(args.case)
        except FileNotFoundError as e:
            logging.error('%s', e)
            return 2
    elif args.duration is None:
        logging.error('必须指定 --case <动作文件> 或 --duration <秒>')
        return 2

    # 既不上传又不导出时 PerfDog 的 saveData 会直接返回“无效的操作”
    if args.no_upload and not args.export:
        logging.error('--no-upload 需配合 --export 使用，否则数据无处落地')
        return 2

    # 解析设备与包名：命令行 > local_env/.env > 唯一在线设备（仅设备）
    # 同时校验 token / SERVICE_PATH，全部在启动 PerfDog 之前完成
    try:
        config.ensure_configured()
        args.device = resolve_device_id(args.device)
        args.package = resolve_package(args.package)
    except config.ConfigError as e:
        logging.error('%s', e)
        return 2

    # 创建服务对象代理
    service = create_service()

    # 禁止安装 PerfDog APK，跑自动化时减少不必要的暂停打断
    service.disable_install_apk()

    # 测试过程中应用异常时的日志采集与上报
    service.update_configuration(enable_device_logs=True)
    service.update_configuration(enable_upload_device_logs=True)

    # 通过 adb connect 连接的设备需要用 get_wifi_device
    device = service.get_wifi_device(args.device) if args.wifi \
        else service.get_usb_device(args.device)
    if device is None:
        logging.error('device not found: %s', args.device)
        return 1

    return run_test_app(device, args)


def run_test_app(device, args):
    # 创建测试对象
    test = Test(device)

    # 首帧性能数据信号，用于确保回放开始前采集已真正就绪
    first_data = threading.Event()
    test.set_first_perf_data_callback(lambda: first_data.set())

    if not args.quiet_perf_data:
        test.set_perf_data_callback(lambda perf_data: logging.info(perf_data))

    # 输出测试过程中告警和错误信息，出问题便于查日志
    test.set_error_perf_data_callback(
        lambda perf_data: logging.error('PerfDog: %s', perf_data.errorData.msg))
    test.set_warning_perf_data_callback(
        lambda perf_data: logging.warning('PerfDog: %s', perf_data.warningData.msg))

    # 自动化一般配置隐藏浮窗
    set_floating_window(device)

    # 创建要测试的目标 App
    builder = test.create_test_target_builder(TestAppBuilder)
    builder.set_package_name(args.package)
    test.set_test_target(builder.build())

    # 启用/禁用性能指标
    if args.all_types:
        types, dynamic_types = get_all_types(device)
    else:
        types, dynamic_types = DEFAULT_TYPES, DEFAULT_DYNAMIC_TYPES
    if types:
        test.set_types(*types)
    if dynamic_types:
        test.set_dynamic_types(*dynamic_types)

    # 启用 APP_STARTUP_TIME 会导致每次测试重启 app；SYSTEM_LOG 会收集大量系统日志
    test.disable_type(perfdog_pb2.APP_STARTUP_TIME)
    test.disable_type(perfdog_pb2.SYSTEM_LOG)

    workload_error = None
    started_at = None

    try:
        # ---------- 1. 先启动采集 ----------
        logging.info('PerfDog: 启动采集 device=%s package=%s', args.device, args.package)
        test.start()

        if not first_data.wait(FIRST_DATA_TIMEOUT):
            logging.warning('PerfDog: %ss 内未收到性能数据，仍继续执行回放',
                            FIRST_DATA_TIMEOUT)
        started_at = time.time()
        logging.info('PerfDog: 采集就绪')

        # ---------- 2. 执行 workload，阻塞直到真正结束 ----------
        try:
            if args.case:
                _run_replay_workload(test, args, started_at)
            else:
                logging.info('定时采集 %.1fs', args.duration)
                test.set_label('timed_begin')
                time.sleep(args.duration)
        except (ReplayError, KeyboardInterrupt) as e:
            # 回放失败也要把已采集的数据落地，避免白跑
            workload_error = e
            logging.error('workload 中断: %s', e)

        # ---------- 3. 回放结束后停止并保存 ----------
        elapsed = time.time() - started_at
        test.add_note('replay_end', int(elapsed * 1000))
        test.stop()
        logging.info('PerfDog: 采集停止，实际采集 %.1fs', elapsed)

        case_name = build_case_name(args)
        export_dir = os.path.abspath(args.export_dir) if args.export_dir else ''
        if args.export and export_dir:
            os.makedirs(export_dir, exist_ok=True)

        try:
            result = test.save_data(
                case_name=case_name,
                is_upload=not args.no_upload,
                is_export=args.export,
                export_format=EXPORT_FORMATS[args.export_format],
                export_directory=export_dir,
                extra_info={
                    'case': os.path.basename(args.case) if args.case else 'timed',
                    'loop': str(args.loop),
                    'speed': str(args.speed or 1),
                    'duration_s': '%.1f' % elapsed,
                },
            )
            logging.info('PerfDog: 数据已保存 case_name=%s', case_name)
            if result is not None:
                logging.info('PerfDog: save_data 返回\n%s', result)
        except Exception as e:
            logging.error('PerfDog: save_data 失败: %s', e)
            return 1

    finally:
        # 必要的资源释放
        if test.is_start():
            test.stop()

    return 1 if workload_error else 0


def _run_replay_workload(test, args, started_at):
    """把回放进度打成 PerfDog label / note，回放结束才返回"""

    def on_round(n, total):
        test.set_label('round_%d_%d' % (n, total))
        logging.info('PerfDog: 打标 round_%d/%d', n, total)

    test.set_label('replay_begin')
    test.add_note('replay_begin', int((time.time() - started_at) * 1000))

    run_replay(
        args.case,
        loop=args.loop,
        speed=args.speed,
        serial=args.device,
        on_round=on_round,
        timeout=args.replay_timeout,
    )


if __name__ == '__main__':
    sys.exit(main())
