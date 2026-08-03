# coding: utf-8

import logging
import subprocess

import perfdog_pb2

import config
from perfdog import Service

DEFAULT_PORT = 23456


def create_service(port=DEFAULT_PORT):
    # 连接 PerfDog 之前先校验配置，避免抛出晦涩的底层异常
    config.ensure_configured()
    service = Service(config.SERVICE_TOKEN, config.SERVICE_PATH, port=port)
    service.get_device_event_stream(lambda event: print_device(event))
    return service


def detect_adb_devices():
    """返回 adb 已连接的设备 ID 列表"""
    try:
        out = subprocess.check_output(['adb', 'devices'], text=True, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError) as e:
        logging.warning('执行 adb devices 失败: %s', e)
        return []

    devices = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == 'device':
            devices.append(parts[0])
    return devices


def resolve_device_id(device_id=None):
    """确定目标设备：显式参数 > 配置文件 > 唯一在线设备

    :raise config.ConfigError: 无设备或存在多台设备却未指定
    """
    if device_id:
        return device_id
    if config.DEFAULT_DEVICE:
        return config.DEFAULT_DEVICE

    devices = detect_adb_devices()
    if not devices:
        raise config.ConfigError('未检测到在线设备，请先执行 adb devices 检查连接')
    if len(devices) > 1:
        raise config.ConfigError(
            '检测到多台设备 %s，请用 -d/--device 指定，或在 local_env/.env 配置 PD_DEVICE'
            % ', '.join(devices))

    logging.info('自动选用唯一在线设备: %s', devices[0])
    return devices[0]


def resolve_package(package=None):
    """确定被测包名：显式参数 > 配置文件"""
    pkg = package or config.DEFAULT_PACKAGE
    if not pkg:
        raise config.ConfigError(
            '未指定被测 App 包名，请用 -p/--package 传入，'
            '或在 local_env/.env 配置 PD_PACKAGE\n'
            '（可用 python perfdog/cmds.py getapps <设备ID> 查看包名列表）')
    return pkg


def get_all_types(device):
    types, dynamicTypes = device.get_available_types()
    return [ty for ty in types], [(dynamicType.type, dynamicType.category) for dynamicType in dynamicTypes]


def set_floating_window(device):
    position = perfdog_pb2.HIDE
    font_color = perfdog_pb2.Color(red=0.49, green=0.93, blue=0.89, alpha=1.0)
    record_hotkey = ''
    add_label_hotkey = ''
    device.set_floating_window_preferences(position, font_color, record_hotkey, add_label_hotkey)


def print_device(event):
    if event.eventType == perfdog_pb2.ADD:
        logging.info("AddDevice: \n%s", event.device)
    elif event.eventType == perfdog_pb2.REMOVE:
        logging.info("RemoveDevice: \n%s", event.device)
