# coding: utf-8
"""配置加载：环境变量 > local_env/.env

本文件会入库，**不要在这里写 token 或本机绝对路径**。
真实配置放在 local_env/.env（已被 .gitignore 忽略），格式见 local_env/.env.example：

    SERVICE_TOKEN = 'xxxxxxxx'
    SERVICE_PATH  = '/path/to/PerfDogService'
    PD_PACKAGE    = 'com.example.app'
    PD_DEVICE     = ''            # 留空则自动探测唯一在线设备

也可以用环境变量覆盖（优先级更高）：
    PERFDOG_TOKEN / PERFDOG_SERVICE_PATH / PD_PACKAGE / PD_DEVICE
    PERFDOG_ENV_FILE=/other/path/.env   指定其它配置文件
"""

import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ENV_FILE = os.path.join(PROJECT_ROOT, 'local_env', '.env')
ENV_FILE = os.environ.get('PERFDOG_ENV_FILE') or DEFAULT_ENV_FILE


class ConfigError(RuntimeError):
    """配置缺失或非法"""


def _parse_env_file(path):
    """极简 .env 解析：支持 KEY = 'value' / KEY=value / # 注释"""
    data = {}
    if not os.path.isfile(path):
        return data
    with open(path, encoding='utf-8') as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            key, value = key.strip(), value.strip()
            # 去掉成对的引号
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            if key:
                data[key] = value
    return data


_FILE_ENV = _parse_env_file(ENV_FILE)


def get(name, *aliases, **kwargs):
    """取配置：先查所有环境变量名，再查 .env 中的同名键"""
    default = kwargs.pop('default', None)
    keys = (name,) + aliases
    for key in keys:
        value = os.environ.get(key)
        if value:
            return value.strip()
    for key in keys:
        value = _FILE_ENV.get(key)
        if value:
            return value.strip()
    return default


SERVICE_TOKEN = get('PERFDOG_TOKEN', 'SERVICE_TOKEN')
SERVICE_PATH = get('PERFDOG_SERVICE_PATH', 'SERVICE_PATH')
if SERVICE_PATH:
    SERVICE_PATH = os.path.expanduser(SERVICE_PATH)

# 被测对象的缺省值，同样不写死在代码里；缺失时由调用方显式要求
DEFAULT_DEVICE = get('PD_DEVICE', 'PERFDOG_DEVICE')
DEFAULT_PACKAGE = get('PD_PACKAGE', 'PERFDOG_PACKAGE')

_HINT = (
    '请在 %s 中配置（可参考 local_env/.env.example）：\n'
    "    SERVICE_TOKEN = '<PerfDog 申请到的 token>'\n"
    "    SERVICE_PATH  = '<PerfDogService 可执行文件路径>'\n"
    '或用环境变量 PERFDOG_TOKEN / PERFDOG_SERVICE_PATH 覆盖。'
) % ENV_FILE


def ensure_configured():
    """在真正连接 PerfDog 之前校验配置，避免报错信息晦涩"""
    missing = []
    if not SERVICE_TOKEN:
        missing.append('SERVICE_TOKEN')
    if not SERVICE_PATH:
        missing.append('SERVICE_PATH')
    if missing:
        raise ConfigError('缺少配置 %s\n%s' % ('、'.join(missing), _HINT))

    if not os.path.isfile(SERVICE_PATH):
        raise ConfigError('SERVICE_PATH 指向的文件不存在: %s\n%s' % (SERVICE_PATH, _HINT))
    if not os.access(SERVICE_PATH, os.X_OK):
        raise ConfigError('SERVICE_PATH 没有可执行权限: %s' % SERVICE_PATH)
    return True
